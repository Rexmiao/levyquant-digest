from io import BytesIO
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from levyquant.sources import (
    MAX_PAGE_BYTES, _OfficialRedirectHandler, enrich_articles, extract_html_text,
)


PARAGRAPH = "The official release explains the policy change, its scope and the evidence provided by the agency. " * 8
HTML = (
    "<html><head><title>Official release</title><script>head secret</script></head><body>"
    "<nav>Navigation should disappear</nav><main><article><p>" + PARAGRAPH + "</p>"
    "<script>Script should disappear</script><div class='related-articles'>Related noise</div>"
    "<div hidden>Hidden noise</div><p>Further &amp; verified detail.</p></article></main>"
    "<footer>Footer should disappear</footer></body></html>"
)


class Response(BytesIO):
    def __init__(self, content=HTML, *, url="https://www.federalreserve.gov/newsevents/pressreleases/test.htm",
                 content_type="text/html; charset=utf-8", length=None):
        super().__init__(content.encode() if isinstance(content, str) else content)
        self.url = url
        self.headers = {"Content-Type": content_type}
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def geturl(self):
        return self.url


def article(url="https://www.federalreserve.gov/newsevents/pressreleases/test.htm", summary="Short RSS excerpt"):
    return {"id": "stable-id", "source_id": "fed_press", "source": "Federal Reserve",
            "title": "Policy release", "url": url, "summary": summary,
            "published_at": "2026-11-25T10:00:00+00:00", "section": "macro"}


class HtmlExtractionTests(unittest.TestCase):
    def test_article_text_removes_navigation_scripts_related_and_hidden_content(self):
        text, scope = extract_html_text(HTML)
        self.assertEqual(scope, "official_article_text")
        self.assertIn("policy change", text)
        self.assertIn("Further & verified detail.", text)
        for noise in ("Navigation", "Script", "Related noise", "Hidden noise", "Footer", "head secret"):
            self.assertNotIn(noise, text)

    def test_arxiv_abstract_is_not_labelled_as_full_paper(self):
        text, scope = extract_html_text("<main><h1>A paper</h1><blockquote class='abstract mathjax'>" + PARAGRAPH + "</blockquote></main>")
        self.assertEqual(scope, "official_abstract")
        self.assertEqual(text, PARAGRAPH.strip())

    def test_empty_article_does_not_hide_readable_main_text(self):
        text, scope = extract_html_text("<main><article></article><p>" + PARAGRAPH + "</p></main>")
        self.assertEqual(scope, "official_page_text")
        self.assertIn("official release", text)

    def test_redirect_is_checked_before_external_host_can_be_contacted(self):
        handler = _OfficialRedirectHandler()
        request = Request("https://www.federalreserve.gov/article")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            handler.redirect_request(request, None, 302, "Moved", {}, "https://outside.example/article")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            handler.redirect_request(request, None, 302, "Moved", {}, "https://www.federalreserve.gov.evil.example/article")


