import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.chapters.markers import GLUED_QUANTITY_STARTERS
from pixiv_novel_toolkit.chapters.splitting import (
    discover_split_inputs,
    find_volume_overlaps,
    list_chapter_text_files,
    scan_suspicious_markers,
    volume_name_from_filename,
    write_volumes_file,
)


class SplittingTests(unittest.TestCase):
    def test_directory_discovery_filters_system_files_and_sorts_chapters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "010 十.txt",
                "002 二.txt",
                "附录.txt",
                "000 书籍信息.txt",
                "_编号统计.txt",
                "series_1_info.txt",
                "ignore.md",
            ):
                (root / name).write_text("", encoding="utf-8")

            self.assertEqual(
                list_chapter_text_files(str(root)),
                ["002 二.txt", "010 十.txt", "附录.txt"],
            )
            inputs = discover_split_inputs(str(root))
            self.assertFalse(inputs.single_file)
            self.assertEqual(inputs.filenames, ["002 二.txt", "010 十.txt", "附录.txt"])

    def test_single_txt_discovery_and_volume_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "01 第一卷.txt"
            source.write_text("第一章 开始", encoding="utf-8")

            inputs = discover_split_inputs(str(source))

            self.assertTrue(inputs.single_file)
            self.assertEqual(inputs.filenames, [source.name])
            self.assertEqual(volume_name_from_filename(source.name), "第一卷")

    def test_suspicious_scan_skips_rejected_and_body_like_quantity_lines(self):
        lines = [
            "001第一章",
            "002疑似标题",
            "003被连续性校验拒绝",
            "004年发生了很多事情。",
            "005第五章",
            "004万兽森林",
        ]
        export_log = [
            {"orig": 1, "out": 1, "name": "001.txt"},
            {"orig": 5, "out": 5, "name": "005.txt"},
        ]

        result = scan_suspicious_markers(
            lines,
            export_log,
            [(3, "003被连续性校验拒绝")],
            GLUED_QUANTITY_STARTERS,
        )

        self.assertEqual(result, [(2, "002疑似标题"), (6, "004万兽森林")])

    def test_volume_overlap_and_json_output(self):
        volumes = [
            {"name": "第一卷", "start": 1, "end": 10},
            {"name": "第二卷", "start": 10, "end": 20},
            {"name": "第三卷", "start": 21, "end": 30},
        ]
        self.assertEqual(find_volume_overlaps(volumes), [(volumes[0], volumes[1])])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "standardized"
            output.mkdir()
            path = Path(write_volumes_file(str(output), volumes))
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(json.loads(text), volumes)
            self.assertEqual(path, Path(temp_dir) / "volumes.json")


if __name__ == "__main__":
    unittest.main()
