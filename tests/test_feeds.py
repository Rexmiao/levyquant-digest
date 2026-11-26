from datetime import datetime, timedelta, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

from levyquant.feeds import MAX_FEED_BYTES, collect_sources, parse_feed


SOURCE = {"id": "sample", "name": "Sample", "url": "https://example.com/feed.xml", "section": "macro"}


class Response(BytesIO):
    def __init__(self, content, *, url="https://example.com/feed.xml", length=None):
        super().__init__(content.encode() if isinstance(content, str) else content)
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self.url = url

    def geturl(self):
        return self.url


def rss(items, channel_extra=""):
    return f"<rss version='2.0'><channel>{channel_extra}{items}</channel></rss>"


def item(title="News", url="https://example.com/news", date="Wed, 25 Nov 2026 10:00:00 GMT"):
    date_tag = f"<pubDate>{date}</pubDate>" if date else ""
    return f"<item><title>{title}</title><link>{url}</link>{date_tag}</item>"


class ParseFeedTests(unittest.TestCase):
    def test_rss_cleans_tracking_preserves_functional_query_and_plain_text(self):
        data = rss("""<item><title>Data &amp; policy</title>
            <link>https://EXAMPLE.com:443/news?id=7&amp;utm_source=mail&amp;fbclid=x#top</link>
            <description>&lt;p&gt;First &amp;amp; second.&lt;/p&gt;&lt;p&gt;Next.&lt;/p&gt;&lt;script&gt;hidden&lt;/script&gt;</description>
            <pubDate>Wed, 25 Nov 2026 05:00:00 -0500</pubDate></item>""")
        article = parse_feed(data, SOURCE)[0]
        self.assertEqual(article["url"], "https://example.com/news?id=7")
        self.assertEqual(article["summary"], "First & second. Next.")
        self.assertEqual(article["published_at"], "2026-11-25T10:00:00+00:00")
        self.assertEqual(article["section"], "macro")
        self.assertEqual(article["source"], "Sample")
        same_article = parse_feed(rss(item(url="https://example.com/news?id=7")), SOURCE)[0]
        self.assertEqual(article["id"], same_article["id"])

    def test_atom_prefers_alternate_and_published_over_updated(self):
        data = """<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://example.com/">
          <updated>2026-11-25T11:00:00Z</updated>
          <entry><title>Research</title><link rel="self" href="api/1"/>
            <link rel="alternate" href="papers/1?utm_medium=rss"/>
            <published>2026-11-24T12:30:00+02:00</published><updated>2026-11-25T10:00:00Z</updated>
            <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>One.</p><p>Two.</p></div></content>
          </entry>
          <entry><title>Updated only</title><link href="papers/2"/><updated>2026-11-25T09:00:00Z</updated></entry>
          <entry><title>Undated</title><link href="papers/3"/></entry>
        </feed>"""
        articles = parse_feed(data, SOURCE)
        self.assertEqual(articles[0]["url"], "https://example.com/papers/1")
        self.assertEqual(articles[0]["published_at"], "2026-11-24T10:30:00+00:00")
        self.assertEqual(articles[0]["summary"], "One. Two.")
        self.assertEqual(articles[0]["date_basis"], "published")
        self.assertEqual(articles[1]["date_basis"], "updated")
        self.assertIsNone(articles[2]["published_at"])

    def test_rdf_dublin_core_date_and_default_section(self):
        data = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
          <channel rdf:about="https://example.com/feed"/>
          <item rdf:about="https://example.com/a"><title>RDF item</title><link>https://example.com/a</link>
          <dc:date>2026-11-25T10:15:00.123Z</dc:date></item></rdf:RDF>"""
        article = parse_feed(data.encode(), {"name": "RDF"})[0]
        self.assertEqual(article["published_at"], "2026-11-25T10:15:00.123000+00:00")
        self.assertEqual(article["section"], "company")

    def test_channel_dates_never_substitute_for_an_undated_article(self):
        undated = item(date="")
        explicit = rss(undated, "<pubDate>Wed, 25 Nov 2026 10:00:00 GMT</pubDate>")
        article = parse_feed(explicit, SOURCE)[0]
        self.assertIsNone(article["date_basis"])
        self.assertIsNone(article["published_at"])
        built = rss(undated, "<lastBuildDate>Wed, 25 Nov 2026 10:00:00 GMT</lastBuildDate>")
        self.assertIsNone(parse_feed(built, SOURCE)[0]["published_at"])

    def test_unzoned_date_only_unknown_zone_and_invalid_calendar_dates_are_unknown(self):
        for date in (
            "2026-11-25", "2026-11-25T10:00:00", "Wed, 25 Nov 2026 10:00:00",
            "Wed, 25 Nov 2026 10:00:00 -0000", "2026-02-30T10:00:00Z",
            "Mon, 30 Feb 2026 10:00:00 GMT", "2026-11-25T25:00:00Z",
            "2026-11-25T10:00:00+00:60", "25 Nov 2026 10:00:00 +0060",
            "25 Nov 26 10:00:00 GMT",
        ):
            with self.subTest(date=date):
                article = parse_feed(rss(item(date=date)), SOURCE)[0]
                self.assertIsNone(article["published_at"])

    def test_offsets_and_dst_repeated_hour_preserve_real_instants(self):
        first = parse_feed(rss(item(date="2026-11-01T01:30:00-04:00")), SOURCE)[0]
        second = parse_feed(rss(item(date="2026-11-01T01:30:00-05:00")), SOURCE)[0]
        self.assertEqual(first["published_at"], "2026-11-01T05:30:00+00:00")
        self.assertEqual(second["published_at"], "2026-11-01T06:30:00+00:00")
        self.assertEqual(first["id"], second["id"])

    def test_source_identity_and_section_are_explicit_but_not_part_of_article_id(self):
        article = parse_feed(rss(item()), SOURCE)[0]
        other = parse_feed(rss(item()), {**SOURCE, "id": "renamed", "section": "company"})[0]
        self.assertEqual(article["source_id"], "sample")
        self.assertEqual(article["canonical_url"], article["url"])
        self.assertEqual(article["feed_url"], SOURCE["url"])
        self.assertEqual(article["id"], other["id"])
        self.assertEqual(other["section"], "company")

    def test_invalid_primary_date_can_fall_back_to_atom_updated(self):
        data = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Valid update</title>
          <link href="https://example.com/a"/><published>not a date</published>
          <updated>2026-11-25T10:00:00Z</updated></entry></feed>"""
        self.assertEqual(parse_feed(data, SOURCE)[0]["date_basis"], "updated")

    def test_invalid_or_missing_article_links_are_not_emitted(self):
        data = rss(item(url="javascript:alert(1)") + item(title="No URL", url=""))
        self.assertEqual(parse_feed(data, SOURCE), [])


