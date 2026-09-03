import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.chapters.split_config import (
    SPLIT_CONFIG_DEFAULTS,
    load_split_config,
)


class SplitConfigTests(unittest.TestCase):
    def test_missing_config_generates_template_and_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "split_config.json"
            config = load_split_config(str(path))
            self.assertEqual(config, SPLIT_CONFIG_DEFAULTS)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["marker_max_len"], 40
            )

    def test_null_disables_and_invalid_value_falls_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "split_config.json"
            path.write_text(
                json.dumps({"chapter_gap_limit": None, "marker_max_len": True}),
                encoding="utf-8",
            )
            config = load_split_config(str(path))
            self.assertEqual(config["chapter_gap_limit"], 0)
            self.assertEqual(config["marker_max_len"], 40)


if __name__ == "__main__":
    unittest.main()
