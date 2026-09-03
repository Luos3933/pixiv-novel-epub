import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.paths import (
    build_images_dir,
    build_record_file,
    chapter_file_exists,
    find_existing_cover,
    normalize_chapter_number,
)


class DownloadPathTests(unittest.TestCase):
    def test_chapter_number_and_existence_follow_prefix_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chapters = Path(temp_dir)
            (chapters / "011 标题.txt").write_text("正文", encoding="utf-8")
            self.assertEqual(normalize_chapter_number("11"), "011")
            self.assertEqual(normalize_chapter_number("番外"), "番外")
            self.assertTrue(chapter_file_exists(chapters, 11))
            self.assertFalse(chapter_file_exists(chapters, 12))

    def test_legacy_illustration_directory_has_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            self.assertEqual(Path(build_images_dir(work_dir)).name, "illustrations")
            (work_dir / "插图库").mkdir()
            self.assertEqual(Path(build_images_dir(work_dir)).name, "插图库")

    def test_scope_paths_and_scraper_mutable_roots_remain_compatible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            novels_dir = root / "n"
            series_dir = root / "s"
            self.assertEqual(
                Path(build_record_file(novels_dir, series_dir, "novel", "1")),
                novels_dir / "novel_1" / "novel_1_records.csv",
            )
            self.assertEqual(
                Path(build_record_file(novels_dir, series_dir, "series", "2")),
                series_dir / "series_2" / "series_2_records.csv",
            )

            scraper = PixivNovelScraper(base_dir=root)
            scraper.novels_dir = str(root / "custom-novels")
            self.assertEqual(
                Path(scraper.build_novel_output_dir("9")),
                root / "custom-novels" / "novel_9",
            )

    def test_existing_cover_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            self.assertIsNone(find_existing_cover(work_dir))
            cover = work_dir / "cover.webp"
            cover.write_bytes(b"image")
            self.assertEqual(Path(find_existing_cover(work_dir)), cover)


if __name__ == "__main__":
    unittest.main()
