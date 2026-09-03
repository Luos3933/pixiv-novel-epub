import unittest

from pixiv_novel_toolkit.epub.planning import plan_spine
from txt_file_processing import EpubBuilder


class EpubPlanningTests(unittest.TestCase):
    def test_places_volume_before_first_matching_chapter(self):
        chapters = [
            ("001", "第一章", "one.txt"),
            ("002", "第二章", "two.txt"),
            ("附录", "附录", "appendix.txt"),
        ]
        volumes = [{"name": "第一卷", "start": 1, "end": 2}]

        spine, mapping = plan_spine(chapters, volumes)

        self.assertEqual([item["kind"] for item in spine], ["vol", "chap", "chap", "chap"])
        self.assertEqual(mapping, {1: ["001", "002"]})
        self.assertEqual(spine[-1]["fname"], "chap_0003.xhtml")
        builder = EpubBuilder([], "unused.epub")
        self.assertEqual(builder._plan_spine(chapters, volumes), (spine, mapping))

    def test_skips_empty_volume(self):
        warnings = []
        spine, mapping = plan_spine(
            [("001", "第一章", "one.txt")],
            [{"name": "空卷", "start": 9, "end": 10}],
            warning=warnings.append,
        )
        self.assertEqual(len(spine), 1)
        self.assertEqual(mapping, {})
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()

