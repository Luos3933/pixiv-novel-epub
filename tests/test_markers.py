import unittest

from pixiv_novel_toolkit.chapters.markers import (
    chapter_number_to_chinese,
    chinese_chapter_number_to_int,
    parse_chapter_marker,
    unify_chapter_marker,
)


class ChapterMarkerTests(unittest.TestCase):
    def test_chinese_number_conversions(self):
        self.assertEqual(chapter_number_to_chinese(144), "一百四十四")
        self.assertEqual(chinese_chapter_number_to_int("一百四十四"), 144)
        self.assertEqual(chinese_chapter_number_to_int("一四四"), 144)

    def test_parse_supported_marker_styles(self):
        cases = {
            "第一四四章 风雪": (144, "chinese", "风雪"),
            "第407章：暗中危机": (407, "arabic", "暗中危机"),
            "407章 暗中危机": (407, "bare_sfx", "暗中危机"),
            "588对战阿法摩": (588, "bare", "对战阿法摩"),
            "番外：小剧场": (None, "fanwai", "番外：小剧场"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                marker = parse_chapter_marker(raw)
                self.assertIsNotNone(marker)
                self.assertEqual((marker["num"], marker["style"], marker["title"]), expected)

    def test_reject_sentence_and_quantity(self):
        self.assertIsNone(parse_chapter_marker("第三章内容是一段正文。"))
        self.assertIsNone(parse_chapter_marker("500万像素"))
        self.assertIsNone(parse_chapter_marker("番外 这是一段正文。"))

    def test_unify_marker(self):
        marker = parse_chapter_marker("407：暗中危机")
        unified = unify_chapter_marker(marker)
        self.assertEqual(unified["raw"], "第四百零七章 暗中危机")


if __name__ == "__main__":
    unittest.main()

