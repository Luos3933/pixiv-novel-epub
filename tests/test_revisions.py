import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.postprocess.revisions import RevisionsStore


class RevisionsStoreTests(unittest.TestCase):
    def test_number_key_finds_current_filename_and_persists_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapter = root / "043 新标题.txt"
            chapter.write_text("正文", encoding="utf-8")

            store = RevisionsStore(str(root))
            store.set("043", "修正错字")

            record = store.list_all()["043"]
            self.assertEqual(record["filename"], chapter.name)
            self.assertEqual(record["msg"], "修正错字")
            self.assertTrue(record["mtime"])
            saved = json.loads((root / "_revisions.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["043"]["filename"], chapter.name)

    def test_full_filename_uses_prefix_and_remove_accepts_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            filename = "007 第七章.txt"
            (root / filename).write_text("正文", encoding="utf-8")
            store = RevisionsStore(str(root))

            store.set(filename, "调整标题")

            self.assertIn("007", store.list_all())
            self.assertTrue(store.remove("007"))
            self.assertEqual(store.list_all(), {})


if __name__ == "__main__":
    unittest.main()
