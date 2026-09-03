import csv
import json
import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.indexes import (
    load_record_rows,
    regenerate_summary,
    save_chapter_record,
    save_metadata_record,
    sum_word_count_from_metadata,
    update_series_catalog,
)


class DownloadIndexTests(unittest.TestCase):
    def test_chapter_records_are_merged_and_sorted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            record_file = Path(temp_dir) / "records.csv"
            record_file.write_text("003,old-3\ninvalid,row\n001,old-1\n", encoding="utf-8")

            save_chapter_record("2", "new-2", record_file)

            self.assertEqual(
                load_record_rows(record_file),
                [["001", "old-1"], ["002", "new-2"], ["003", "old-3"]],
            )

    def test_metadata_is_truth_source_for_summary_and_word_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_file = root / "metadata.json"
            summary_file = root / "summary.txt"

            save_metadata_record(2, "第二章", "2026-01-02", 20, "", metadata_file)
            save_metadata_record(1, "第一章", "2026-01-01", 10.9, "简介", metadata_file)
            regenerate_summary(metadata_file, summary_file)

            records = json.loads(metadata_file.read_text(encoding="utf-8"))
            self.assertEqual(records["002"]["desc"], "（本章无简介或留言）")
            self.assertEqual(sum_word_count_from_metadata(metadata_file), 30)
            summary = summary_file.read_text(encoding="utf-8")
            self.assertLess(summary.index("001 第一章"), summary.index("002 第二章"))

    def test_series_catalog_updates_existing_id_and_sorts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_file = Path(temp_dir) / "catalog.csv"
            catalog_file.write_text("20,旧系列\n3,第三系列\n", encoding="utf-8")

            update_series_catalog(catalog_file, "20", "新系列")

            with catalog_file.open("r", encoding="utf-8") as file_obj:
                self.assertEqual(
                    list(csv.reader(file_obj)),
                    [["3", "第三系列"], ["20", "新系列"]],
                )

    def test_scraper_compatibility_methods_delegate_to_shared_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = PixivNovelScraper(base_dir=temp_dir)
            metadata_file = Path(temp_dir) / "metadata.json"
            summary_file = Path(temp_dir) / "summary.txt"
            scraper.save_summary_txt(
                1,
                "第一章",
                "2026-01-01",
                12,
                "简介",
                metadata_file,
                summary_file,
            )
            self.assertEqual(scraper._sum_word_count_from_metadata(metadata_file), 12)
            self.assertIn("001 第一章", summary_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
