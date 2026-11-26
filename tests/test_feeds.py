from datetime import datetime, timedelta, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

from levyquant.feeds import MAX_FEED_BYTES, MAX_SOURCE_FEED_BYTES, MIN_SOURCE_FEED_BYTES, collect_sources, parse_feed


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
    def test_supported_empty_rss_atom_and_rdf_remain_valid_empty_feeds(self):
        for data in (rss(""), '<feed xmlns="http://www.w3.org/2005/Atom"/>',
                     '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>'):
            with self.subTest(data=data):
                self.assertEqual(parse_feed(data, SOURCE), [])

    def test_non_feed_xml_and_rss_without_channel_are_rejected(self):
        for data in ('<html><body>Access denied</body></html>', '<rss version="2.0"/>'):
            with self.subTest(data=data):
                with self.assertRaisesRegex(ValueError, "unsupported feed"):
                    parse_feed(data, SOURCE)

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
            "Wed, 25 Nov 2026 10:00:00 UNKNOWN", "2026-02-30T10:00:00Z",
            "Mon, 30 Feb 2026 10:00:00 GMT", "2026-11-25T25:00:00Z",
            "2026-11-25T10:00:00+00:60", "25 Nov 2026 10:00:00 +0060",
            "25 Nov 26 10:00:00 GMT",
        ):
            with self.subTest(date=date):
                article = parse_feed(rss(item(date=date)), SOURCE)[0]
                self.assertIsNone(article["published_at"])

    def test_rfc_negative_zero_is_same_utc_instant_with_unknown_local_zone_provenance(self):
        results = [parse_feed(rss(item(date="Wed, 25 Nov 2026 10:00:00 " + zone)), SOURCE)[0]
                   for zone in ("GMT", "+0000", "-0000")]
        self.assertEqual({article["published_at"] for article in results}, {"2026-11-25T10:00:00+00:00"})
        self.assertEqual(results[2]["date_raw"], "Wed, 25 Nov 2026 10:00:00 -0000")
        self.assertEqual(results[2]["date_zone"], "-0000")
        self.assertEqual(results[2]["date_timezone_status"], "local_zone_unknown")
        self.assertEqual(results[0]["date_timezone_status"], "explicit_timezone")
        self.assertEqual(results[1]["date_zone"], "+0000")

    def test_negative_zero_exception_does_not_accept_unzoned_or_malformed_rfc(self):
        for value in ("2026-11-25T10:00:00", "2026-11-25", "Wed, 25 Nov 2026 10:00:00",
                      "Wed, 25 Nov 2026 10:00:00 -00:00", "Wed 25 Nov 2026 10:00:00 -0000",
                      "Wed, 25 Nov 2026 1:00:00 -0000", "Tue, 25 Nov 2026 10:00:00 -0000",
                      "Wed, 25 Nov 2026 10:00:00 -0060", "Mon, 30 Feb 2026 10:00:00 -0000"):
            with self.subTest(value=value):
                self.assertIsNone(parse_feed(rss(item(date=value)), SOURCE)[0]["published_at"])

    def test_podcast_prefers_episode_page_and_preserves_audio_metadata_and_excerpt_scope(self):
        data = """<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><item>
          <title>Policy conversation</title><link>https://podcast.example/episode</link>
          <guid isPermaLink="false">episode-id</guid><pubDate>Wed, 25 Nov 2026 10:00:00 -0000</pubDate>
          <itunes:summary><![CDATA[<p>Guests discuss monetary policy.</p><script>not evidence</script>]]></itunes:summary>
          <enclosure url="https://audio.example/episode.mp3" type="audio/mpeg"/></item></channel></rss>"""
        article = parse_feed(data, {**SOURCE, "kind": "podcast"})[0]
        self.assertEqual(article["url"], "https://podcast.example/episode")
        self.assertEqual(article["audio_url"], "https://audio.example/episode.mp3")
        self.assertEqual(article["summary"], "Guests discuss monetary policy.")
        self.assertEqual(article["media_type"], "podcast")
        self.assertEqual(article["content_scope"], "podcast_episode_description")
        self.assertEqual(article["retrieval"], "feed_excerpt_only")
        self.assertEqual(article["feed_url"], SOURCE["url"])
        self.assertEqual(article["date_timezone_status"], "local_zone_unknown")

    def test_only_trusted_podcast_can_fall_back_to_audio_enclosure_without_episode_page(self):
        data = rss("""<item><title>Audio episode</title><guid isPermaLink="false">opaque-id</guid>
          <pubDate>Wed, 25 Nov 2026 10:00:00 GMT</pubDate><description>Episode introduction only.</description>
          <enclosure url="https://audio.example/episode.mp3" type="audio/mpeg"/></item>""")
        article = parse_feed(data, {**SOURCE, "kind": "podcast"})[0]
        self.assertEqual(article["url"], article["audio_url"])
        self.assertEqual(article["published_at"], "2026-11-25T10:00:00+00:00")
        self.assertEqual(parse_feed(data, SOURCE), [])

    def test_podcast_rejects_unsafe_or_non_audio_enclosure_fallback(self):
        for enclosure in ('<enclosure url="javascript:alert(1)" type="audio/mpeg"/>',
                          '<enclosure url="https://example.com/video.mp4" type="video/mp4"/>',
                          '<enclosure url="https://user:password@example.com/audio.mp3" type="audio/mpeg"/>'):
            with self.subTest(enclosure=enclosure):
                data = rss('<item><title>Episode</title><guid isPermaLink="false">opaque</guid>' + enclosure + '</item>')
                self.assertEqual(parse_feed(data, {**SOURCE, "kind": "podcast"}), [])

    def test_atom_podcast_enclosure_fallback_and_html_alternate_priority(self):
        data = """<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://podcast.example/">
          <entry><title>Episode</title><link rel="enclosure" href="audio/1.mp3" type="audio/mpeg"/>
          <updated>2026-11-25T10:00:00Z</updated><summary>Show notes only.</summary>{alternate}</entry></feed>"""
        source = {**SOURCE, "kind": "podcast"}
        audio = parse_feed(data.format(alternate=""), source)[0]
        page = parse_feed(data.format(alternate='<link rel="alternate" href="episode/1" type="text/html"/>'), source)[0]
        self.assertEqual(audio["url"], "https://podcast.example/audio/1.mp3")
        self.assertEqual(page["url"], "https://podcast.example/episode/1")
        self.assertEqual(page["audio_url"], audio["url"])
        self.assertEqual(page["date_basis"], "updated")
        self.assertEqual(page["date_raw"], "2026-11-25T10:00:00Z")

    def test_empty_summary_uses_description_and_declared_media_retrieval_is_retained(self):
        data = rss("""<item><title>Media story</title><link>https://example.com/story</link>
          <summary> </summary><description><![CDATA[<p>Publisher-provided excerpt.</p>]]></description>
          <enclosure url="https://audio.example/episode.mp3" type="audio/mpeg"/></item>""")
        article = parse_feed(data, {**SOURCE, "retrieval": "feed_excerpt_only"})[0]
        self.assertEqual(article["summary"], "Publisher-provided excerpt.")
        self.assertEqual(article["retrieval"], "feed_excerpt_only")
        self.assertEqual(article["content_scope"], "rss_metadata_and_feed_excerpt")
        self.assertNotIn("audio_url", article)

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

    @patch("levyquant.feeds.urlopen")
    def test_large_valid_feed_requires_explicit_bounded_per_source_limit(self, open_url):
        content = rss(item()).encode() + b" " * (4 * 1024 * 1024)
        for cap, expected in ((MAX_FEED_BYTES, 0), (MAX_SOURCE_FEED_BYTES, 1)):
            with self.subTest(cap=cap):
                open_url.return_value = Response(content, length=len(content))
                articles, warnings = self.collect([{**SOURCE, "max_feed_bytes": cap}])
                self.assertEqual(len(articles), expected)
                if expected:
                    self.assertEqual(warnings, [])
                else:
                    self.assertTrue(any("byte limit" in warning for warning in warnings))

    @patch("levyquant.feeds.urlopen")
    def test_custom_feed_limit_bounds_declared_and_accumulated_bytes(self, open_url):
        cap = MIN_SOURCE_FEED_BYTES
        for response in (Response(b"", length=cap + 1), Response(b"x" * (cap + 1))):
            with self.subTest(declared=bool(response.headers)):
                open_url.return_value = response
                articles, warnings = self.collect([{**SOURCE, "max_feed_bytes": cap}])
                self.assertEqual(articles, [])
                self.assertTrue(any("byte limit" in warning for warning in warnings))

    @patch("levyquant.feeds.urlopen")
    def test_invalid_feed_caps_are_rejected_before_network(self, open_url):
        for cap in (True, False, "8388608", 8388608.0, 0, -1, MIN_SOURCE_FEED_BYTES - 1, MAX_SOURCE_FEED_BYTES + 1):
            with self.subTest(cap=cap):
                diagnostics = []
                articles, warnings = self.collect([{**SOURCE, "max_feed_bytes": cap}], diagnostics=diagnostics)
                self.assertEqual(articles, [])
                self.assertEqual(diagnostics[0]["status"], "invalid_configuration")
                self.assertTrue(any("max_feed_bytes" in warning for warning in warnings))
        open_url.assert_not_called()

    @patch("levyquant.feeds.urlopen")
    def test_diagnostics_distinguish_old_failed_disabled_empty_and_unusable_dates(self, open_url):
        sources = [{**SOURCE, "id": name, "name": name, "url": f"https://example.com/{name}",
                    "enabled": name != "disabled"} for name in ("ok", "old", "broken", "disabled", "empty", "undated")]
        contents = {
            "ok": rss(item("A", "https://example.com/a") + item("duplicate", "https://example.com/a?utm_source=rss")
                      + item("old", "https://example.com/old", "Tue, 24 Nov 2026 10:00:00 GMT")
                      + item("unknown", "https://example.com/unknown", "")),
            "old": rss(item(date="Tue, 24 Nov 2026 10:00:00 GMT")),
            "broken": "<rss><channel>", "empty": rss(""), "undated": rss(item(date="")),
        }
        open_url.side_effect = lambda request, **kwargs: Response(contents[request.full_url.rsplit("/", 1)[-1]])
        diagnostics = []
        articles, warnings = self.collect(sources, diagnostics=diagnostics)
        self.assertEqual([report["id"] for report in diagnostics], [source["id"] for source in sources])
        reports = {report["id"]: report for report in diagnostics}
        self.assertEqual({key: report["status"] for key, report in reports.items()}, {
            "ok": "ok", "old": "no_new_items", "broken": "failed", "disabled": "disabled",
            "empty": "empty_feed", "undated": "unusable_dates"})
        self.assertEqual({key: reports["ok"][key] for key in ("parsed", "dated", "eligible", "selected")},
                         {"parsed": 4, "dated": 3, "eligible": 2, "selected": 1})
        self.assertEqual(reports["ok"]["latest_published"], "2026-11-25T10:00:00+00:00")
        self.assertEqual(reports["disabled"]["selected"], 0)
        self.assertEqual(len(articles), 1)
        self.assertFalse(any(warning.startswith("old:") for warning in warnings))
        self.assertTrue(any(warning.startswith("undated:") and "unknown publication" in warning for warning in warnings))
        self.assertEqual(open_url.call_count, 5)

    @patch("levyquant.feeds.urlopen")
    def test_diagnostics_include_all_disabled_sources_without_network(self, open_url):
        diagnostics = []
        articles, warnings = self.collect([{**SOURCE, "enabled": False}], diagnostics=diagnostics)
        self.assertEqual(articles, [])
        self.assertEqual(diagnostics[0]["status"], "disabled")
        self.assertFalse(diagnostics[0]["enabled"])
        self.assertTrue(warnings)
        open_url.assert_not_called()

    @patch("levyquant.feeds.urlopen")
    def test_http_200_well_formed_html_is_failed_not_successful_empty_feed(self, open_url):
        open_url.return_value = Response('<html><body><h1>Access denied</h1></body></html>')
        diagnostics = []
        articles, warnings = self.collect(diagnostics=diagnostics)
        self.assertEqual(articles, [])
        self.assertEqual(diagnostics[0]["status"], "failed")
        self.assertEqual(diagnostics[0]["parsed"], 0)
        self.assertTrue(any("unsupported feed" in warning for warning in warnings))

    @patch("levyquant.feeds.urlopen")
    def test_rfc_negative_zero_respects_window_and_future_exclusion(self, open_url):
        open_url.return_value = Response(rss(item("current", "https://example.com/current", "Wed, 25 Nov 2026 10:00:00 -0000")
                                           + item("future", "https://example.com/future", "Wed, 25 Nov 2026 12:00:01 -0000")))
        diagnostics = []
        articles, warnings = self.collect(diagnostics=diagnostics)
        self.assertEqual([article["title"] for article in articles], ["current"])
        self.assertEqual(diagnostics[0]["dated"], 2)
        self.assertEqual(diagnostics[0]["future_dated"], 1)
        self.assertTrue(any("future" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
