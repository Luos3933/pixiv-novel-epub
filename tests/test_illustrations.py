import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.epub.illustrations import (
    parse_illustrations_file,
    parse_illustrations_json,
    parse_illustrations_text,
)
from txt_file_processing import EpubBuilder


class IllustrationParsingTests(unittest.TestCase):
    def test_text_format_prefers_chapter_in_filename(self):
        content = (
            "002 第二章\n"
            "【插图: ch041_up_1.jpg】\n描述一\n描述二\n"
            "【插图：plain.png】\n描述三\n"
        )
        entries = parse_illustrations_text(content)
        self.assertEqual(entries["041"][0]["desc"], ["描述一", "描述二"])
        self.assertEqual(entries["002"][0]["img"], "plain.png")

    def test_json_format_normalizes_explicit_chapter(self):
        entries = parse_illustrations_json(
            [{"chapter": "2", "img": "image.png", "desc": "第一行\n第二行"}]
        )
        self.assertEqual(entries["002"][0]["desc"], ["第一行", "第二行"])

    def test_file_parser_and_legacy_builder_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "illustrations.json"
            path.write_text(
                json.dumps([{"chapter": 1, "img": "image.jpg"}], ensure_ascii=False),
                encoding="utf-8",
            )
            expected = parse_illustrations_file(path)
            builder = EpubBuilder([], "unused.epub")
            self.assertEqual(builder._parse_illustrations_file(path), expected)


if __name__ == "__main__":
    unittest.main()

