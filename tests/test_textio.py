import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.common.textio import detect_encoding, read_text, read_text_lines


class TextIoTests(unittest.TestCase):
    def test_utf8_bom_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "utf8.txt"
            path.write_text("第一行\n第二行", encoding="utf-8-sig")

            self.assertEqual(detect_encoding(path), "utf-8-sig")
            self.assertEqual(read_text_lines(path), ["第一行", "第二行"])

    def test_gb18030_is_decoded_and_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gb.txt"
            path.write_bytes("这是一个测试文本。".encode("gb18030"))
            messages = []

            content = read_text(path, info=messages.append)

            self.assertEqual(content, "这是一个测试文本。")
            self.assertEqual(len(messages), 1)

    def test_damaged_utf8_uses_replacement_without_falling_back_to_gb18030(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "damaged.txt"
            data = "第一章 熟女二婶\n正文仍应正常读取".encode("utf-8")
            path.write_bytes(data[:9] + b"\xff" + data[10:])
            messages = []

            self.assertEqual(detect_encoding(path), "utf-8")
            content = read_text(path, info=messages.append)

            self.assertIn("第一章", content)
            self.assertIn("正文仍应正常读取", content)
            self.assertIn("\ufffd", content)
            self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()
