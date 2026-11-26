"""Offline public-search fixtures: no real news, provider or article requests."""
from hashlib import sha256
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from levyquant import moomoo


SOURCE = {"id": "moomoo_example", "name": "Example headline search", "queries": ["example research"],
          "section": "company", "url": moomoo.ENDPOINT}


def article(**updates):
    return {"news_id": "provider-id-not-canonical", "news_type": 1,
            "title": "Example <em>Acme</em> &amp; research <script>hidden</script>",
            "publish_time": "1767225600", "url": "https://publisher.example/story?b=2&utm_source=search&a=1#top",
            "img_url": "https://images.example/image.jpg", **updates}


class Response:
    status = 200
    def __init__(self, value=None, *, raw=None, headers=None, url=None, on_exit=None):
        self.raw = json.dumps({"code": 0, "data": [article()]} if value is None else value).encode() if raw is None else raw
        self.stream, self.headers = BytesIO(self.raw), headers or {"Content-Type": "application/json"}
        self.url, self.on_exit, self.reads = url, on_exit, []

    def geturl(self):
        return self.url

    def read(self, size):
        self.reads.append(size)
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()
        if self.on_exit:
            self.on_exit()


class Opener:
    def __init__(self, responses):
        self.responses, self.requests = iter(responses), []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        if response.url is None:
            response.url = request.full_url
        return response


