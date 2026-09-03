import unittest

from pixiv_novel_toolkit.chapters.markers import (
    parse_chapter_marker,
    unify_chapter_marker,
)
from pixiv_novel_toolkit.chapters.scanning import (
    scan_chapter_segments,
    scan_marker_lines,
)


class ChapterScanningTests(unittest.TestCase):
    def test_marker_scan_returns_zero_based_source_positions(self):
        lines = ["前言\n", "第一章 开始\n", "正文\n", "番外：后记\n"]
        markers = scan_marker_lines(lines)
        self.assertEqual([index for index, _ in markers], [1, 3])
        self.assertEqual([marker["style"] for _, marker in markers], ["chinese", "fanwai"])

    def test_segment_scan_collects_preamble_and_body(self):
        result = scan_chapter_segments(
            ["书名\n", "作者\n", "第一章 开始\n", "正文一\n", "第二章 继续\n"],
            parse_chapter_marker,
        )
        self.assertEqual(result.preamble, ["书名", "作者"])
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[0]["lines"], ["正文一\n"])
        self.assertEqual(result.rejected_markers, [])

    def test_large_rollback_is_rejected_and_merged_into_previous_body(self):
        warnings = []
        result = scan_chapter_segments(
            ["第一百章 高点\n", "正文\n", "第五章 疑似正文\n", "后续\n"],
            parse_chapter_marker,
            gap_limit=10,
            warn=warnings.append,
        )
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.rejected_markers, [(3, "第五章 疑似正文")])
        self.assertIn("第五章 疑似正文\n", result.segments[0]["lines"])
        self.assertEqual(len(warnings), 1)

    def test_same_number_same_title_repost_survives_large_rollback(self):
        messages = []
        result = scan_chapter_segments(
            ["第五章 重发\n", "第二十章 高点\n", "第五章 重发\n"],
            parse_chapter_marker,
            gap_limit=10,
            info=messages.append,
        )
        self.assertEqual(len(result.segments), 3)
        self.assertEqual(result.rejected_markers, [])
        self.assertIn("同号同题", messages[0])

    def test_optional_unifier_runs_only_for_numbered_markers(self):
        result = scan_chapter_segments(
            ["第2章 标题\n", "番外：后记\n"],
            parse_chapter_marker,
            unify_marker=lambda marker: unify_chapter_marker(marker, num_style="chinese"),
        )
        self.assertEqual(result.segments[0]["title"], "第二章 标题")
        self.assertEqual(result.segments[1]["title"], "番外：后记")


if __name__ == "__main__":
    unittest.main()
