import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_toolkit.epub.styles import load_style_presets, parse_style_section
from txt_file_processing import EpubBuilder


class EpubStyleTests(unittest.TestCase):
    def test_loads_two_section_style_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "styles.json"
            path.write_text(
                json.dumps(
                    {
                        "chapter": {"left": {"align": "left", "size": "2em"}},
                        "volume": {"red": {"vol_color": "#990000"}},
                    }
                ),
                encoding="utf-8",
            )

            presets = load_style_presets(path)

            self.assertEqual(presets["chapter"]["left"]["align"], "left")
            self.assertEqual(presets["volume"]["red"]["vol_color"], "#990000")
            self.assertEqual(EpubBuilder.load_presets(path), presets)

    def test_invalid_alignment_is_skipped(self):
        warnings = []
        result = parse_style_section(
            {"bad": {"align": "right"}},
            warning=warnings.append,
        )
        self.assertEqual(result, {})
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()

