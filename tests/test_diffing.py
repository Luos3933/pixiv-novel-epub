import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.postprocess.diffing import (
    DirectoryDiffer,
    TxtFileComparator,
    diff_paragraphs,
)


class DiffingTests(unittest.TestCase):
    def test_paragraph_diff_ignores_blank_lines_and_finds_first_character(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("标题\n\n相同\n旧文字\n", encoding="utf-8")
            second.write_text("标题\n相同\n新文字\n新增段\n", encoding="utf-8")

            result = diff_paragraphs(str(first), str(second))

            self.assertEqual(result["total_diff"], 2)
            changed = result["changed_paragraphs"][0]
            self.assertEqual(changed["line_no"], 3)
            self.assertEqual(changed["first_diff_pos"], 1)
            self.assertEqual((changed["char1"], changed["char2"]), ("旧", "新"))
            self.assertEqual(result["only_in_2"], [(7, "新增段")])

    def test_legacy_static_method_delegates_to_shared_function(self):
        self.assertIs(TxtFileComparator._diff_paragraphs, diff_paragraphs)

    def test_directory_diff_tracks_modified_renamed_and_one_sided_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "standardized"
            corrected = root / "corrected"
            baseline.mkdir()
            corrected.mkdir()
            (baseline / "001 旧名.txt").write_text("相同", encoding="utf-8")
            (corrected / "001 新名.txt").write_text("相同", encoding="utf-8")
            (baseline / "002 第二章.txt").write_text("旧", encoding="utf-8")
            (corrected / "002 第二章.txt").write_text("新", encoding="utf-8")
            (baseline / "003 仅标准化.txt").write_text("三", encoding="utf-8")
            (corrected / "004 仅校正.txt").write_text("四", encoding="utf-8")
            report = root / "diff.txt"

            result = DirectoryDiffer(
                str(baseline), str(corrected), str(report)
            ).diff()

            self.assertEqual(result, {
                "common": 2,
                "modified": 1,
                "unchanged": 1,
                "renamed_only": 1,
                "only_baseline": 1,
                "only_corrected": 1,
            })
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("001 旧名.txt  ->  001 新名.txt", report_text)
            self.assertIn("1 篇改动", report_text)


if __name__ == "__main__":
    unittest.main()