class MoomooTests(unittest.TestCase):
    def fetch(self, responses, source=None, timeout=10):
        opener = Opener(responses)
        with patch.object(moomoo, "build_opener", return_value=opener) as build:
            result = moomoo.fetch_moomoo_source(SOURCE if source is None else source, timeout)
        self.assertIsInstance(build.call_args.args[0], moomoo._NoRedirect)
        return result, opener

    def test_schema_highlights_original_publisher_link_and_no_body_fetch(self):
        result, opener = self.fetch([Response()])
        self.assertEqual(len(result), 1)
        row = result[0]
        canonical = "https://publisher.example/story?a=1&b=2"
        self.assertEqual(row["title"], "Example Acme & research")
        self.assertEqual(row["url"], canonical)
        self.assertEqual(row["canonical_url"], canonical)
        self.assertEqual(row["id"], sha256(canonical.encode()).hexdigest())
        self.assertEqual((row["source_id"], row["source"], row["section"]),
                         (SOURCE["id"], SOURCE["name"], SOURCE["section"]))
        self.assertEqual(row["feed_url"], moomoo.ENDPOINT)
        self.assertEqual((row["summary"], row["body"]), ("", ""))
        self.assertEqual(row["source_text"], row["title"])
        self.assertEqual(row["content_scope"], "search_headline_and_link")
        self.assertEqual(row["media_type"], "headline_only")
        self.assertEqual(row["retrieval"], "feed_excerpt_only")
        self.assertEqual(row["verified_numbers"], [])
        self.assertNotIn("img_url", row)
        self.assertNotIn("news_id", row)
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0][0]
        self.assertEqual(urlsplit(request.full_url).hostname, "ai-news-search.moomoo.com")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query),
            {"keyword": ["example research"], "size": ["5"], "news_type": ["1"], "lang": ["en"], "sort_type": ["2"]})
        self.assertEqual(request.get_header("User-agent"), moomoo.USER_AGENT)
        self.assertNotIn("Authorization", dict(request.header_items()))
        self.assertNotIn("Cookie", dict(request.header_items()))

    def test_tracking_links_dedupe_by_url_not_provider_news_id(self):
        first = article(news_id="one")
        duplicate = article(news_id="two", url="https://publisher.example/story?a=1&b=2&utm_medium=feed")
        other = article(news_id="one", url="https://publisher.example/other")
        result, opener = self.fetch([Response({"code": 0, "data": [first, duplicate]}),
                                    Response({"code": 0, "data": [duplicate, other]})],
                                   {**SOURCE, "queries": ["one", "two"]})
        self.assertEqual(len(result), 2)
        self.assertEqual(len({row["id"] for row in result}), 2)
        self.assertEqual(len(opener.requests), 2)

    def test_moomoo_attribution_query_cleanup_is_limited_to_verified_host_routes(self):
        rows = [article(url="https://www.moomoo.com/news/post/123?futusource=news_search_searchnews&src=39&lang=en"),
                article(url="https://www.moomoo.com/news/post/123?lang=en"),
                article(url="https://www.moomoo.com/community/feed/example?src=39&futusource=news_search_searchnews"),
                article(url="https://www.moomoo.com/community/feed/example"),
                article(url="https://publisher.example/story?futusource=source&src=39&article=1"),
                article(url="https://publisher.example/story?article=1"),
                article(url="https://www.moomoo.com/account?src=39&futusource=keep"),
                article(url="https://www.moomoo.com.other.example/news/post/123?src=39&futusource=keep")]
        result, _ = self.fetch([Response({"code": 0, "data": rows})], {**SOURCE, "search_size": 10})
        urls = {row["url"] for row in result}
        self.assertEqual(len(result), 6)
        self.assertIn("https://www.moomoo.com/news/post/123?lang=en", urls)
        self.assertIn("https://www.moomoo.com/community/feed/example", urls)
        self.assertIn("https://publisher.example/story?article=1&futusource=source&src=39", urls)
        self.assertIn("https://publisher.example/story?article=1", urls)
        self.assertIn("https://www.moomoo.com/account?futusource=keep&src=39", urls)
        self.assertIn("https://www.moomoo.com.other.example/news/post/123?futusource=keep&src=39", urls)
        self.assertTrue(all(row["id"] == sha256(row["url"].encode()).hexdigest() for row in result))

    def test_epochs_and_zoned_dates_are_utc_unknown_and_future_are_not_replaced(self):
        dates = ["1767225600", "1767225600000", "2025-12-31T19:00:00-05:00", 0,
                 "2100-01-01T00:00:00Z", "2026-01-01", "2026-01-01T00:00:00", "3 minutes ago", None, True]
        rows = [article(publish_time=value, url=f"https://publisher.example/{index}") for index, value in enumerate(dates)]
        result, _ = self.fetch([Response({"code": 0, "data": rows})], {**SOURCE, "search_size": 10})
        self.assertEqual([row["published_at"] for row in result[:3]], ["2026-01-01T00:00:00+00:00"] * 3)
        self.assertEqual(result[3]["published_at"], "1970-01-01T00:00:00+00:00")
        self.assertEqual(result[4]["published_at"], "2100-01-01T00:00:00+00:00")
        self.assertTrue(all(row["published_at"] is None and row["date_basis"] is None for row in result[5:]))
        self.assertTrue(all(row["date_timezone_status"] == "unusable" for row in result[5:]))
        self.assertEqual(result[0]["date_raw"], dates[0])
        self.assertEqual(result[0]["date_zone"], "UTC")
        self.assertEqual(result[2]["date_zone"], "-05:00")

    def test_date_variants_survive_for_shared_collector_to_filter(self):
        result, _ = self.fetch([Response({"code": 0, "data": [article(publish_time=None), article()]})])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], result[1]["id"])
        self.assertIsNone(result[0]["published_at"])
        self.assertIsNotNone(result[1]["published_at"])

    def test_iso_unknown_offset_variants_are_unknown_but_rfc_negative_zero_is_utc(self):
        dates = ["2026-11-26T10:00:00-00:00", "2026-11-26 10:00:00-00:00",
                 "2026-11-26T10:00:00-0000", "Thu, 26 Nov 2026 10:00:00 -0000",
                 "2026-11-26T10:00:00+00:00"]
        rows = [article(publish_time=value, url=f"https://publisher.example/date/{index}") for index, value in enumerate(dates)]
        result, _ = self.fetch([Response({"code": 0, "data": rows})])
        self.assertTrue(all(row["published_at"] is None for row in result[:3]))
        self.assertTrue(all(row["date_timezone_status"] == "unusable" for row in result[:3]))
        self.assertEqual(result[3]["published_at"], "2026-11-26T10:00:00+00:00")
        self.assertEqual(result[3]["date_zone"], "-0000")
        self.assertEqual(result[3]["date_timezone_status"], "local_zone_unknown")
        self.assertEqual(result[4]["published_at"], result[3]["published_at"])

    def test_bad_urls_and_empty_titles_are_dropped_without_fetching_links(self):
        bad = [article(url=value) for value in ["javascript:alert(1)", "https://name:password@publisher.example/a",
               "https://publisher.example/a\ninjected", "file:///private/file"]]
        bad.extend([article(title=""), article(title=None), article(title="<script>hidden</script>")])
        result, opener = self.fetch([Response({"code": 0, "data": bad})], {**SOURCE, "search_size": 10})
        self.assertEqual(result, [])
        self.assertEqual(len(opener.requests), 1)

    def test_empty_is_distinct_from_business_errors_and_invalid_schema(self):
        self.assertEqual(self.fetch([Response({"code": 0, "data": []})])[0], [])
        cases = [({"code": 7, "data": [], "message": "sensitive-provider-body"}, "api_error"),
                 ({"code": False, "data": []}, "invalid_response"),
                 ({"code": 0, "data": {}}, "invalid_response"),
                 ({"code": 0, "data": [None]}, "invalid_response"),
                 ({"data": []}, "invalid_response")]
        for value, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(moomoo.MoomooSourceError) as captured:
                    self.fetch([Response(value)])
                self.assertEqual(str(captured.exception), code)
                self.assertNotIn("sensitive", str(captured.exception))
        for raw in [b"not JSON sensitive-provider-body", b'{"code":0,"code":0,"data":[]}', b'{"code":0,"data":NaN}']:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(moomoo.MoomooSourceError, "invalid_response"):
                    self.fetch([Response(raw=raw)])

    def test_http_403_429_network_and_redirect_fail_once_with_safe_codes(self):
        for status in (403, 429):
            body = BytesIO(b"sensitive-provider-body not-a-real-token")
            error = HTTPError("https://private.example/?token=not-a-real-token", status,
                              "sensitive-provider-message", {}, body)
            opener = Opener([error])
            with patch.object(moomoo, "build_opener", return_value=opener):
                with self.assertRaises(moomoo.MoomooSourceError) as captured:
                    moomoo.fetch_moomoo_source({**SOURCE, "queries": ["one", "two"]}, 10)
            self.assertEqual((captured.exception.code, captured.exception.http_status), ("http_error", status))
            self.assertEqual(len(opener.requests), 1)
            self.assertTrue(body.closed)
            self.assertNotIn("sensitive", str(captured.exception))
            self.assertNotIn("token", str(captured.exception))
        with self.assertRaisesRegex(moomoo.MoomooSourceError, "network_error"):
            self.fetch([URLError("sensitive-provider-message")])
        with self.assertRaisesRegex(moomoo.MoomooSourceError, "source_timeout"):
            self.fetch([TimeoutError("sensitive-provider-message")])
        response = Response(url="https://other.example/search")
        with self.assertRaisesRegex(moomoo.MoomooSourceError, "redirect_rejected"):
            self.fetch([response])
        self.assertEqual(response.reads, [])
        self.assertIsNone(moomoo._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_configuration_is_rejected_before_io(self):
        variants = [{"queries": []}, {"queries": ["x"] * 5}, {"queries": [" "]}, {"queries": ["x\ninjected"]},
                    {"search_size": 0}, {"search_size": 11}, {"search_size": True}, {"language": "invalid"},
                    {"url": "https://other.example/search"}, {"max_response_bytes": 0},
                    {"max_response_bytes": moomoo.DEFAULT_MAX_RESPONSE_BYTES + 1}]
        for updates in variants:
            with self.subTest(updates=updates), patch.object(moomoo, "build_opener") as build:
                with self.assertRaisesRegex(moomoo.MoomooSourceError, "invalid_configuration"):
                    moomoo.fetch_moomoo_source({**SOURCE, **updates}, 10)
                build.assert_not_called()
        for timeout in (0, True, float("nan"), float("inf"), 10 ** 400):
            with self.subTest(timeout=timeout), patch.object(moomoo, "build_opener") as build:
                with self.assertRaisesRegex(moomoo.MoomooSourceError, "invalid_configuration"):
                    moomoo.fetch_moomoo_source(SOURCE, timeout)
                build.assert_not_called()

    def test_at_most_four_search_requests_and_ten_entries_per_query(self):
        rows = [article(url=f"https://publisher.example/{index}") for index in range(12)]
        result, opener = self.fetch([Response({"code": 0, "data": rows}) for _ in range(4)],
            {**SOURCE, "queries": ["one", "two", "three", "four"], "search_size": 10})
        self.assertEqual(len(opener.requests), 4)
        self.assertEqual(len(result), 10)
        self.assertTrue(all(parse_qs(urlsplit(request.full_url).query)["size"] == ["10"] for request, _ in opener.requests))

    def test_source_byte_budget_is_shared_and_declared_oversize_is_not_read(self):
        first, second = Response(), Response()
        cap = len(first.raw) + len(second.raw) - 1
        with self.assertRaisesRegex(moomoo.MoomooSourceError, "source_bytes_exceeded"):
            self.fetch([first, second], {**SOURCE, "queries": ["one", "two"], "max_response_bytes": cap})
        self.assertTrue(second.reads)
        declared = Response(headers={"Content-Length": "101"})
        with self.assertRaisesRegex(moomoo.MoomooSourceError, "source_bytes_exceeded"):
            self.fetch([declared], {**SOURCE, "max_response_bytes": 100})
        self.assertEqual(declared.reads, [])
        exact = Response()
        opener = Opener([exact])
        with patch.object(moomoo, "build_opener", return_value=opener):
            with self.assertRaisesRegex(moomoo.MoomooSourceError, "source_bytes_exceeded"):
                moomoo.fetch_moomoo_source({**SOURCE, "queries": ["one", "two"],
                    "max_response_bytes": len(exact.raw)}, 10)
        self.assertEqual(len(opener.requests), 1)

    def test_total_deadline_is_not_reset_between_queries(self):
        clock = [0.0]
        def advance(amount):
            clock[0] += amount
        opener = Opener([Response(on_exit=lambda: advance(6)), Response(on_exit=lambda: advance(5))])
        with patch.object(moomoo, "time") as timer, patch.object(moomoo, "build_opener", return_value=opener):
            timer.monotonic.side_effect = lambda: clock[0]
            with self.assertRaisesRegex(moomoo.MoomooSourceError, "source_timeout"):
                moomoo.fetch_moomoo_source({**SOURCE, "queries": ["one", "two", "three"]}, 10)
        self.assertEqual([timeout for _, timeout in opener.requests], [10, 4])
        self.assertEqual(len(opener.requests), 2)


if __name__ == "__main__":
    unittest.main()
