import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.postprocess.merging import TxtFileMerger


class TxtFileMergerTests(unittest.TestCase):
    def test_later_directory_overrides_and_body_indent_skips_titles_and_book_info(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "standardized"
            corrected = root / "corrected"
            baseline.mkdir()
            corrected.mkdir()
            (baseline / "000 书籍信息.txt").write_text(
                "书籍信息\n书名\n字数：未填\n简介：\n测试", encoding="utf-8"
            )
            (baseline / "001 第一章.txt").write_text(
                "第一章\n旧正文", encoding="utf-8"
            )
            (baseline / "002 第二章.txt").write_text(
                "第二章\n第二章正文", encoding="utf-8"
            )
            (corrected / "001 新标题.txt").write_text(
                "第一章 新标题\n校正正文", encoding="utf-8"
            )
            output = root / "book.txt"

            TxtFileMerger(
                [str(baseline), str(corrected)], str(output), indent=True
            ).merge_txt_files()

            text = output.read_text(encoding="utf-8")
            self.assertIn("第一章 新标题\n\n　　校正正文", text)
            self.assertNotIn("旧正文", text)
            self.assertIn("第二章\n\n　　第二章正文", text)
            self.assertIn("书籍信息\n\n书名", text)

    def test_volumes_and_maker_are_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "standardized"
            chapters.mkdir()
            (chapters / "000 书籍信息.txt").write_text(
                "书籍信息\n\n书名\n\n连载状态：2章\n\n字数：0.1万字\n\n简介：\n\n测试\n",
                encoding="utf-8",
            )
            (chapters / "001 第一章.txt").write_text("第一章\n正文", encoding="utf-8")
            (chapters / "002 第二章.txt").write_text("第二章\n正文", encoding="utf-8")
            volumes_file = root / "volumes.json"
            volumes_file.write_text(
                json.dumps([{"name": "第一卷", "start": 1, "end": 2}], ensure_ascii=False),
                encoding="utf-8",
            )
            output = root / "book.txt"

            TxtFileMerger(
                str(chapters),
                str(output),
                volumes_file=str(volumes_file),
                maker="测试者",
            ).merge_txt_files()

            text = output.read_text(encoding="utf-8")
            self.assertIn("TXT制作：测试者", text)
            self.assertLess(text.index("第一卷"), text.index("第一章"))


if __name__ == "__main__":
    unittest.main()
