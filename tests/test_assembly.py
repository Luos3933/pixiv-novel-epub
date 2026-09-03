import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.postprocess.assembly import DirectoryAssembler


class DirectoryAssemblerTests(unittest.TestCase):
    def test_corrected_files_override_by_prefix_and_mapping_is_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "standardized"
            corrected = root / "corrected"
            output = root / "final"
            baseline.mkdir()
            corrected.mkdir()
            (baseline / "001 旧标题.txt").write_text("标准化一", encoding="utf-8")
            (baseline / "002 第二章.txt").write_text("标准化二", encoding="utf-8")
            (baseline / "附录.txt").write_text("旧附录", encoding="utf-8")
            (corrected / "001 新标题.txt").write_text("校正一", encoding="utf-8")
            (corrected / "附录.txt").write_text("新附录", encoding="utf-8")
            (corrected / "_revisions.txt").write_text("忽略", encoding="utf-8")

            result = DirectoryAssembler(
                str(baseline), str(corrected), str(output)
            ).assemble()

            self.assertEqual(result, {
                "total": 3,
                "from_corrected": 2,
                "from_baseline": 1,
                "renamed": 1,
            })
            self.assertEqual(
                (output / "001 新标题.txt").read_text(encoding="utf-8"), "校正一"
            )
            self.assertEqual(
                (output / "002 第二章.txt").read_text(encoding="utf-8"), "标准化二"
            )
            self.assertEqual((output / "附录.txt").read_text(encoding="utf-8"), "新附录")
            self.assertFalse((output / "_revisions.txt").exists())
            mapping = (output / "_source_map.txt").read_text(encoding="utf-8")
            self.assertIn("001 新标题.txt  <- 校正", mapping)
            self.assertIn("改名: 001 旧标题.txt -> 001 新标题.txt", mapping)


if __name__ == "__main__":
    unittest.main()
