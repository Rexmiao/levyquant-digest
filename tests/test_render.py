"""Meaningful rendering/security checks using only the standard library."""

import copy
from html.parser import HTMLParser
import unittest

from levyquant.render import RECIPIENT_FOOTER_SLOT, render_digest


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
            "title": "LevyQuant Daily",
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
        self.assertIn(self.articles[0]["published_at"], html)
        self.assertIn(self.articles[0]["source"], text)
        self.assertIn("Editorial analysis:", text)
        self.assertNotIn("Morning Edition", text)
        self.assertNotIn("DO NOT SEND", text)
        self.assertNotIn("agent-s", text)

    def test_unconfigured_mode_is_marked_as_not_sendable(self):
        self.digest.pop("mode")
        self.digest["sections"] = []
        html, text = render_digest(self.digest, self.articles)
        self.assertIn("运行模式未确认 / 禁止发送", html)
        self.assertIn("本期没有可展示的内容", text)

    def test_new_brand_and_optional_personalization_slot_are_only_in_the_footer(self):
        self.digest.update(language="en", footer_personalization=True)
        html, text = render_digest(self.digest, self.articles)
        brand = "LevyQuant · Macro, U.S. equities and quantitative research · Source articles: 1"
        self.assertIn(brand, text)
        self.assertEqual(html.count(RECIPIENT_FOOTER_SLOT), 1)
        footer_start = html.index('data-digest-block="footer"')
        self.assertLess(footer_start, html.index(RECIPIENT_FOOTER_SLOT))
        self.assertLess(html.index(RECIPIENT_FOOTER_SLOT), html.index("</td>", footer_start))
        self.assertNotIn(RECIPIENT_FOOTER_SLOT, text)
        self.assertNotIn("This briefing is sent", html + text)
        self.digest["footer_personalization"] = False
        self.assertNotIn(RECIPIENT_FOOTER_SLOT, render_digest(self.digest, self.articles)[0])


if __name__ == "__main__":
    unittest.main()
