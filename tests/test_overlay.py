import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.chapters.overlay import build_prefix_index, collect_text_overlay


class ChapterOverlayTests(unittest.TestCase):
    def test_later_directory_overrides_same_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "standardized"
            corrected = root / "corrected"
            baseline.mkdir()
            corrected.mkdir()
            (baseline / "001 第一章.txt").write_text("旧", encoding="utf-8")
            (baseline / "002 第二章.txt").write_text("第二章", encoding="utf-8")
            (corrected / "001 新标题.txt").write_text("新", encoding="utf-8")
            (corrected / "_toc.txt").write_text("系统文件", encoding="utf-8")

            collected = collect_text_overlay([str(baseline), str(corrected)])

            self.assertEqual(collected["001"][0], "001 新标题.txt")
            self.assertEqual(collected["002"][0], "002 第二章.txt")
            self.assertNotIn("_toc.txt", collected)

    def test_prefix_index_reports_conflicts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "003 A.txt").write_text("A", encoding="utf-8")
            (root / "003 B.txt").write_text("B", encoding="utf-8")
            warnings = []

            prefix_map, no_prefix = build_prefix_index(str(root), warn=warnings.append)

            self.assertIn(prefix_map["003"], {"003 A.txt", "003 B.txt"})
            self.assertEqual(no_prefix, [])
            self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
