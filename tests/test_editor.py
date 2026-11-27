"""Offline provenance boundaries and mocked Gemini HTTP behavior."""

from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from levyquant.editor import (
    DEFAULT_MODEL, HEADLINE_ONLY_SUMMARY, EditorError, EditorValidationError, editor_to_digest,
    generate_editor, load_editor_schema, validate_editor, translate_digest, SECTION_IDS, SECTION_TITLES,
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

    def test_headline_only_source_cannot_be_expanded_into_inferred_detail(self):
        title = "Example Company announces a research partnership"
        self.articles[0].update(title=title, summary="", content=title,
                                media_type="headline_only", content_scope="search_headline_and_link")
        item = self.editor["sections"][0]["items"][0]
        item.update(title=title, summary=HEADLINE_ONLY_SUMMARY, analysis="",
                    evidence=[{"source_id": "art0001", "quote": title}])
        self.assertTrue(validate_editor(self.editor, self.articles)["valid"])
        for change in ({"title": "Example Company acquires a research business"},
                       {"summary": "The deal adds new factories and customers."},
                       {"analysis": "This caused the stock to rise."}):
            with self.subTest(change=change):
                candidate = deepcopy(self.editor)
                candidate["sections"][0]["items"][0].update(change)
                report = validate_editor(candidate, self.articles)
                self.assertFalse(report["valid"])
                self.assertIn("headline_only_expansion", {issue["code"] for issue in report["errors"]})

    def test_headline_only_display_does_not_relax_financial_evidence_checks(self):
        title = "Example Company price target rises to $100"
        self.articles[0].update(title=title, summary="", content=title, media_type="headline_only")
        item = self.editor["sections"][0]["items"][0]
        item.update(title=title, summary=HEADLINE_ONLY_SUMMARY, analysis="",
                    evidence=[{"source_id": "art0001", "quote": title}])
        report = validate_editor(self.editor, self.articles)
        self.assertFalse(report["valid"])
        self.assertIn("financial_value_not_upstream_verified", {issue["code"] for issue in report["errors"]})

    def test_unrepaired_headline_expansion_is_omitted_without_losing_valid_research(self):
        title = "Example Company announces a research partnership"
        headline = {**self.articles[0], "id": "headline1", "title": title, "summary": "", "content": title,
                    "media_type": "headline_only", "content_scope": "search_headline_and_link"}
        candidate = deepcopy(self.editor)
        candidate["sections"].append({"id": "company_sector", "items": [{
            "title": title, "summary": "An unsupported expansion detail.", "analysis": "",
            "source_ids": ["headline1"], "evidence": [{"source_id": "headline1", "quote": title}],
            "event_time": None}]})
        with patch("levyquant.editor._OPEN", side_effect=[self.response(candidate), self.response(candidate)]) as opened:
            result = generate_editor(self.articles + [headline], api_key=self.key, prompt="A sectioned digest.")
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(result, self.editor)
        self.assertEqual(result.generation_metadata["discarded_items"], 1)
        self.assertIn("headline_only_expansion", result.generation_metadata["discarded_error_codes"])

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

    def test_event_date_and_time_preserve_their_verified_precision(self):
        section = self.editor["sections"][0]
        section["id"] = "upcoming_events"
        for value, precision, displayed in (
            ("2026-11-26T01:30:00Z", "datetime", "2026-11-25 20:30 EST"),
            ("2026-11-26", "day", "2026-11-26"),
        ):
            with self.subTest(precision=precision):
                event = {"value": value, "precision": precision, "status": "confirmed"}
                self.articles[0]["event_time"] = {**event, "evidence": self.quote}
                section["items"][0]["event_time"] = event
                digest = editor_to_digest(self.editor, self.articles, date="2026-11-25", cutoff="2026-11-25T12:00:00Z")
                self.assertEqual(digest["sections"][0]["items"][0]["event_time"]["value"], value)
                for output in render_digest(digest, self.articles):
                    self.assertIn(f"{displayed} · {precision} · confirmed", output)

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
        articles[0].update(content_scope="official_abstract", media_type="research", date_basis="published",
                           audio_url="https://example.org/unrequested-audio.mp3")
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
        self.assertNotIn("unrequested-audio.mp3", body_text)
        body = json.loads(body_text)
        source = json.loads(body["contents"][0]["parts"][0]["text"])["articles"][0]
        self.assertEqual(source["content_scope"], "official_abstract")
        self.assertEqual(source["media_type"], "research")
        self.assertEqual(source["date_basis"], "published")
        instructions = body["systemInstruction"]["parts"][0]["text"]
        self.assertIn("not audio or a transcript", instructions)
        self.assertIn("not a full paper or a replication", instructions)
        self.assertIn("not independently verified full-article evidence", " ".join(instructions.split()))
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

    def http_error(self, status):
        return HTTPError("https://generativelanguage.googleapis.com/", status,
                         "reason " + self.key, None, BytesIO(("provider-body " + self.key).encode()))

    def test_http_client_errors_never_leak_body_retry_or_trigger_fallback(self):
        for status in (400, 401, 403, 429):
            with self.subTest(status=status):
                with patch("levyquant.editor._OPEN", side_effect=self.http_error(status)) as opened, \
                        patch("levyquant.editor.time.sleep") as sleep:
                    with self.assertRaises(EditorError) as captured:
                        generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()
                self.assertIn("HTTP " + str(status), str(captured.exception))
                self.assertEqual(captured.exception.error_code, "model_http_error")
                self.assertEqual(captured.exception.http_status, status)
                self.assertNotIn(self.key, str(captured.exception))
                self.assertNotIn("provider-body", str(captured.exception))

    def test_transient_http_retry_uses_same_request_and_shared_budget(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                with patch("levyquant.editor._OPEN", side_effect=[self.http_error(status), self.response()]) as opened, \
                        patch("levyquant.editor.time.sleep") as sleep:
                    result = generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertEqual(result, self.editor)
                self.assertEqual(result.generation_metadata["requests"], 2)
                self.assertEqual(opened.call_count, 2)
                sleep.assert_called_once_with(2)
                first, second = (call.args[0] for call in opened.call_args_list)
                self.assertEqual(first.full_url, second.full_url)
                self.assertEqual(first.data, second.data)
                self.assertEqual(first.header_items(), second.header_items())
                self.assertEqual(len(json.loads(second.data)["contents"]), 1)

    def test_second_http_failure_exhausts_retry_or_repair_budget(self):
        for first_failure in ("transient", "validation"):
            with self.subTest(first_failure=first_failure):
                first = self.http_error(503) if first_failure == "transient" else self.response(raw_editor="invalid JSON")
                with patch("levyquant.editor._OPEN", side_effect=[first, self.http_error(502)]) as opened, \
                        patch("levyquant.editor.time.sleep") as sleep:
                    with self.assertRaises(EditorError) as captured:
                        generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(captured.exception.error_code, "model_http_error")
                self.assertEqual(captured.exception.http_status, 502)
                self.assertNotIn(self.key, str(captured.exception))
                if first_failure == "transient":
                    sleep.assert_called_once_with(2)
                else:
                    sleep.assert_not_called()

    def test_output_after_transient_retry_uses_existing_survivor_rules_without_third_request(self):
        for defect in ("mixed_items", "all_items_invalid", "schema", "unknown_source"):
            with self.subTest(defect=defect):
                output = deepcopy(self.editor)
                bad = deepcopy(output["sections"][0]["items"][0])
                bad.update(title="Unsupported sample size", summary="Researchers used 999 observations.")
                output["sections"][0]["items"].append(bad)
                if defect == "all_items_invalid":
                    output["sections"][0]["items"] = [bad]
                elif defect == "schema":
                    output["unexpected"] = "not allowed"
                elif defect == "unknown_source":
                    bad["source_ids"] = ["unknown"]
                with patch("levyquant.editor._OPEN", side_effect=[self.http_error(503), self.response(output)]) as opened, \
                        patch("levyquant.editor.time.sleep") as sleep:
                    if defect == "mixed_items":
                        result = generate_editor(self.articles, api_key=self.key, prompt="Digest")
                        self.assertEqual(result, self.editor)
                        self.assertTrue(validate_editor(result, self.articles)["valid"])
                        self.assertEqual(result.generation_metadata["requests"], 2)
                        self.assertEqual(result.generation_metadata["discarded_items"], 1)
                    else:
                        with self.assertRaises(EditorValidationError):
                            generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertEqual(opened.call_count, 2)
                sleep.assert_called_once_with(2)

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
        for failure in (URLError(self.key), TimeoutError(self.key)):
            with self.subTest(failure=type(failure).__name__):
                with patch("levyquant.editor._OPEN", side_effect=failure) as opened, \
                        patch("levyquant.editor.time.sleep") as sleep:
                    with self.assertRaises(EditorError) as captured:
                        generate_editor(self.articles, api_key=self.key, prompt="Digest")
                self.assertNotIn(self.key, str(captured.exception))
                self.assertEqual(captured.exception.error_code, "model_network_error")
                self.assertIsNone(captured.exception.http_status)
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()
        with patch("levyquant.editor._OPEN", return_value=self.response(finish="MAX_TOKENS")) as opened:
            with self.assertRaises(EditorError) as captured:
                generate_editor(self.articles, api_key=self.key, prompt="Digest")
        self.assertEqual(captured.exception.error_code, "incomplete_generation")
        self.assertIsNone(captured.exception.http_status)
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


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.key = "offline-translation-key"
        self.digest = {"language": "en", "title": "LevyQuant Morning Briefing", "edition": "Morning Edition",
            "date": "2026-11-27", "cutoff": "2026-11-27T12:00:00Z", "mode": "live",
            "sections": [{"id": "quant_research", "title": "QUANT RESEARCH", "items": [{
                "title": "Method comparison", "summary": "Researchers use 120 observations.",
                "analysis": "Further testing remains necessary.", "source_ids": ["original-source-id"],
                "evidence": [{"source_id": "original-source-id", "quote": "Original English evidence."}],
                "event_time": None}]}], "coverage_warnings": ["Feed excerpts only."]}
        self.words = {"Method comparison": "方法比较", "Researchers use 120 observations.": "研究人员使用120个观测值。",
                      "Further testing remains necessary.": "仍需进一步测试。", "Feed excerpts only.": "仅使用来源摘要。"}

    def object_for(self, payload):
        context = json.loads(payload["contents"][0]["parts"][0]["text"])
        return {"translations": [{"key": row["key"], "text": self.words[row["text"]]} for row in context["texts"]]}

    def answer(self, payload, *args):
        return json.dumps(self.object_for(payload), ensure_ascii=False)

    def translate(self, digest=None):
        return translate_digest(self.digest if digest is None else digest, api_key=self.key,
                                model=DEFAULT_MODEL, max_output_tokens=4096)

    def test_structure_order_provenance_and_original_chinese_headline_are_preserved(self):
        second = deepcopy(self.digest["sections"][0]["items"][0])
        second["title"] = "已有中文标题 120"
        second["source_ids"] = ["another-source"]
        self.digest["sections"][0]["items"].append(second)
        self.digest["sections"].append({"id": "watchlist", "title": "WATCHLIST", "items": []})
        original = deepcopy(self.digest)
        with patch("levyquant.editor._request_model", side_effect=self.answer) as model:
            result = self.translate()
        self.assertEqual(model.call_count, 1)
        self.assertEqual(self.digest, original)
        self.assertEqual((result["language"], result["title"], result["edition"]), ("zh-CN", "LevyQuant 晨间简报", "晨间版"))
        self.assertEqual([section["id"] for section in result["sections"]], ["quant_research", "watchlist"])
        self.assertEqual(result["sections"][1]["title"], SECTION_TITLES["zh-CN"][SECTION_IDS.index("watchlist")])
        self.assertEqual(result["sections"][1]["items"], [])
        for before, after in zip(original["sections"][0]["items"], result["sections"][0]["items"]):
            for field in ("source_ids", "evidence", "event_time"):
                self.assertEqual(after[field], before[field])
        self.assertEqual(result["sections"][0]["items"][1]["title"], second["title"])
        self.assertEqual(result["sections"][0]["items"][0]["summary"], "研究人员使用120个观测值。")
        self.assertEqual(result["coverage_warnings"], ["仅使用来源摘要。"])
        self.assertEqual((result["date"], result["cutoff"]), (original["date"], original["cutoff"]))
        sent = json.dumps(model.call_args.args[0], ensure_ascii=False)
        self.assertNotIn(second["title"], sent)
        self.assertNotIn("Original English evidence", sent)
        self.assertNotIn("original-source-id", sent)

    def test_missing_reordered_duplicate_or_extra_output_never_returns_a_partial_digest(self):
        for defect in ("missing", "reordered", "duplicate", "extra", "not_json"):
            with self.subTest(defect=defect):
                def invalid(payload, *args):
                    value = self.object_for(payload)
                    rows = value["translations"]
                    if defect == "missing": rows.pop()
                    elif defect == "reordered": rows.reverse()
                    elif defect == "duplicate": rows[-1]["key"] = rows[0]["key"]
                    elif defect == "extra": rows[0]["url"] = "https://invented.example"
                    return "not JSON" if defect == "not_json" else json.dumps(value)
                with patch("levyquant.editor._request_model", side_effect=invalid) as model:
                    with self.assertRaises(EditorError) as caught:
                        self.translate()
                self.assertEqual(model.call_count, 2)
                self.assertEqual(caught.exception.error_code, "translation_validation_failed")

    def test_numeric_sign_percent_currency_and_scale_are_literal_not_reinterpreted(self):
        source = "The rate is -2.5% and the total is $12 million."
        self.digest["sections"][0]["items"][0]["summary"] = source
        self.words[source] = "利率为 -2.5%，总额为 $12 million。"
        with patch("levyquant.editor._request_model", side_effect=self.answer):
            self.assertIn("$12 million", self.translate()["sections"][0]["items"][0]["summary"])
        for wrong in ("利率为 2.5%，总额为 $12 million。", "利率为 -2.5，总额为 $12 million。",
                      "利率为 -2.5%，总额为 $13 million。", "利率为 -2.5%，总额为 $12 billion。",
                      "利率为 -2.5%，总额为 12 million。", "利率为 -2.5%，总额为 $12 million，另有3项。"):
            with self.subTest(wrong=wrong):
                def altered(payload, *args):
                    value = self.object_for(payload)
                    next(row for row in value["translations"] if row["key"].endswith(".summary"))["text"] = wrong
                    return json.dumps(value)
                with patch("levyquant.editor._request_model", side_effect=altered) as model:
                    with self.assertRaises(EditorError): self.translate()
                self.assertEqual(model.call_count, 2)

    def test_original_iso_timestamp_and_renderer_event_suffix_are_preserved(self):
        item = self.digest["sections"][0]["items"][0]
        item["event_time"] = {"value": "2026-11-27T14:00:00Z", "precision": "datetime", "status": "confirmed"}
        suffix = "\n2026-11-27 09:00 EST · datetime · confirmed"
        item["summary"] += suffix
        with patch("levyquant.editor._request_model", side_effect=self.answer) as model:
            result = self.translate()
        self.assertTrue(result["sections"][0]["items"][0]["summary"].endswith(suffix))
        self.assertNotIn("2026-11-27 09:00 EST", json.dumps(model.call_args.args[0]))
        source = "The record is timestamped 2026-11-27T14:00:00Z."
        item.update(summary=source, event_time=None)
        self.words[source] = "记录的时间戳是 2026-11-27T14:00:00Z。"
        with patch("levyquant.editor._request_model", side_effect=self.answer):
            self.assertIn("2026-11-27T14:00:00Z", self.translate()["sections"][0]["items"][0]["summary"])
        self.words[source] = "记录的时间戳是 2026-11-27 14:00:00Z。"
        with patch("levyquant.editor._request_model", side_effect=self.answer):
            with self.assertRaises(EditorError): self.translate()

    def test_new_links_html_or_unchanged_english_are_rejected_and_repair_uses_only_clean_input(self):
        for wrong in ("方法 https://invented.example/private", "方法 invented.example", "<b>方法</b>",
                      "&lt;script&gt;方法&lt;/script&gt;", "Method comparison"):
            with self.subTest(wrong=wrong):
                def invalid(payload, *args):
                    value = self.object_for(payload)
                    value["translations"][0]["text"] = wrong
                    return json.dumps(value)
                with patch("levyquant.editor._request_model", side_effect=invalid) as model:
                    with self.assertRaises(EditorError): self.translate()
                self.assertEqual(model.call_count, 2)
        calls = []
        def repaired(payload, *args):
            calls.append(deepcopy(payload))
            value = self.object_for(payload)
            if len(calls) == 1:
                value["translations"][0]["text"] = "错误 https://invented.example/private-marker"
            return json.dumps(value)
        with patch("levyquant.editor._request_model", side_effect=repaired):
            self.assertEqual(self.translate()["language"], "zh-CN")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("private-marker", json.dumps(calls[1]))
        self.assertEqual(len(calls[1]["contents"]), 1)
        self.assertIn("correction", json.loads(calls[1]["contents"][0]["parts"][0]["text"]))

    def test_completely_empty_payload_skips_model_but_empty_edition_notices_are_translated(self):
        empty = {"language": "en", "sections": [{"id": "quant_research", "title": "QUANT RESEARCH", "items": []}], "coverage_warnings": []}
        with patch("levyquant.editor._request_model") as model:
            result = translate_digest(empty, api_key="", model=DEFAULT_MODEL, max_output_tokens=4096)
        model.assert_not_called()
        self.assertEqual(result["language"], "zh-CN")
        self.assertEqual(result["sections"][0]["title"], "量化研究")
        empty["coverage_warnings"] = ["Feed excerpts only."]
        with patch("levyquant.editor._request_model", side_effect=self.answer) as model:
            result = self.translate(empty)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["coverage_warnings"], ["仅使用来源摘要。"])

    def test_real_request_wrapper_keeps_credentials_only_in_header_and_sends_no_metadata_or_links(self):
        self.digest.update(recipient="private-reader@example.org", smtp_password="private-password",
                           source_link="https://source.example/only-metadata")
        def respond(req, **kwargs):
            payload = json.loads(req.data)
            body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": self.answer(payload)}]}}]}
            return BytesIO(json.dumps(body).encode())
        with patch("levyquant.editor._OPEN", side_effect=respond) as opened:
            self.translate()
        self.assertEqual(opened.call_count, 1)
        req = opened.call_args.args[0]
        self.assertEqual(req.get_header("X-goog-api-key"), self.key)
        self.assertNotIn(self.key, req.full_url)
        for private in (self.key, "private-reader", "private-password", "source.example", "original-source-id", "Original English evidence"):
            self.assertNotIn(private, req.data.decode())
        payload = json.loads(req.data)
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 4096)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("quoted strings", payload["systemInstruction"]["parts"][0]["text"])
        self.assertNotIn("tools", payload)

    def test_invalid_input_or_transport_errors_stop_without_provider_body_leaks(self):
        invalid = deepcopy(self.digest)
        invalid["sections"][0]["items"][0]["summary"] = "https://not-public-copy.example/path"
        with patch("levyquant.editor._request_model") as model:
            with self.assertRaises(EditorError) as caught: self.translate(invalid)
        self.assertEqual(caught.exception.error_code, "translation_invalid_input")
        model.assert_not_called()
        with patch("levyquant.editor._OPEN", side_effect=URLError(self.key)) as opened:
            with self.assertRaises(EditorError) as caught: self.translate()
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(caught.exception.error_code, "model_network_error")
        self.assertNotIn(self.key, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
