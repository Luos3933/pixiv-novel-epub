import tempfile
import unittest
from pathlib import Path

from txt_file_processing import VolumeSplitter


class VolumeSplitterTests(unittest.TestCase):
    def test_split_uses_shared_marker_parser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            output = root / "standardized"
            source.write_text(
                "第一章 开始\n这是第一章。\n第二章 继续\n这是第二章。\n",
                encoding="utf-8",
            )

            result = VolumeSplitter(str(source), str(output)).split()

            self.assertIsNotNone(result)
            chapter_files = sorted(path.name for path in output.glob("[0-9][0-9][0-9] *.txt"))
            self.assertIn("001 第一章 开始.txt", chapter_files)
            self.assertIn("002 第二章 继续.txt", chapter_files)
            self.assertTrue((root / "volumes.json").exists())
            report = output / "_编号统计.txt"
            self.assertTrue(report.exists())
            self.assertIn("编号从 001 起连续", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
