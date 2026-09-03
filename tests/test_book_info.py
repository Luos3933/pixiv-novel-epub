import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.postprocess.book_info import (
    format_update_date,
    format_word_count,
    parse_book_info_file,
    parse_pixiv_info_file,
    parse_pixiv_metadata_file,
    upsert_maker_line,
)
from txt_file_processing import BookInfoGenerator, EpubBuilder


class BookInfoTests(unittest.TestCase):
    def test_parses_pixiv_info_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            info_path = root / "series_1_info.txt"
            info_path.write_text(
                "系列名称：测试系列\n作者：作者\n更新时间：2026-09-02 10:00:00\n"
                "总字数：12,345\n章节数：3\n标签：奇幻、冒险\n简介：第一段\n第二段\n",
                encoding="utf-8",
            )
            metadata_path = root / "series_1_metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "1": {"title": "第一章", "word_count": 100},
                        "2": {"title": "番外", "word_count": 20},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            info = parse_pixiv_info_file(info_path)
            metadata = parse_pixiv_metadata_file(metadata_path)

            self.assertEqual(info["title"], "测试系列")
            self.assertEqual(info["word_count"], 12345)
            self.assertEqual(info["tags"], ["奇幻", "冒险"])
            self.assertEqual(metadata["word_count"], 120)
            self.assertEqual(metadata["extra_count"], 1)

    def test_parses_book_info_and_preserves_first_maker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "000 书籍信息.txt"
            path.write_text(
                "书籍信息\n\n书名\n\n作者：甲\n\n连载于：Pixiv\n\n卷数：2\n\n"
                "字数：1.2万字\n\nTXT制作：A\nEPUB制作：B\n\n简介：\n第一段\n第二段\n",
                encoding="utf-8",
            )

            info = parse_book_info_file(path)

            self.assertEqual(info["title"], "书名")
            self.assertEqual(info["platform"], "Pixiv")
            self.assertEqual(info["vol_count"], "2")
            self.assertEqual(info["maker"], "A")
            self.assertEqual(info["description"], "第一段\n第二段")
            self.assertEqual(EpubBuilder._parse_book_info_file(path), info)

    def test_maker_update_is_idempotent_and_handles_backslash(self):
        original = "书籍信息\n\n书名\n\n字数：1.0万字\n\nTXT制作：旧\n\n简介：\n内容\n"
        updated, ok = upsert_maker_line(original, r"A\B")
        again, second_ok = upsert_maker_line(updated, r"A\B")

        self.assertTrue(ok and second_ok)
        self.assertEqual(again.count("TXT制作："), 1)
        self.assertIn(r"TXT制作：A\B", again)
        self.assertEqual(BookInfoGenerator._upsert_maker_line(updated, r"A\B")[0], again)

    def test_format_helpers(self):
        self.assertEqual(format_word_count(12345), "1.2万字")
        self.assertEqual(format_update_date("2026-09-02 10:00:00"), "2026年9月2日")


if __name__ == "__main__":
    unittest.main()

