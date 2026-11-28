"""Meaningful rendering/security checks using only the standard library."""

import copy
from html.parser import HTMLParser
import unittest

from levyquant.render import RECIPIENT_FOOTER_SLOT, render_bilingual_digest, render_digest


class ParsedHTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.tags = []
        self.attributes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)
        if tag == "a":
            self.links.append(dict(attrs).get("href"))


class RenderDigestTests(unittest.TestCase):
    def setUp(self):
        self.digest = {
            "title": "LévyQuant Daily",
            "edition": "Morning Edition",
            "date": "2026-11-25",
            "cutoff": "2026-11-25T07:00:00-05:00",
            "language": "zh-CN",
            "mode": "live",
            "coverage_warnings": [],
            "sections": [{
                "id": "macro",
                "title": "MACRO CALENDAR / 宏观日历",
                "items": [{
                    "title": "Example research update",
                    "summary": "A summary drawn from supplied material.",
                    "analysis": "A possible implication that needs verification.",
                    "source_ids": ["a1"],
                }],
            }],
        }
        self.articles = [{
            "id": "a1",
            "source": "Example source",
            "title": "Original article",
            "url": "https://example.org/article?one=1&two=2",
            "summary": "Original material",
            "published_at": "2026-11-25T06:20:00-05:00",
            "section": "macro",
        }]

    def test_html_escapes_all_model_and_source_markup(self):
        payload = '<script>alert("unsafe")</script><img src=x onerror=alert(1)>'
        self.digest.update(title=payload, edition=payload, date=payload, cutoff=payload)
        self.digest["coverage_warnings"] = [payload]
        self.digest["sections"][0]["title"] = payload
        self.digest["sections"][0]["items"][0].update(
            title=payload, summary=payload, analysis=payload,
            url="https://model-invented.example/never-link-this",
        )
        self.articles[0].update(source=payload, published_at=payload)
        html, text = render_digest(self.digest, self.articles)
        parsed = ParsedHTML(html)
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("img", parsed.tags)
        self.assertFalse(any(name.lower().startswith("on") for name, _ in parsed.attributes))
        self.assertIn("&lt;script&gt;", html)
        self.assertEqual(parsed.links, [self.articles[0]["url"]])
        self.assertNotIn("model-invented.example", html)
        # Plain text is not HTML and should preserve readable source wording.
        self.assertIn(payload, text)

    def test_only_referenced_article_links_are_used_and_duplicates_merge(self):
        self.articles.append(dict(self.articles[0], id="a2", url="https://unused.example/"))
        self.digest["sections"][0]["items"][0]["source_ids"] = ["a1", "a1", "unknown"]
        html, text = render_digest(self.digest, self.articles)
        self.assertEqual(ParsedHTML(html).links, [self.articles[0]["url"]])
        self.assertNotIn("unused.example", html)
        self.assertNotIn("unused.example", text)
        self.assertIn("引用原文: 1", text)
        self.assertIn("one=1&amp;two=2", html)

    def test_rejects_unsafe_or_malformed_urls_in_both_alternatives(self):
        unsafe_urls = [
            "javascript:alert(1)", "JaVaScRiPt:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd", "ftp://example.org/article", "//example.org/article",
            "https://", "https://example.org/a\nb", "https://example.org/a\tb",
            "https://user:password@example.org/article", "https://example.org\\@evil.example/",
            'https://example.org/\"onclick=alert(1)',
            "https://example.org:bad/article", "https://example.org:999999/article",
            "https://[invalid/article",
        ]
        for unsafe_url in unsafe_urls:
            with self.subTest(url=unsafe_url):
                articles = [dict(self.articles[0], url=unsafe_url)]
                html, text = render_digest(self.digest, articles)
                self.assertEqual(ParsedHTML(html).links, [])
                self.assertNotIn(unsafe_url, text)
                self.assertIn("来源链接缺失或待核实", text)
                self.assertIn("引用原文: 0", text)

    def test_unknown_source_never_becomes_a_link(self):
        self.digest["sections"][0]["items"][0]["source_ids"] = ["https://unknown.example/", "missing"]
        html, text = render_digest(self.digest, self.articles)
        self.assertEqual(ParsedHTML(html).links, [])
        self.assertIn("来源链接缺失或待核实", text)

    def test_demo_and_coverage_warning_are_visible_in_each_language(self):
        for language, demo, analysis, coverage in [
            ("zh-CN", "演示模板 / 非实时新闻 / 禁止发送", "编辑分析", "资料覆盖提醒"),
            ("en", "DEMO TEMPLATE / NOT LIVE NEWS / DO NOT SEND", "Editorial analysis", "Coverage notice"),
        ]:
            with self.subTest(language=language):
                digest = copy.deepcopy(self.digest)
                digest.update(language=language, mode="demo", coverage_warnings=["A source could not be fetched."])
                html, text = render_digest(digest, self.articles)
                for expected in [demo, analysis, coverage, "A source could not be fetched."]:
                    self.assertIn(expected, html)
                    self.assertIn(expected, text)
                self.assertLess(html.index(demo), html.index("MACRO CALENDAR"))
                self.assertIn(f'lang="{language}"', html)

    def test_long_digest_is_not_truncated_and_source_count_is_dynamic(self):
        items = []
        articles = []
        for index in range(32):
            items.append({"title": f"Item {index}", "summary": f"Summary {index}", "source_ids": [f"a{index}"]})
            articles.append(dict(self.articles[0], id=f"a{index}", url=f"https://example.org/article/{index}"))
        self.digest["sections"][0]["items"] = items
        self.digest["sections"].append({"id": "empty", "title": "EMPTY SECTION SHOULD BE OMITTED", "items": []})
        html, text = render_digest(self.digest, articles)
        self.assertEqual(len(ParsedHTML(html).links), 32)
        self.assertIn("Item 31", html)
        self.assertIn("Summary 31", text)
        self.assertIn("引用原文: 32", text)
        self.assertNotIn("EMPTY SECTION SHOULD BE OMITTED", html)
        self.assertNotIn("EMPTY SECTION SHOULD BE OMITTED", text)
        self.assertIn("max-width:760px", html)

    def test_actual_source_time_is_preserved_without_invented_edition(self):
        self.digest.update(language="en", edition="")
        html, text = render_digest(self.digest, self.articles)
        for output in (html, text):
            self.assertIn("2026-11-25 06:20 EST", output)
        self.assertIn(self.articles[0]["source"], text)
        self.assertIn("Editorial analysis:", text)
        self.assertNotIn("Morning Edition", text)
        self.assertNotIn("DO NOT SEND", text)
        self.assertNotIn("agent-s", text)

    def test_cutoff_and_source_times_use_new_york_date_and_dst_in_both_formats(self):
        for cutoff, published, expected_cutoff, expected_published in (
            ("2026-11-26T11:12:14.285001+00:00", "2026-11-26T01:00:00Z", "2026-11-26 06:12 EST", "2026-11-25 20:00 EST"),
            ("2026-07-10T11:00:00Z", "2026-07-10T08:20:00+02:00", "2026-07-10 07:00 EDT", "2026-07-10 02:20 EDT"),
            ("2026-11-01T06:30:00Z", "2026-11-01T05:30:00Z", "2026-11-01 01:30 EST", "2026-11-01 01:30 EDT"),
        ):
            with self.subTest(cutoff=cutoff, published=published):
                self.digest.update(language="en", cutoff=cutoff)
                self.articles[0]["published_at"] = published
                for output in render_digest(self.digest, self.articles):
                    self.assertIn("Information cutoff: " + expected_cutoff, output)
                    self.assertIn(expected_published, output)
                    self.assertNotIn(cutoff, output)
                    self.assertNotIn(published, output)

    def test_unqualified_times_are_not_given_a_new_york_offset(self):
        for value in ("2026-11-26", "2026-11-26T07:00:00", "2026-11-26T07:00:00-00:00"):
            with self.subTest(value=value):
                self.digest["cutoff"] = value
                self.articles[0]["published_at"] = value
                for output in render_digest(self.digest, self.articles):
                    self.assertIn("资料截止: " + value, output)
                    self.assertEqual(output.count(value), 2)
                    self.assertNotIn("EST", output)
                    self.assertNotIn("EDT", output)

    def test_unconfigured_mode_is_marked_as_not_sendable(self):
        self.digest.pop("mode")
        self.digest["sections"] = []
        html, text = render_digest(self.digest, self.articles)
        self.assertIn("运行模式未确认 / 禁止发送", html)
        self.assertIn("本期没有可展示的内容", text)

    def test_new_brand_and_optional_personalization_slot_are_only_in_the_footer(self):
        self.digest.update(language="en", footer_personalization=True)
        html, text = render_digest(self.digest, self.articles)
        brand = "LévyQuant · Macro, U.S. equities and quantitative research · Source articles: 1"
        self.assertIn(brand, text)
        self.assertEqual(html.count(RECIPIENT_FOOTER_SLOT), 1)
        footer_start = html.index('data-digest-block="footer"')
        self.assertLess(footer_start, html.index(RECIPIENT_FOOTER_SLOT))
        self.assertLess(html.index(RECIPIENT_FOOTER_SLOT), html.index("</td>", footer_start))
        self.assertNotIn(RECIPIENT_FOOTER_SLOT, text)
        self.assertNotIn("This briefing is sent", html + text)
        self.digest["footer_personalization"] = False
        self.assertNotIn(RECIPIENT_FOOTER_SLOT, render_digest(self.digest, self.articles)[0])

    def bilingual_pair(self):
        english = copy.deepcopy(self.digest)
        english.update(language="en", title="LévyQuant Morning Briefing", footer_personalization=True,
                       cutoff="2026-11-25T12:00:00Z", coverage_warnings=["English coverage limitation."])
        english["sections"][0]["title"] = "MACRO CALENDAR"
        english["sections"].append({"id": "quant_research", "title": "QUANT RESEARCH", "items": [{
            "title": "English research item", "summary": "English research summary.",
            "analysis": "English research analysis.", "source_ids": ["a2"],
        }]})
        chinese = copy.deepcopy(english)
        chinese.update(language="zh-CN", title="LévyQuant 晨间简报", edition="晨间版",
                       coverage_warnings=["中文资料覆盖说明。"])
        chinese["sections"][0]["title"] = "宏观日历"
        chinese["sections"][0]["items"][0].update(title="中文宏观条目", summary="中文宏观摘要。", analysis="中文宏观分析。")
        chinese["sections"][1]["title"] = "量化研究"
        chinese["sections"][1]["items"][0].update(title="中文研究条目", summary="中文研究摘要。", analysis="中文研究分析。")
        articles = [*self.articles, dict(self.articles[0], id="a2", url="https://example.org/research")]
        return english, chinese, articles

    def test_bilingual_complete_copies_are_ordered_with_matching_citations_and_one_footer(self):
        english, chinese, articles = self.bilingual_pair()
        original = copy.deepcopy((english, chinese, articles))
        html, text = render_bilingual_digest(english, chinese, articles)
        parsed = ParsedHTML(html)
        self.assertEqual((english, chinese, articles), original)
        self.assertEqual(parsed.tags.count("html"), 1)
        self.assertEqual(parsed.tags.count("head"), 1)
        self.assertEqual(parsed.tags.count("body"), 1)
        self.assertEqual(parsed.links, [article["url"] for article in articles] * 2)
        self.assertIn(('data-digest-language', 'en'), parsed.attributes)
        self.assertIn(('data-digest-language', 'zh-CN'), parsed.attributes)
        self.assertIn('lang="zh-CN" data-digest-language="zh-CN"', html)
        for output in (html, text):
            self.assertLess(output.index("English edition"), output.index("English research summary."))
            self.assertLess(output.index("English coverage limitation."), output.index("简体中文版"))
            self.assertLess(output.index("简体中文版"), output.index("中文宏观摘要。"))
            self.assertLess(output.index("中文宏观摘要。"), output.index("中文研究摘要。"))
            self.assertLess(output.index("中文研究摘要。"), output.index("中文资料覆盖说明。"))
            self.assertIn("Information cutoff: 2026-11-25 07:00 EST", output)
            self.assertIn("资料截止: 2026-11-25 07:00 EST", output)
            self.assertIn("Editorial analysis:", output)
            self.assertIn("编辑分析:", output)
            self.assertEqual(output.count("LévyQuant · Macro, U.S. equities and quantitative research"), 1)
            self.assertIn("Source articles: 2", output)
            self.assertNotIn("Source articles: 4", output)
        self.assertEqual(html.count('data-digest-block="footer"'), 1)
        self.assertEqual(html.count(RECIPIENT_FOOTER_SLOT), 1)
        self.assertLess(html.index("中文资料覆盖说明。"), html.index(RECIPIENT_FOOTER_SLOT))
        self.assertNotIn(RECIPIENT_FOOTER_SLOT, text)
        self.assertNotIn("This briefing is sent", html + text)

    def test_bilingual_escapes_both_languages_and_never_uses_model_urls(self):
        english, chinese, articles = self.bilingual_pair()
        payload = '<script>alert("unsafe")</script><img src=x onerror=alert(1)>'
        english.update(title=payload, coverage_warnings=[payload])
        chinese.update(title=payload, coverage_warnings=[payload])
        for digest in (english, chinese):
            digest["sections"][0]["title"] = payload
            digest["sections"][0]["items"][0].update(title=payload, summary=payload + RECIPIENT_FOOTER_SLOT,
                analysis=payload, url="https://model-invented.example/never-link")
        articles[0].update(source=payload, published_at=payload, url="javascript:alert(1)")
        articles.append(dict(articles[1], id="unused", url="https://unused.example/"))
        html, text = render_bilingual_digest(english, chinese, articles)
        parsed = ParsedHTML(html)
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("img", parsed.tags)
        self.assertFalse(any(name.lower().startswith("on") for name, _ in parsed.attributes))
        self.assertEqual(parsed.links, [articles[1]["url"]] * 2)
        self.assertNotIn("model-invented.example", html + text)
        self.assertNotIn("unused.example", html + text)
        self.assertNotIn("javascript:", html + text)
        self.assertEqual(html.count(RECIPIENT_FOOTER_SLOT), 1)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn(payload, text)
        self.assertIn("Source link missing or unverified", text)
        self.assertIn("来源链接缺失或待核实", text)

    def test_bilingual_rejects_mismatched_edition_or_reference_structure(self):
        for change in ("date", "cutoff", "mode", "source_ids", "section_order", "missing_item"):
            with self.subTest(change=change):
                english, chinese, articles = self.bilingual_pair()
                if change in ("date", "cutoff", "mode"):
                    chinese[change] = "mismatch"
                elif change == "source_ids":
                    chinese["sections"][0]["items"][0]["source_ids"] = ["a2"]
                elif change == "section_order":
                    chinese["sections"].reverse()
                else:
                    chinese["sections"][1]["items"] = []
                with self.assertRaisesRegex(ValueError, "share edition metadata and ordered source references"):
                    render_bilingual_digest(english, chinese, articles)

    def test_bilingual_demo_is_visible_in_both_copies_without_duplicate_recipient_slots(self):
        english, chinese, articles = self.bilingual_pair()
        english.update(mode="demo", cutoff="pending", date="YYYY-MM-DD", footer_personalization=False)
        chinese.update(mode="demo", cutoff="pending", date="YYYY-MM-DD", footer_personalization=False)
        for output in render_bilingual_digest(english, chinese, articles):
            self.assertIn("DEMO TEMPLATE / NOT LIVE NEWS / DO NOT SEND", output)
            self.assertIn("演示模板 / 非实时新闻 / 禁止发送", output)
            self.assertIn("Information cutoff: pending", output)
            self.assertIn("资料截止: pending", output)
            self.assertNotIn(RECIPIENT_FOOTER_SLOT, output)

    def test_bilingual_long_edition_keeps_last_item_of_each_complete_copy(self):
        english, chinese, articles = self.bilingual_pair()
        english["sections"] = [{"id": "quant_research", "title": "QUANT RESEARCH", "items": []}]
        chinese["sections"] = [{"id": "quant_research", "title": "量化研究", "items": []}]
        articles = []
        for index in range(32):
            articles.append(dict(self.articles[0], id=f"a{index}", url=f"https://example.org/article/{index}"))
            english["sections"][0]["items"].append({"title": f"English item {index}", "summary": f"English summary {index}", "source_ids": [f"a{index}"]})
            chinese["sections"][0]["items"].append({"title": f"中文条目 {index}", "summary": f"中文摘要 {index}", "source_ids": [f"a{index}"]})
        html, text = render_bilingual_digest(english, chinese, articles)
        self.assertEqual(len(ParsedHTML(html).links), 64)
        for output in (html, text):
            self.assertIn("English summary 31", output)
            self.assertIn("中文摘要 31", output)
            self.assertIn("Source articles: 32", output)
            self.assertLess(output.index("English summary 31"), output.index("简体中文版"))
        self.assertEqual(html.count(RECIPIENT_FOOTER_SLOT), 1)


if __name__ == "__main__":
    unittest.main()