class CollectFeedTests(unittest.TestCase):
    def setUp(self):
        self.since = datetime(2026, 11, 25, 0, tzinfo=timezone.utc)
        self.until = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)

    def collect(self, sources=None, **kwargs):
        return collect_sources(sources or [SOURCE], since=self.since, until=self.until, **kwargs)

    @patch("levyquant.feeds.urlopen")
    def test_excludes_old_future_and_unknown_dates(self, open_url):
        data = rss(
            item("Current", "https://example.com/current")
            + item("Old", "https://example.com/old", "Tue, 24 Nov 2026 23:59:59 GMT")
            + item("Future", "https://example.com/future", "Wed, 25 Nov 2026 12:00:01 GMT")
            + item("Unknown", "https://example.com/unknown", "")
        )
        open_url.return_value = Response(data)
        articles, warnings = self.collect()
        self.assertEqual([article["title"] for article in articles], ["Current"])
        self.assertTrue(any("unknown publication" in warning for warning in warnings))
        self.assertTrue(any("future" in warning for warning in warnings))
        self.assertEqual(open_url.call_args.kwargs["timeout"], 20)

    @patch("levyquant.feeds.urlopen")
    def test_deduplicates_tracking_variants_within_and_across_sources(self, open_url):
        data = rss(item(url="https://example.com/a?utm_source=first")
                   + item(url="https://example.com/a?fbclid=second"))
        open_url.side_effect = lambda *args, **kwargs: Response(data)
        sources = [SOURCE, {**SOURCE, "id": "second", "name": "Second"}]
        articles, warnings = self.collect(sources)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "Sample")
        self.assertEqual(warnings, [])
        self.assertEqual(open_url.call_count, 2)

    @patch("levyquant.feeds.urlopen")
    def test_partial_failure_keeps_successful_sources(self, open_url):
        def respond(request, **kwargs):
            if "broken" in request.full_url:
                return Response("<rss><channel>")
            return Response(rss(item()))
        open_url.side_effect = respond
        articles, warnings = self.collect([SOURCE, {**SOURCE, "name": "Broken", "url": "https://broken.example/feed"}])
        self.assertEqual(len(articles), 1)
        self.assertTrue(any("Broken" in warning and "ParseError" in warning for warning in warnings))

    @patch("levyquant.feeds.urlopen")
    def test_empty_feed_warns_and_disabled_source_is_not_requested(self, open_url):
        open_url.return_value = Response(rss(""))
        articles, warnings = self.collect([SOURCE, {**SOURCE, "enabled": False}])
        self.assertEqual(articles, [])
        self.assertTrue(any("no usable entries" in warning for warning in warnings))
        self.assertEqual(open_url.call_count, 1)

    @patch("levyquant.feeds.urlopen")
    def test_feed_size_limit_rejects_declared_and_undeclared_large_bodies(self, open_url):
        for response in (
            Response(b"", length=MAX_FEED_BYTES + 1),
            Response(b"x" * (MAX_FEED_BYTES + 1)),
        ):
            with self.subTest(declared=bool(response.headers)):
                open_url.return_value = response
                articles, warnings = self.collect()
                self.assertEqual(articles, [])
                self.assertTrue(any("byte limit" in warning for warning in warnings))

    @patch("levyquant.feeds.urlopen")
    def test_invalid_source_url_warns_without_network_access(self, open_url):
        articles, warnings = self.collect([{**SOURCE, "url": "file:///etc/passwd"}])
        self.assertEqual(articles, [])
        self.assertTrue(any("invalid HTTP(S)" in warning for warning in warnings))
        open_url.assert_not_called()

    @patch("levyquant.feeds.urlopen")
    def test_limit_is_applied_after_filtering_and_duplicate_removal(self, open_url):
        open_url.return_value = Response(rss(
            item("A", "https://example.com/a") + item("A duplicate", "https://example.com/a?utm_source=rss")
            + item("B", "https://example.com/b", "Wed, 25 Nov 2026 09:00:00 GMT")
            + item("C", "https://example.com/c", "Wed, 25 Nov 2026 08:00:00 GMT")
        ))
        articles, _ = self.collect(max_per_source=2)
        self.assertEqual({article["url"] for article in articles}, {"https://example.com/a", "https://example.com/b"})

    @patch("levyquant.feeds.urlopen")
    def test_per_source_limit_is_respected(self, open_url):
        open_url.return_value = Response(rss(item("A", "https://example.com/a") + item("B", "https://example.com/b")))
        articles, _ = self.collect([{**SOURCE, "max_items_per_run": 1}])
        self.assertEqual(len(articles), 1)

    @patch("levyquant.feeds.urlopen")
    def test_exact_window_edges_offsets_and_microseconds(self, open_url):
        data = rss(
            item("At start", "https://example.com/start", "2026-11-24T19:00:00-05:00")
            + item("Before", "https://example.com/before", "2026-11-24T23:59:59.999999Z")
            + item("At end", "https://example.com/end", "2026-11-25T07:00:00-05:00")
            + item("After", "https://example.com/after", "2026-11-25T12:00:00.000001Z")
        )
        open_url.return_value = Response(data)
        articles, _ = self.collect()
        self.assertEqual({article["title"] for article in articles}, {"At start", "At end"})

    @patch("levyquant.feeds.urlopen")
    def test_real_future_is_excluded_even_when_requested_cutoff_is_future(self, open_url):
        now = datetime.now(timezone.utc)
        open_url.return_value = Response(rss(item(date=(now + timedelta(days=1)).isoformat())))
        articles, warnings = collect_sources([SOURCE], since=now-timedelta(days=1), until=now+timedelta(days=2))
        self.assertEqual(articles, [])
        self.assertTrue(any("future" in warning for warning in warnings))

    def test_naive_window_is_rejected_instead_of_guessing_a_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            collect_sources([SOURCE], since=datetime(2026, 11, 25), until=self.until)


if __name__ == "__main__":
    unittest.main()
