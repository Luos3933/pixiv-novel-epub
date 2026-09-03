import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.chapters.markers import parse_chapter_marker
from pixiv_novel_toolkit.chapters.numbering import (
    allocate_output_number,
    build_number_report,
    chapter_name,
    compress_ranges,
    describe_number_gaps,
    normalize_title_key,
    renumber_segments,
)
from txt_file_processing import VolumeSplitter, _compress_ranges


class ChapterNumberingTests(unittest.TestCase):
    def test_range_title_and_gap_helpers(self):
        self.assertEqual(compress_ranges([1, 2, 3, 7, 9, 10]), "001-003、007、009-010")
        self.assertEqual(_compress_ranges([1, 2, 3, 7]), "001-003、007")
        self.assertEqual(normalize_title_key("第 12 章：（4爆）"), "第12章4爆")
        self.assertEqual(chapter_name("第十二章： 雪棠"), "雪棠")
        self.assertEqual(chapter_name("番外：小剧场"), "番外：小剧场")
        self.assertEqual(
            describe_number_gaps({1, 2, 5, 7}),
            ["002->005（缺 003-004）", "005->007（缺 006）"],
        )

    def test_renumber_segments_preserves_first_style_and_fanwai(self):
        first = parse_chapter_marker("第一章 开始")
        repeated = parse_chapter_marker("第一章 继续")
        fanwai = parse_chapter_marker("番外：小剧场")
        segments = [
            {"mk": first, "title": first["raw"]},
            {"mk": repeated, "title": repeated["raw"]},
            {"mk": fanwai, "title": fanwai["raw"]},
        ]

        actual, fixed = renumber_segments(segments)

        self.assertIs(actual, segments)
        self.assertEqual(fixed, 1)
        self.assertEqual(actual[0]["title"], "第一章 开始")
        self.assertEqual(actual[1]["title"], "第二章 继续")
        self.assertEqual(actual[2]["title"], "番外：小剧场")

    def test_output_allocator_prefers_original_and_resolves_duplicates(self):
        used = set()
        warnings = []
        first, last = allocate_output_number(2, used, 0, warn=warnings.append)
        duplicate, last = allocate_output_number(2, used, last, warn=warnings.append)
        unnumbered, last = allocate_output_number(None, used, last, warn=warnings.append)
        self.assertEqual((first, duplicate, unnumbered, last), (2, 3, 4, 4))
        self.assertEqual(used, {2, 3, 4})
        self.assertEqual(len(warnings), 1)

    def test_number_report_includes_all_diagnostic_sections(self):
        report = build_number_report(
            [
                {"orig": 2, "out": 2, "name": "002 第二章.txt"},
                {"orig": 4, "out": 4, "name": "004 第四章.txt"},
                {"orig": 4, "out": 5, "name": "005 第四章重发.txt"},
                {"orig": None, "out": 6, "name": "006 番外.txt"},
            ],
            rejected_markers=[(20, "005疑似正文")],
            suspicious=[(30, "003标题正文同行。")],
            gap_limit=10,
        )
        self.assertIn("首个编号为 002", report)
        self.assertIn("缺失编号（1 个", report)
        self.assertIn("003", report)
        self.assertIn("重复编号（1 处", report)
        self.assertIn("顺延为 005", report)
        self.assertIn("被连续性校验拒绝", report)
        self.assertIn("疑似未识别", report)
        self.assertTrue(report.endswith("\n"))

    def test_volume_splitter_compatibility_wrappers_use_shared_logic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            splitter = VolumeSplitter(temp_dir, str(Path(temp_dir) / "out"))
            self.assertEqual(splitter._chapter_name("第3章 标题"), "标题")
            self.assertEqual(splitter._norm_title_key("标 题！"), "标题")
            splitter._used_nums = set()
            splitter._last_out = 0
            self.assertEqual(splitter._alloc_out_num(3), 3)
            self.assertEqual(splitter._alloc_out_num(3), 4)


if __name__ == "__main__":
    unittest.main()
