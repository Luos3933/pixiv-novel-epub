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

    def test_batch_punctuation_keeps_quote_state_across_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chapters"
            output = root / "standardized"
            source.mkdir()
            (source / "001 对话.txt").write_text(
                '他说:"第一行\n第二行"',
                encoding="utf-8",
            )

            BatchTxtFileFormatter(str(source), str(output), punct=True).format_all_files()

            content = (output / "001 第一章 对话.txt").read_text(encoding="utf-8")
            self.assertIn("他说:“第一行", content)
            self.assertIn("第二行”", content)

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

    def test_format_command_uses_reviewed_sibling_as_prefix_overlay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cleaned = root / "cleaned"
            reviewed = root / "reviewed"
            output = root / "standardized"
            cleaned.mkdir()
            reviewed.mkdir()
            (cleaned / "001 原标题.txt").write_text("机器清洗版", encoding="utf-8")
            (cleaned / "002 继续.txt").write_text("未人工修改", encoding="utf-8")
            (reviewed / "001 人工标题.txt").write_text("人工复核版", encoding="utf-8")

            result = _cmd_format_batch(SimpleNamespace(
                input_folder=str(cleaned),
                output_folder=str(output),
                punct=False,
            ))

            self.assertEqual(result, 0)
            first = output / "001 第一章 人工标题.txt"
            second = output / "002 第二章 继续.txt"
            self.assertTrue(first.is_file())
            self.assertIn("人工复核版", first.read_text(encoding="utf-8"))
            self.assertNotIn("机器清洗版", first.read_text(encoding="utf-8"))
            self.assertTrue(second.is_file())

    def test_format_command_accepts_explicit_reviewed_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            manual = root / "manual_before_format"
            output = root / "standardized"
            chapters.mkdir()
            manual.mkdir()
            (chapters / "001 原标题.txt").write_text("原始版", encoding="utf-8")
            (manual / "001 人工标题.txt").write_text("人工版", encoding="utf-8")

            result = _cmd_format_batch(SimpleNamespace(
                input_folder=str(chapters),
                output_folder=str(output),
                reviewed_dir=str(manual),
                punct=False,
            ))

            self.assertEqual(result, 0)
            formatted = output / "001 第一章 人工标题.txt"
            self.assertIn("人工版", formatted.read_text(encoding="utf-8"))

    def test_format_command_rejects_missing_explicit_reviewed_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            chapters.mkdir()
            (chapters / "001 标题.txt").write_text("正文", encoding="utf-8")

            result = _cmd_format_batch(SimpleNamespace(
                input_folder=str(chapters),
                output_folder=str(root / "standardized"),
                reviewed_dir=str(root / "missing"),
                punct=False,
            ))

            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
