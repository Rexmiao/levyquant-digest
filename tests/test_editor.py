"""Offline provenance boundaries and mocked Gemini HTTP behavior."""

from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from levyquant.editor import (
    DEFAULT_MODEL, EditorError, EditorValidationError, editor_to_digest,
    generate_editor, load_editor_schema, validate_editor,
)
from levyquant.render import render_digest


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.quote = "Researchers compare linear methods using 120 observations."
        self.articles = [{
            "id": "art0001", "canonical_id": "canonical-example", "source": "Example research source",
            "title": "A method comparison", "summary": self.quote,
            "url": "https://example.org/paper?a=1&b=2", "published_at": "2026-11-25T06:00:00-05:00",
            "section": "quant_research",
        }]
        self.editor = {"sections": [{"id": "quant_research", "items": [{
            "title": "A method comparison", "summary": self.quote,
            "analysis": "Additional out-of-sample testing is needed.",
            "source_ids": ["art0001"], "evidence": [{"source_id": "art0001", "quote": self.quote}],
            "event_time": None,
        }]}]}
        self.key = "offline-test-key-do-not-log"

    def response(self, editor=None, *, raw_editor=None, finish="STOP"):
        output = raw_editor if raw_editor is not None else json.dumps(editor if editor is not None else self.editor)
        return BytesIO(json.dumps({"candidates": [{"finishReason": finish, "content": {"parts": [{"text": output}]}}]}).encode())

    def test_valid_excerpt_numbers_empty_sections_and_schema(self):
        self.editor["sections"].append({"id": "earnings", "items": []})
        report = validate_editor(self.editor, self.articles)
        self.assertTrue(report["valid"])
        self.assertFalse(report["fact_checked"])
        self.assertEqual(report["counts"]["accepted_items"], 1)
        self.assertEqual(len(report["editor_output"]["sections"]), 1)
        schema = load_editor_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(len(schema["properties"]["sections"]["items"]["properties"]["id"]["enum"]), 11)

    def test_unknown_source_model_url_and_unquoted_number_block(self):
        for change, expected in [
            ({"source_ids": ["unknown"]}, "unknown_or_missing_source"),
            ({"summary": "Read https://invented.example/story"}, "model_url_not_allowed"),
            ({"summary": "Researchers used 999 observations."}, "unsupported_numeric_claim"),
            ({"url": "https://invented.example/story"}, "unexpected_field"),
        ]:
            with self.subTest(expected=expected):
                editor = deepcopy(self.editor)
                editor["sections"][0]["items"][0].update(change)
                report = validate_editor(editor, self.articles)
                self.assertFalse(report["valid"])
                self.assertIn(expected, {error["code"] for error in report["errors"]})

    def test_financial_number_requires_trusted_upstream_record(self):
        quote = "Revenue was $12 million."
        self.articles[0]["summary"] = quote
        item = self.editor["sections"][0]["items"][0]
        item.update(title="Quarterly disclosure", summary=quote,
                    evidence=[{"source_id": "art0001", "quote": quote}])
        report = validate_editor(self.editor, self.articles)
        self.assertFalse(report["valid"])
        self.assertIn("financial_value_not_upstream_verified", {error["code"] for error in report["errors"]})
        self.assertFalse(report["fact_checked"])
        self.articles[0]["verified_numbers"] = [{"value": "$12 million", "currency": "USD", "unit": "million", "evidence": quote}]
        self.assertTrue(validate_editor(self.editor, self.articles)["valid"])

    def test_time_window_preserved_and_cannot_be_refined_to_january_first(self):
        quote = "A release is planned for Q1 2027."
        self.articles[0]["summary"] = quote
        event = {"value": "2027-Q1", "precision": "quarter", "status": "estimated"}
        self.articles[0]["event_time"] = {**event, "evidence": quote}
        section = self.editor["sections"][0]
        section["id"] = "watchlist"
        section["items"][0].update(title="A proposed release", summary=quote, event_time=event,
                                   evidence=[{"source_id": "art0001", "quote": quote}])
        self.assertTrue(validate_editor(self.editor, self.articles)["valid"])
        digest = editor_to_digest(self.editor, self.articles, date="2026-11-25", cutoff="2026-11-25T07:00:00-05:00")
        self.assertIn("2027-Q1", digest["sections"][0]["items"][0]["summary"])
        self.assertNotIn("2027-01-01", digest["sections"][0]["items"][0]["summary"])
        section["id"] = "upcoming_events"
        section["items"][0]["event_time"] = {"value": "2027-01-01", "precision": "day", "status": "confirmed"}
        report = validate_editor(self.editor, self.articles)
        self.assertFalse(report["valid"])
        self.assertIn("event_time_not_upstream_verified", {error["code"] for error in report["errors"]})

    def test_demo_adapter_is_unsendable_and_renderer_escapes_html(self):
        self.editor["sections"][0]["items"][0]["title"] = '<script>alert("unsafe")</script>'
        self.articles[0]["source"] = "<b>Publisher</b>"
        digest = editor_to_digest(self.editor, self.articles, date="YYYY-MM-DD", cutoff="pending", mode="demo")
        self.assertFalse(digest["send_allowed"])
        html, text = render_digest(digest, self.articles)
        self.assertIn("DEMO TEMPLATE / NOT LIVE NEWS / DO NOT SEND", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>Publisher</b>", html)
        self.assertIn("Editorial analysis:", text)
        self.assertIn("a=1&amp;b=2", html)
        with self.assertRaises(EditorError):
            editor_to_digest({"sections": []}, self.articles, date="2026-11-25", cutoff="2026-11-25T07:00:00-05:00")

    def test_gemini_request_uses_header_schema_cap_and_public_context_only(self):
        articles = deepcopy(self.articles)
        articles[0]["unrelated_private_field"] = "private-value-never-send"
        history = [{"title": "Prior topic", "source_ids": ["old"], "recipient": "private@example.org", "smtp_password": "private-password"}]
        with patch("levyquant.editor._OPEN", return_value=self.response()) as opened:
            result = generate_editor(articles, api_key=self.key, prompt="English digest; preserve Chinese titles.", history=history, max_output_tokens=4096)
        self.assertEqual(result, self.editor)
        self.assertEqual(opened.call_count, 1)
        req = opened.call_args.args[0]
        self.assertIn(DEFAULT_MODEL + ":generateContent", req.full_url)
        self.assertNotIn(self.key, req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), self.key)
        body_text = req.data.decode()
        self.assertNotIn(self.key, body_text)
        self.assertNotIn("private@example.org", body_text)
        self.assertNotIn("private-password", body_text)
        self.assertNotIn("private-value-never-send", body_text)
        body = json.loads(body_text)
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 4096)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("responseJsonSchema", body["generationConfig"])
        self.assertNotIn("tools", body)
        self.assertNotIn("cachedContent", body)

    def test_one_repair_request_and_never_a_third(self):
        with patch("levyquant.editor._OPEN", side_effect=[self.response(raw_editor="not JSON"), self.response()]) as opened:
            result = generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertEqual(result, self.editor)
        self.assertEqual(opened.call_count, 2)
        repair = json.loads(opened.call_args.args[0].data)
        self.assertEqual(len(repair["contents"]), 3)
        invalid = deepcopy(self.editor)
        invalid["sections"][0]["items"][0]["source_ids"] = ["missing"]
        with patch("levyquant.editor._OPEN", side_effect=[self.response(invalid), self.response(invalid)]) as opened:
            with self.assertRaises(EditorValidationError):
                generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertEqual(opened.call_count, 2)

    def test_http_quota_errors_never_leak_body_or_trigger_fallback(self):
        api_error = HTTPError("https://generativelanguage.googleapis.com/", 429,
                              "reason " + self.key, None, BytesIO(("provider-body " + self.key).encode()))
        with patch("levyquant.editor._OPEN", side_effect=api_error) as opened:
            with self.assertRaises(EditorError) as captured:
                generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertEqual(opened.call_count, 1)
        self.assertIn("HTTP 429", str(captured.exception))
        self.assertNotIn(self.key, str(captured.exception))
        self.assertNotIn("provider-body", str(captured.exception))

    def test_after_one_repair_omit_only_bad_items_and_keep_every_valid_item(self):
        articles, good_items = [], []
        for number, title in enumerate(("Linear estimates", "Tree estimates", "Temporal validation",
                                        "Sample selection", "Model stability", "Forecast comparison"), 1):
            source_id = f"art{number:04d}"
            quote = "Researchers examine " + title.lower() + "."
            articles.append({**self.articles[0], "id": source_id, "title": title, "summary": quote,
                             "url": f"https://example.org/paper/{number}"})
            good_items.append({"title": title, "summary": quote, "analysis": "",
                               "source_ids": [source_id], "evidence": [{"source_id": source_id, "quote": quote}],
                               "event_time": None})
        bad_number = deepcopy(good_items[0])
        bad_number.update(title="Unsupported sample size", summary="Researchers used 999 observations.")
        bad_date = deepcopy(good_items[1])
        bad_date.update(title="Unsupported exact date", summary="An update is expected January 1, 2027.")
        output = {"sections": [
            {"id": "quant_research", "items": [good_items[0], bad_number, *good_items[1:]]},
            {"id": "geopolitics_macro", "items": [bad_date]},
        ]}
        original = deepcopy(output)
        with patch("levyquant.editor._OPEN", side_effect=[self.response(output), self.response(output)]) as opened:
            result = generate_editor(articles, api_key=self.key, prompt="Digest")
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(output, original)
        self.assertEqual(result, {"sections": [{"id": "quant_research", "items": good_items}]})
        self.assertTrue(validate_editor(result, articles)["valid"])
        self.assertEqual(result.generation_metadata["requests"], 2)
        self.assertEqual(result.generation_metadata["discarded_items"], 2)
        self.assertIn("unsupported_precise_date", result.generation_metadata["discarded_error_codes"])
        self.assertIn("unsupported_numeric_claim", result.generation_metadata["discarded_error_codes"])
        self.assertEqual(set(json.loads(json.dumps(result))), {"sections"})
        snapshot = result.generation_metadata
        snapshot["discarded_items"] = 999
        self.assertEqual(result.generation_metadata["discarded_items"], 2)
        with self.assertRaises(AttributeError):
            result.generation_metadata = {}
        digest = editor_to_digest(result, articles, date="2026-11-25", cutoff="2026-11-25T07:00:00-05:00",
                                  coverage_warnings=["Existing source coverage notice."])
        self.assertEqual(len(digest["sections"][0]["items"]), 6)
        self.assertEqual(digest["editor_generation"]["discarded_items"], 2)
        self.assertEqual(digest["coverage_warnings"][0], "Existing source coverage notice.")
        self.assertTrue(any("Excluded 2 editorial items" in notice for notice in digest["coverage_warnings"]))

    def test_all_invalid_items_still_fail_after_two_requests(self):
        invalid = deepcopy(self.editor)
        invalid["sections"][0]["items"][0]["summary"] = "Researchers used 999 observations."
        with patch("levyquant.editor._OPEN", side_effect=[self.response(invalid), self.response(invalid)]) as opened:
            with self.assertRaises(EditorValidationError) as captured:
                generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertEqual(opened.call_count, 2)
        self.assertIn("unsupported_numeric_claim", str(captured.exception))

    def test_schema_and_unknown_source_errors_are_fatal_even_with_good_items(self):
        for defect in ("item_schema", "top_level_schema", "unknown_source", "duplicate_section"):
            with self.subTest(defect=defect):
                invalid = deepcopy(self.editor)
                bad = deepcopy(invalid["sections"][0]["items"][0])
                bad["title"] = "A separate item"
                if defect == "item_schema":
                    bad["extra_field"] = "not allowed"
                elif defect == "unknown_source":
                    bad["source_ids"] = ["missing"]
                invalid["sections"][0]["items"].append(bad)
                if defect == "top_level_schema":
                    invalid["extra_field"] = "not allowed"
                elif defect == "duplicate_section":
                    invalid["sections"].append(deepcopy(invalid["sections"][0]))
                with patch("levyquant.editor._OPEN", side_effect=[self.response(invalid), self.response(invalid)]) as opened:
                    with self.assertRaises(EditorValidationError):
                        generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertEqual(opened.call_count, 2)
        unsafe_articles = deepcopy(self.articles)
        unsafe_articles[0]["url"] = "javascript:alert(1)"
        with patch("levyquant.editor._OPEN") as opened:
            with self.assertRaises(EditorValidationError):
                generate_editor(unsafe_articles, api_key=self.key, prompt="Digest")
        self.assertEqual(opened.call_count, 0)

    def test_invalid_or_unresolvable_item_error_paths_are_not_salvaged(self):
        invalid = deepcopy(self.editor)
        bad = deepcopy(invalid["sections"][0]["items"][0])
        bad.update(title="Unsupported sample size", summary="Researchers used 999 observations.")
        invalid["sections"][0]["items"].append(bad)
        for wrong_path in ("editor_output.sections[0]", "editor_output.sections[99].items[0]",
                           "editor_output.sections[0].items[99]"):
            with self.subTest(path=wrong_path):
                def unresolvable_report(editor, articles):
                    report = validate_editor(editor, articles)
                    for issue in report["errors"]:
                        issue["path"] = wrong_path
                    return report
                with patch("levyquant.editor.validate_editor", side_effect=unresolvable_report), \
                        patch("levyquant.editor._OPEN", side_effect=[self.response(invalid), self.response(invalid)]) as opened:
                    with self.assertRaises(EditorValidationError):
                        generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertEqual(opened.call_count, 2)

    def test_network_error_and_truncated_generation_stop_without_repair(self):
        with patch("levyquant.editor._OPEN", side_effect=URLError(self.key)) as opened:
            with self.assertRaises(EditorError) as captured:
                generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertNotIn(self.key, str(captured.exception))
        self.assertEqual(opened.call_count, 1)
        with patch("levyquant.editor._OPEN", return_value=self.response(finish="MAX_TOKENS")) as opened:
            with self.assertRaises(EditorError):
                generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertEqual(opened.call_count, 1)

    def test_env_key_and_preflight_configuration_fail_without_http(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": self.key}), patch("levyquant.editor._OPEN", return_value=self.response()) as opened:
            self.assertEqual(generate_editor(self.articles, prompt="Digest"), self.editor)
            self.assertEqual(opened.call_count, 1)
        with patch.dict("os.environ", {}, clear=True), patch("levyquant.editor._OPEN") as opened:
            with self.assertRaises(EditorError):
                generate_editor(self.articles, prompt="Digest")
            with self.assertRaises(EditorError):
                generate_editor(self.articles, api_key=self.key, model="gemini-../?key=bad", prompt="Digest")
            with self.assertRaises(EditorError):
                generate_editor(self.articles, api_key=self.key, max_output_tokens=99999, prompt="Digest")
            self.assertEqual(opened.call_count, 0)


if __name__ == "__main__":
    unittest.main()
