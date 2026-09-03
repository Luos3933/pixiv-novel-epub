import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.batch import (
    execute_batch_tasks,
    find_missing_records,
    record_rows_to_tasks,
    unresolved_chapter_numbers,
)


class DownloadBatchTests(unittest.TestCase):
    def test_shared_batch_helpers_preserve_order_and_count(self):
        tasks = record_rows_to_tasks([[" 002 ", " b "], ["001", "a"]])
        self.assertEqual(tasks, [("002", "b"), ("001", "a")])

        existing = {"001"}
        self.assertEqual(
            find_missing_records(tasks, lambda number: number in existing),
            [("002", "b")],
        )
        result = execute_batch_tasks(tasks, lambda task: task[1] == "a")
        self.assertEqual((result.successful, result.total), (1, 2))
        self.assertEqual(
            unresolved_chapter_numbers(tasks, lambda number: number in existing),
            ["002"],
        )

    def test_csv_entrypoint_builds_per_novel_targets(self):
        class FakeScraper(PixivNovelScraper):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.calls = []

            def download_novel(self, novel_id, chapter_num, **kwargs):
                self.calls.append((novel_id, chapter_num, kwargs))
                return novel_id == "100"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "import.csv"
            source.write_text("1,100\ninvalid\n2,200\n", encoding="utf-8")
            scraper = FakeScraper(base_dir=root)

            with self.assertLogs("pixiv_novel_toolkit", level="INFO") as logs:
                scraper.download_from_csv(source, force=True)

            self.assertEqual([(call[0], call[1]) for call in scraper.calls], [("100", "1"), ("200", "2")])
            self.assertTrue(all(call[2]["force"] for call in scraper.calls))
            self.assertTrue(
                scraper.calls[0][2]["output_folder"].endswith("novels\\novel_100")
                or scraper.calls[0][2]["output_folder"].endswith("novels/novel_100")
            )
            self.assertIn("Successful chapters: 1/2", "\n".join(logs.output))

    def test_retry_entrypoints_find_and_recover_only_missing_chapter(self):
        class FakeScraper(PixivNovelScraper):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.calls = []

            def download_novel(self, novel_id, chapter_num, output_folder=None, **kwargs):
                self.calls.append((novel_id, chapter_num, kwargs.get("force")))
                chapters_dir = Path(self.build_chapters_dir(output_folder))
                chapters_dir.mkdir(parents=True, exist_ok=True)
                (chapters_dir / f"{int(chapter_num):03d} recovered.txt").write_text(
                    "正文", encoding="utf-8"
                )
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(base_dir=temp_dir)
            work_dir = Path(scraper.build_series_output_dir("99"))
            chapters_dir = Path(scraper.build_chapters_dir(work_dir))
            chapters_dir.mkdir(parents=True)
            (chapters_dir / "001 existing.txt").write_text("正文", encoding="utf-8")
            record_file = Path(scraper.build_record_file("series", "99"))
            record_file.write_text("001,100\n002,200\n", encoding="utf-8")

            self.assertEqual(scraper.find_missing_chapters("series", "99"), [("002", "200")])
            scraper.download_missing("series", "99", force=True)

            self.assertEqual(scraper.calls, [("200", "002", True)])
            self.assertEqual(scraper.find_missing_chapters("series", "99"), [])


if __name__ == "__main__":
    unittest.main()
