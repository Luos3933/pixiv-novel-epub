import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pixiv_novel_toolkit.postprocess_cli import _cmd_format_batch
from pixiv_novel_toolkit.postprocess.formatting import (
    BatchTxtFileFormatter,
    TxtFileFormatter,
    convert_punctuation,
    interleave_blank_lines,
)


class FormattingTests(unittest.TestCase):
    def test_interleave_blank_lines_strips_and_discards_empty_lines(self):
        self.assertEqual(
            interleave_blank_lines([" 第一段 \n", "\n", "第二段\n"]),
            ["第一段", "", "第二段", ""],
        )

    def test_convert_punctuation_reports_unpaired_quotes(self):
        converted, stats = convert_punctuation('他说:"你好!" 真的? "')
        self.assertEqual(converted, "他说:“你好！” 真的？ “")
        self.assertEqual(stats["front_quote"], 2)
        self.assertEqual(stats["back_quote"], 1)
        self.assertEqual(stats["unpaired"], 1)
        self.assertEqual(stats["original_exclamation"], 1)
        self.assertEqual(stats["original_question"], 1)

    def test_single_file_formatter_adds_paragraph_spacing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            output = root / "output.txt"
            source.write_text("一\n\n二\n", encoding="utf-8")
            TxtFileFormatter(str(source), str(output)).add_blank_lines()
            self.assertEqual(output.read_text(encoding="utf-8"), "一\n\n二\n")

    def test_batch_formatter_numbers_main_chapters_and_keeps_extras_out_of_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chapters"
            output = root / "standardized"
            source.mkdir()
            (source / "001 开始.txt").write_text('正文! "引号"', encoding="utf-8")
            (source / "002 番外 小剧场.txt").write_text("番外正文", encoding="utf-8")
            (source / "003 继续.txt").write_text("正文?", encoding="utf-8")

            BatchTxtFileFormatter(str(source), str(output), punct=True).format_all_files()

            self.assertTrue((output / "001 第一章 开始.txt").exists())
            self.assertTrue((output / "002 番外：小剧场.txt").exists())
            third = output / "003 第二章 继续.txt"
            self.assertTrue(third.exists())
            self.assertIn("正文？", third.read_text(encoding="utf-8"))
            self.assertTrue((output / "000 书籍信息.txt").exists())

    def test_format_command_creates_corrected_sibling_and_preserves_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chapters"
            output = root / "standardized"
            corrected = root / "corrected"
            source.mkdir()
            (source / "001 开始.txt").write_text("正文", encoding="utf-8")

            result = _cmd_format_batch(SimpleNamespace(
                input_folder=str(source),
                output_folder=str(output),
                punct=False,
            ))

            self.assertEqual(result, 0)
            self.assertTrue(corrected.is_dir())

            keep = corrected / "已有校正.txt"
            keep.write_text("保留", encoding="utf-8")
            second_result = _cmd_format_batch(SimpleNamespace(
                input_folder=str(source),
                output_folder=str(output),
                punct=False,
            ))
            self.assertEqual(second_result, 0)
            self.assertEqual(keep.read_text(encoding="utf-8"), "保留")


if __name__ == "__main__":
    unittest.main()
