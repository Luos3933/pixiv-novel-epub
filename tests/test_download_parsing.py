import unittest

from pixiv_novel_scraper import (
    clean_filename as legacy_clean_filename,
    clean_html as legacy_clean_html,
    extract_tag_names as legacy_extract_tag_names,
    parse_chapter_selection as legacy_parse_chapter_selection,
)
from pixiv_novel_toolkit.downloads.parsing import (
    clean_filename,
    clean_html,
    extract_tag_names,
    parse_chapter_selection,
    parse_pixiv_novel_id,
    parse_pixiv_series_id,
)


class DownloadParsingTests(unittest.TestCase):
    def test_legacy_module_reexports_shared_helpers(self):
        self.assertIs(legacy_clean_filename, clean_filename)
        self.assertIs(legacy_clean_html, clean_html)
        self.assertIs(legacy_extract_tag_names, extract_tag_names)
        self.assertIs(legacy_parse_chapter_selection, parse_chapter_selection)

    def test_clean_html_and_filename_preserve_previous_behavior(self):
        self.assertEqual(clean_filename('a:b/c?.txt'), "a_b_c_.txt")
        self.assertEqual(clean_html("<b>A&amp;B</b><br />&lt;end&gt;"), "A&B\n<end>")

    def test_parse_chapter_selection(self):
        self.assertEqual(parse_chapter_selection("", 3), [1, 2, 3])
        self.assertEqual(parse_chapter_selection(" 2 - 4 ", 5), [2, 3, 4])
        with self.assertRaises(ValueError):
            parse_chapter_selection("4-2", 5)
        with self.assertRaises(ValueError):
            parse_chapter_selection("6", 5)

    def test_extract_tag_names_handles_variants_and_deduplicates(self):
        tags = {
            "tags": [
                {"tag": "冒险"},
                {"translation": {"en": "fantasy"}},
                "冒险",
                {"name": ""},
            ]
        }
        self.assertEqual(extract_tag_names(tags), ["冒险", "fantasy"])

    def test_parse_series_id_accepts_numeric_and_urls_without_scheme(self):
        self.assertEqual(parse_pixiv_series_id("456"), "456")
        self.assertEqual(
            parse_pixiv_series_id("https://www.pixiv.net/novel/series/456?lang=zh"),
            "456",
        )
        self.assertEqual(
            parse_pixiv_series_id('www.pixiv.net/novel/series/456"'),
            "456",
        )
        self.assertEqual(
            parse_pixiv_series_id("pixiv.net/novel/series/456/"),
            "456",
        )

    def test_parse_novel_id_accepts_numeric_and_urls_without_scheme(self):
        self.assertEqual(parse_pixiv_novel_id("123"), "123")
        self.assertEqual(
            parse_pixiv_novel_id("https://www.pixiv.net/novel/show.php?id=123"),
            "123",
        )
        self.assertEqual(
            parse_pixiv_novel_id("www.pixiv.net/novel/show.php?id=123"),
            "123",
        )
        self.assertEqual(parse_pixiv_novel_id("pixiv.net/novel/123"), "123")

    def test_pixiv_id_parser_rejects_wrong_kind_and_foreign_hosts(self):
        with self.assertRaises(ValueError):
            parse_pixiv_series_id("pixiv.net/novel/show.php?id=123")
        with self.assertRaises(ValueError):
            parse_pixiv_novel_id("pixiv.net/novel/series/456")
        with self.assertRaises(ValueError):
            parse_pixiv_series_id("example.com/novel/series/456")


if __name__ == "__main__":
    unittest.main()
