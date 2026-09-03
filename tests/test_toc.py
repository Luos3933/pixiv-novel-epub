import tempfile
import unittest
from pathlib import Path

from txt_file_processing import TocManager


class TocManagerTests(unittest.TestCase):
    def test_directory_apply_renames_file_and_replaces_title_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "001 旧标题.txt"
            source.write_text("旧标题\n正文\n", encoding="utf-8")
            toc_file = root / "toc.txt"
            toc_file.write_text("001 第一章 新/标题\n002 缺失章节\n", encoding="utf-8")

            result = TocManager(str(root)).apply(str(toc_file))

            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["missed"], 1)
            renamed = root / "001 第一章 新 标题.txt"
            self.assertTrue(renamed.exists())
            self.assertEqual(
                renamed.read_text(encoding="utf-8").splitlines()[0],
                "第一章 新/标题",
            )

    def test_file_apply_stops_before_backup_when_entry_count_changed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "book.txt"
            toc_file = Path(temp_dir) / "toc.txt"
            original = "第一章 旧标题\n正文\n第二章 旧标题\n"
            source.write_text(original, encoding="utf-8")
            toc_file.write_text("001 第一章 新标题\n", encoding="utf-8")

            result = TocManager(str(source)).apply(str(toc_file))

            self.assertIsNone(result)
            self.assertFalse(Path(str(source) + ".bak").exists())
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_directory_export_reuses_chapter_file_filter_and_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "010 第十章.txt").write_text("", encoding="utf-8")
            (root / "002 第二章.txt").write_text("", encoding="utf-8")
            (root / "000 书籍信息.txt").write_text("", encoding="utf-8")
            (root / "_编号统计.txt").write_text("", encoding="utf-8")
            output = root / "toc.txt"

            result = TocManager(str(root)).export(str(output))

            self.assertEqual(result["chapters"], 2)
            entries = [line for line in output.read_text(encoding="utf-8").splitlines()
                       if line and not line.startswith("#")]
            self.assertEqual(entries[:2], ["002 第二章", "010 第十章"])

    def test_file_export_keeps_all_syntactic_markers_without_continuity_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "book.txt"
            output = Path(temp_dir) / "toc.txt"
            source.write_text(
                "第一百章 高点\n正文\n第五章 回退但仍应预览\n",
                encoding="utf-8",
            )

            result = TocManager(str(source)).export(str(output))

            self.assertEqual(result["markers"], 2)
            toc_text = output.read_text(encoding="utf-8")
            self.assertIn("100 第一百章 高点", toc_text)
            self.assertIn("005 第五章 回退但仍应预览", toc_text)

    def test_file_apply_replaces_markers_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "book.txt"
            toc_file = Path(temp_dir) / "toc.txt"
            original = "第一章 旧标题\n正文\n第二章 旧标题\n"
            source.write_text(original, encoding="utf-8")
            toc_file.write_text("001 第一章 新标题\n002 第二章 新标题\n", encoding="utf-8")

            result = TocManager(str(source)).apply(str(toc_file))

            self.assertEqual(result["replaced"], 2)
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)
            updated = source.read_text(encoding="utf-8")
            self.assertIn("第一章 新标题", updated)
            self.assertIn("第二章 新标题", updated)


if __name__ == "__main__":
    unittest.main()