class EnrichmentTests(unittest.TestCase):
    @patch("levyquant.sources.build_opener")
    def test_planned_media_excerpts_and_podcast_descriptions_never_fetch_bodies_or_audio(self, build):
        publisher = {**article("https://www.cnbc.com/example.html", summary=""),
                     "retrieval": "feed_excerpt_only", "media_type": "publisher_feed"}
        podcast = {**article("https://example.org/episode.mp3", summary="The episode introduction advertises a discussion of market research."),
                   "media_type": "podcast", "content_scope": "podcast_episode_description",
                   "audio_url": "https://example.org/episode.mp3"}
        allowed_host_feed_only = {**article(), "retrieval": "feed_excerpt_only"}
        result, warnings = enrich_articles([publisher, podcast, allowed_host_feed_only])
        build.assert_not_called()
        self.assertEqual(warnings, [])
        self.assertTrue(all(row["enrichment_status"] == "feed_excerpt_only" and row["body"] == "" for row in result))
        self.assertEqual(result[0]["source_text"], publisher["title"])
        self.assertEqual(result[1]["content_scope"], "podcast_episode_description")
        self.assertEqual(result[1]["source_text"], podcast["summary"])
        self.assertEqual(result[1]["audio_url"], podcast["audio_url"])
        self.assertNotIn("body", podcast)

    @patch("levyquant.sources.build_opener")
    def test_incoming_abstract_scope_survives_retention_without_claiming_full_paper(self, build):
        abstract = {**article("https://arxiv.org/abs/example", summary="Research abstract material."),
                    "content_scope": "official_abstract", "media_type": "research"}
        result, warnings = enrich_articles([abstract], max_articles=0)
        build.assert_not_called()
        self.assertEqual(warnings, [])
        self.assertEqual(result[0]["content_scope"], "official_abstract")
        self.assertEqual(result[0]["source_text"], abstract["summary"])
        self.assertEqual(result[0]["body"], "")

    @patch("levyquant.sources.build_opener")
    def test_feed_only_items_do_not_spend_official_enrichment_budget(self, build):
        build.return_value.open.return_value = Response()
        media = {**article("https://www.wsj.com/example.html"), "retrieval": "feed_excerpt_only"}
        official = article()
        result, warnings = enrich_articles([media, official], max_articles=1)
        self.assertEqual(warnings, [])
        self.assertEqual(build.return_value.open.call_count, 1)
        self.assertEqual(build.return_value.open.call_args.args[0].full_url, official["url"])
        self.assertEqual(result[0]["enrichment_status"], "feed_excerpt_only")
        self.assertEqual(result[1]["enrichment_status"], "official_text_extracted")
        self.assertEqual(result[1]["content_scope"], "official_article_text")

    @patch("levyquant.sources.build_opener")
    def test_public_article_adds_source_text_without_rewriting_feed_dates_or_identity(self, build):
        opener = Mock()
        opener.open.return_value = Response()
        build.return_value = opener
        original = article()
        result, warnings = enrich_articles([original])
        enriched = result[0]
        self.assertEqual(warnings, [])
        self.assertEqual(enriched["id"], original["id"])
        self.assertEqual(enriched["summary"], original["summary"])
        self.assertEqual(enriched["published_at"], original["published_at"])
        self.assertEqual(enriched["content_scope"], "official_article_text")
        self.assertEqual(enriched["body"], enriched["source_text"])
        self.assertEqual(enriched["enrichment_status"], "official_text_extracted")
        self.assertNotIn("body", original)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)
        request = opener.open.call_args.args[0]
        self.assertNotIn("@", request.get_header("User-agent"))
        self.assertIsNone(request.get_header("Authorization"))

    @patch("levyquant.sources.build_opener")
    def test_external_and_userinfo_urls_retain_excerpt_without_network(self, build):
        for url in (
            "https://outside.example/a", "http://127.0.0.1/a",
            "https://www.apple.com.evil.example/a", "https://user:password@www.apple.com/a",
            "https://www.apple.com:8443/a", "file:///private/file",
        ):
            with self.subTest(url=url):
                result, warnings = enrich_articles([article(url)])
                self.assertEqual(result[0]["source_text"], "Short RSS excerpt")
                self.assertEqual(result[0]["content_scope"], "rss_metadata_and_feed_excerpt")
                self.assertEqual(len(warnings), 1)
        build.assert_not_called()

    @patch("levyquant.sources.build_opener")
    def test_sec_and_pdf_are_explicitly_left_as_excerpts(self, build):
        result, warnings = enrich_articles([
            article("https://www.sec.gov/Archives/edgar/data/1/filing.htm"),
            article("https://arxiv.org/pdf/2611.12345"),
        ])
        self.assertEqual([item["enrichment_status"] for item in result], ["sec_excerpt_only", "pdf_excerpt_only"])
        self.assertEqual(len(warnings), 2)
        build.assert_not_called()

    @patch("levyquant.sources.build_opener")
    def test_long_excerpt_and_zero_budget_do_not_request_pages(self, build):
        long_article = article(summary="x" * 500)
        result, _ = enrich_articles([long_article])
        self.assertEqual(result[0]["enrichment_status"], "excerpt_sufficient")
        result, _ = enrich_articles([article()], max_articles=0)
        self.assertEqual(result[0]["enrichment_status"], "budget_excerpt_only")
        build.assert_not_called()

    @patch("levyquant.sources.build_opener")
    def test_timeout_keeps_excerpt_and_reports_failure(self, build):
        build.return_value.open.side_effect = TimeoutError("timed out")
        result, warnings = enrich_articles([article()])
        self.assertEqual(result[0]["source_text"], "Short RSS excerpt")
        self.assertEqual(result[0]["enrichment_status"], "failed_excerpt_retained")
        self.assertTrue(any("TimeoutError" in warning for warning in warnings))

    @patch("levyquant.sources.build_opener")
    def test_search_headlines_preserve_scope_without_requesting_the_source_page(self, build):
        value = article("https://www.apple.com/newsroom/discovery", summary="")
        value.update(title="A source headline", retrieval="feed_excerpt_only",
                     content_scope="search_headline_and_link", media_type="headline_only")
        enriched, warnings = enrich_articles([value])
        self.assertEqual(enriched[0]["source_text"], "A source headline")
        self.assertEqual(enriched[0]["content_scope"], "search_headline_and_link")
        self.assertEqual(enriched[0]["media_type"], "headline_only")
        self.assertEqual(warnings, [])
        build.assert_not_called()

    @patch("levyquant.sources.build_opener")
    def test_rate_limit_stops_subsequent_same_host_requests_without_retry(self, build):
        build.return_value.open.side_effect = HTTPError("https://www.apple.com/a", 429, "Too Many Requests", {}, None)
        result, warnings = enrich_articles([
            article("https://www.apple.com/newsroom/a"), article("https://www.apple.com/newsroom/b"),
        ])
        self.assertEqual(build.return_value.open.call_count, 1)
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all(item["content_scope"] == "rss_metadata_and_feed_excerpt" for item in result))

    @patch("levyquant.sources.build_opener")
    def test_declared_and_actual_oversized_pages_are_rejected(self, build):
        for response in (Response(length=MAX_PAGE_BYTES + 1), Response(b"x" * (MAX_PAGE_BYTES + 1))):
            with self.subTest(declared="Content-Length" in response.headers):
                build.return_value.open.return_value = response
                result, warnings = enrich_articles([article()])
                self.assertEqual(result[0]["source_text"], "Short RSS excerpt")
                self.assertTrue(any("byte limit" in warning for warning in warnings))

    @patch("levyquant.sources.build_opener")
    def test_pdf_content_type_and_verification_pages_are_not_treated_as_article_bodies(self, build):
        for response in (
            Response(b"%PDF fake", content_type="application/pdf"),
            Response("<html><h1>Access Denied</h1><p>" + PARAGRAPH + "</p></html>"),
        ):
            with self.subTest(content_type=response.headers["Content-Type"]):
                build.return_value.open.return_value = response
                result, warnings = enrich_articles([article()])
                self.assertEqual(result[0]["body"], "")
                self.assertEqual(len(warnings), 1)

    @patch("levyquant.sources.build_opener")
    def test_article_budget_and_input_order_are_preserved(self, build):
        build.return_value.open.return_value = Response()
        result, _ = enrich_articles([article(), article("https://www.apple.com/newsroom/a")], max_articles=1)
        self.assertEqual([item["url"] for item in result], [article()["url"], "https://www.apple.com/newsroom/a"])
        self.assertEqual(result[1]["enrichment_status"], "budget_excerpt_only")
        self.assertEqual(build.return_value.open.call_count, 1)

    @patch("levyquant.sources.build_opener")
    def test_official_http_links_use_https_and_do_not_change_article_id(self, build):
        build.return_value.open.return_value = Response(url="https://arxiv.org/abs/2611.12345")
        result, _ = enrich_articles([article("http://arxiv.org/abs/2611.12345")])
        self.assertEqual(build.return_value.open.call_args.args[0].full_url, "https://arxiv.org/abs/2611.12345")
        self.assertEqual(result[0]["id"], "stable-id")


if __name__ == "__main__":
    unittest.main()
