import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.chapters.volumes import load_volumes_file
from txt_file_processing import _load_volumes_file


class VolumeConfigTests(unittest.TestCase):
    def test_loads_sorts_and_skips_invalid_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "volumes.json"
            path.write_text(
                json.dumps(
                    [
                        {"name": "第二卷", "start": 3, "end": 5},
                        {"name": "第一卷", "start": "1", "end": "2"},
                        {"name": "错误卷", "start": 9, "end": 8},
                        {"start": 10},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            warnings = []

            volumes = load_volumes_file(path, warning=warnings.append)

            self.assertEqual([volume["name"] for volume in volumes], ["第一卷", "第二卷"])
            self.assertEqual(len(warnings), 2)
            with self.assertLogs("pixiv_novel_toolkit.postprocess", level="WARNING"):
                compatibility_volumes = _load_volumes_file(path)
            self.assertEqual(compatibility_volumes, volumes)

    def test_missing_file_returns_none(self):
        errors = []
        result = load_volumes_file("missing-volumes.json", error=errors.append)
        self.assertIsNone(result)
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
