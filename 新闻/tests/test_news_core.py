"""news_core 的单元测试：RSS/Atom 解析、时间过滤、去重、HTML 生成。"""
import gzip
import unittest
from datetime import datetime, timedelta, timezone

import news_core as core

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Feed</title>
<item>
  <title><![CDATA[Hello <b>World</b>]]></title>
  <link>https://example.com/a</link>
  <description><![CDATA[<p>Summary &amp; more</p>]]></description>
  <pubDate>Mon, 23 Nov 2026 05:00:00 GMT</pubDate>
</item>
<item>
  <title>No link item</title>
  <description>should be skipped</description>
  <pubDate>Mon, 23 Nov 2026 05:00:00 GMT</pubDate>
</item>
<item>
  <title>Bad scheme</title>
  <link>javascript:alert(1)</link>
  <pubDate>Mon, 23 Nov 2026 05:00:00 GMT</pubDate>
</item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Feed</title>
<entry>
  <title>Atom Title</title>
  <link rel="alternate" href="https://example.com/b"/>
  <updated>2026-11-23T06:30:00Z</updated>
  <summary>Atom summary text</summary>
</entry>
</feed>"""


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def make_item(title, link, published, summary="摘要", category="world", source="BBC"):
    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published": published,
        "category": category,
        "source": source,
    }


class ParseFeedTests(unittest.TestCase):
    def test_rss_item_fields_are_cleaned(self):
        items = core.parse_feed(RSS)
        # 无 link 与 javascript: 链接的条目会被丢弃，只剩 1 条
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], "Hello World")
        self.assertEqual(it["link"], "https://example.com/a")
        self.assertEqual(it["summary"], "Summary & more")
        self.assertEqual(it["published"], utc(2026, 11, 23, 5, 0))

    def test_atom_entry_is_parsed(self):
        items = core.parse_feed(ATOM)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], "Atom Title")
        self.assertEqual(it["link"], "https://example.com/b")
        self.assertEqual(it["published"], utc(2026, 11, 23, 6, 30))

    def test_long_summary_is_truncated(self):
        long_text = "word " * 200
        items = core.parse_feed(
            "<rss><channel><item><title>T</title>"
            "<link>https://example.com/c</link>"
            f"<description>{long_text}</description>"
            "<pubDate>Mon, 23 Nov 2026 05:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        )
        self.assertLessEqual(len(items[0]["summary"]), core.SUMMARY_LIMIT + 1)
        self.assertTrue(items[0]["summary"].endswith("…"))

    def test_malformed_xml_raises_feed_error(self):
        with self.assertRaises(core.FeedError):
            core.parse_feed("<rss><channel><item>")


class SelectRecentTests(unittest.TestCase):
    NOW = utc(2026, 11, 23, 12, 0)

    def test_keeps_items_inside_window(self):
        items = [
            make_item("in", "https://e.com/1", self.NOW - timedelta(hours=3)),
            make_item("old", "https://e.com/2", self.NOW - timedelta(hours=30)),
            make_item("future", "https://e.com/3", self.NOW + timedelta(hours=5)),
        ]
        kept = core.select_recent(items, self.NOW, hours=24)
        self.assertEqual([i["title"] for i in kept], ["in"])

    def test_window_boundary_is_inclusive(self):
        items = [make_item("edge", "https://e.com/4", self.NOW - timedelta(hours=24))]
        self.assertEqual(len(core.select_recent(items, self.NOW, hours=24)), 1)


class DedupeTests(unittest.TestCase):
    def test_same_link_is_deduped(self):
        a = make_item("One", "https://e.com/x", utc(2026, 11, 23, 1))
        b = make_item("One copy", "https://e.com/x", utc(2026, 11, 23, 2))
        self.assertEqual(len(core.dedupe_items([a, b])), 1)

    def test_same_title_from_different_sources_is_kept(self):
        a = make_item("Shared story", "https://e.com/1", utc(2026, 11, 23, 1), source="BBC")
        b = make_item("Shared story", "https://e.com/2", utc(2026, 11, 23, 2), source="CNN")
        self.assertEqual(len(core.dedupe_items([a, b])), 2)

    def test_same_title_same_source_is_deduped(self):
        a = make_item("Story", "https://e.com/1", utc(2026, 11, 23, 1), source="BBC")
        b = make_item("Story", "https://e.com/2", utc(2026, 11, 23, 2), source="BBC")
        self.assertEqual(len(core.dedupe_items([a, b])), 1)


class PerSourceLimitTests(unittest.TestCase):
    def test_limits_items_per_source(self):
        items = [
            make_item(f"t{i}", f"https://e.com/{i}", utc(2026, 11, 23, 10 - i), source="BBC")
            for i in range(9)
        ]
        items += [make_item("cnn", "https://c.com/1", utc(2026, 11, 23, 9), source="CNN")]
        kept = core.limit_per_source(items, cap=5)
        self.assertEqual(sum(1 for i in kept if i["source"] == "BBC"), 5)
        self.assertEqual(sum(1 for i in kept if i["source"] == "CNN"), 1)


class DecodeResponseTests(unittest.TestCase):
    def test_gzip_payload_is_decompressed(self):
        raw = gzip.compress(RSS.encode("utf-8"))
        self.assertEqual(core.decode_response(raw), RSS.encode("utf-8"))

    def test_plain_payload_is_unchanged(self):
        self.assertEqual(core.decode_response(b"<rss/>"), b"<rss/>")


class PublisherTests(unittest.TestCase):
    GOOGLE_ITEM = (
        "<rss><channel><item>"
        "<title>Some headline - CNN</title>"
        "<link>https://news.google.com/rss/articles/xyz</link>"
        "<source url=\"https://www.cnn.com\">CNN</source>"
        "<pubDate>Mon, 23 Nov 2026 05:00:00 GMT</pubDate>"
        "</item></channel></rss>"
    )

    def test_parse_feed_captures_publisher(self):
        items = core.parse_feed(self.GOOGLE_ITEM)
        self.assertEqual(items[0]["publisher"], "CNN")

    def test_matching_suffix_is_stripped(self):
        self.assertEqual(
            core.strip_publisher_suffix("Some headline - CNN", "CNN"), "Some headline"
        )

    def test_title_without_suffix_is_kept(self):
        self.assertEqual(
            core.strip_publisher_suffix("Headline - Big Story", "CNN"),
            "Headline - Big Story",
        )

    def test_missing_publisher_is_safe(self):
        self.assertEqual(core.strip_publisher_suffix("Headline", ""), "Headline")


class NoiseFilterTests(unittest.TestCase):
    def test_movie_casting_story_is_noise(self):
        self.assertTrue(
            core.is_entertainment_noise(
                "Andrew Garfield on Becoming Sam Altman in 'Artificial'", "IMDb"
            )
        )

    def test_real_commentary_is_not_noise(self):
        self.assertFalse(
            core.is_entertainment_noise(
                "Sam Altman says AI will reshape how people work", "Reuters"
            )
        )


class OpinionFilterTests(unittest.TestCase):
    def test_statement_with_name_and_speech_verb_is_kept(self):
        self.assertTrue(
            core.is_opinion_item(
                "Billionaire Ray Dalio says rising bond yields are shrinking the cushion",
                "Ray Dalio",
            )
        )

    def test_interview_title_is_kept(self):
        self.assertTrue(
            core.is_opinion_item("I Finally Interview Ray Dalio", "Ray Dalio")
        )

    def test_quote_headline_is_kept(self):
        self.assertTrue(
            core.is_opinion_item(
                "'Apology accepted': Google chief scientist Demis Hassabis after apology",
                "Demis Hassabis",
            )
        )

    def test_name_colon_headline_is_kept(self):
        self.assertTrue(
            core.is_opinion_item(
                "Fei-Fei Li: Public Sector and Universities Priced Out of AI",
                "李飞飞",
                aliases=("Fei-Fei Li",),
            )
        )

    def test_chinese_name_with_english_alias_is_matched(self):
        self.assertTrue(
            core.is_opinion_item(
                "Jensen Huang says he would be honored to return as Nvidia CEO",
                "黄仁勋",
                aliases=("Jensen Huang",),
            )
        )

    def test_pure_event_news_without_cue_is_dropped(self):
        self.assertFalse(
            core.is_opinion_item(
                "MSCI Discussed Avoiding Indonesia Downgrade With Prabowo, Dalio",
                "Ray Dalio",
            )
        )

    def test_story_about_different_person_is_dropped(self):
        self.assertFalse(
            core.is_opinion_item(
                "U.S. Tracked Alice Huang's Contacts With China Spy Agency",
                "黄仁勋",
                aliases=("Jensen Huang",),
            )
        )

    def test_movie_story_is_dropped(self):
        self.assertFalse(
            core.is_opinion_item(
                "Andrew Garfield on Becoming Sam Altman in 'Artificial'", "Sam Altman"
            )
        )

    def test_colon_headline_with_person_after_colon_is_dropped(self):
        self.assertFalse(
            core.is_opinion_item(
                "Nvidia live updates: Jensen Huang reinstated as CEO",
                "黄仁勋",
                aliases=("Jensen Huang",),
            )
        )

    def test_news_agency_attribution_is_dropped(self):
        self.assertFalse(
            core.is_opinion_item(
                "MSCI discussed averting Indonesia downgrade with Prabowo, Dalio, says Bloomberg",
                "Ray Dalio",
            )
        )

    def test_substring_of_cue_word_does_not_count(self):
        self.assertFalse(
            core.is_opinion_item(
                "Nvidia Stock Surges More Than 30% After Company Reinstates Jensen Huang as CEO",
                "黄仁勋",
                aliases=("Jensen Huang",),
            )
        )


class SummaryTests(unittest.TestCase):
    def test_summary_equal_to_title_is_redundant(self):
        self.assertTrue(core.summary_is_redundant("Big story", "Big story"))

    def test_summary_with_title_prefix_is_redundant(self):
        self.assertTrue(
            core.summary_is_redundant(
                "I Finally Interview Ray Dalio", "I Finally Interview Ray Dalio | Sourcery"
            )
        )

    def test_real_summary_is_kept(self):
        self.assertFalse(
            core.summary_is_redundant(
                "Rate cut expected", "Markets rallied as investors bet on a cut next month."
            )
        )


class RenderPageTests(unittest.TestCase):
    def render(self, items):
        return core.render_page(
            items=items,
            statuses=[{"name": "BBC", "ok": True, "count": len(items), "error": ""}],
            generated_at=utc(2026, 11, 23, 12, 0),
            date_label="2026年11月23日 星期一",
            archive_dates=["2026-11-23", "2026-11-22"],
            window_note="最近 24 小时",
            site_title="每日国际新闻",
        )

    def test_headline_html_is_escaped(self):
        html = self.render([make_item("<script>alert(1)</script>", "https://e.com/1", utc(2026, 11, 23, 1))])
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_page_contains_source_and_category(self):
        html = self.render([make_item("A headline", "https://e.com/1", utc(2026, 11, 23, 1))])
        self.assertIn("BBC", html)
        self.assertIn("国际", html)
        self.assertIn("https://e.com/1", html)

    def test_archive_links_are_rendered(self):
        html = self.render([make_item("A", "https://e.com/1", utc(2026, 11, 23, 1))])
        self.assertIn("archive/2026-11-22.html", html)

    def test_update_button_and_endpoint_are_present(self):
        html = self.render([make_item("A", "https://e.com/1", utc(2026, 11, 23, 1))])
        self.assertIn('id="refresh"', html)
        self.assertIn("/api/update", html)

    def test_update_button_can_be_hidden(self):
        html = core.render_page(
            items=[],
            statuses=[],
            generated_at=utc(2026, 11, 23, 12, 0),
            date_label="2026年11月23日 星期一",
            archive_dates=[],
            window_note="测试",
            site_title="每日国际新闻",
            show_update=False,
        )
        self.assertNotIn('id="refresh"', html)


if __name__ == "__main__":
    unittest.main()
