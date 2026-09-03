import unittest

from pixiv_novel_toolkit.downloads.series import initial_series_metadata
from pixiv_novel_toolkit.downloads.series_flow import (
    SeriesApiError,
    execute_series_tasks,
    fetch_series_catalog,
)


class DownloadSeriesFlowTests(unittest.TestCase):
    def test_fetch_catalog_follows_remote_cursor_and_aggregates_pages(self):
        urls = []

        def request_json(url, **kwargs):
            urls.append(url)
            self.assertEqual(kwargs["timeout"], 25)
            self.assertEqual(kwargs["purpose"], "series metadata request")
            if "last_order=0" in url:
                return {
                    "body": {
                        "title": "分页系列",
                        "seriesContents": [
                            {"id": "a", "order": 7, "textCount": 10},
                            {"id": "b", "order": 8, "wordCount": 20},
                        ],
                    }
                }
            self.assertIn("last_order=8", url)
            return {
                "body": {
                    "seriesContents": [
                        {"id": "c", "order": 9, "textCount": 30},
                    ]
                }
            }

        result = fetch_series_catalog(
            "99",
            request_json,
            initial_series_metadata("99"),
            page_limit=2,
        )

        self.assertEqual(result.chapter_ids, ["a", "b", "c"])
        self.assertEqual(result.word_count, 60)
        self.assertEqual(result.metadata["title"], "分页系列")
        self.assertEqual(len(urls), 2)

    def test_fetch_catalog_keeps_api_error_distinct(self):
        def request_json(url, **kwargs):
            return {"error": True, "message": "权限不足"}

        with self.assertRaisesRegex(SeriesApiError, "权限不足"):
            fetch_series_catalog("99", request_json, initial_series_metadata("99"))

    def test_task_executor_counts_serial_and_parallel_successes(self):
        progress_calls = []

        def progress(iterable, **kwargs):
            progress_calls.append(kwargs)
            return iterable

        serial_count = execute_series_tasks(
            [1, 2, 3],
            lambda value: value != 2,
            workers=4,
            index_only=True,
            progress=progress,
        )
        self.assertEqual(serial_count, 2)
        self.assertEqual(progress_calls[0]["desc"], "Series")

        parallel_count = execute_series_tasks(
            [1, 2, 3, 4],
            lambda value: value % 2 == 0,
            workers=2,
            progress=progress,
        )
        self.assertEqual(parallel_count, 2)
        self.assertEqual(progress_calls[1]["desc"], "Series(x2)")
        self.assertEqual(progress_calls[1]["total"], 4)

    def test_parallel_task_exception_is_not_swallowed(self):
        def process(value):
            if value == 2:
                raise RuntimeError("task failed")
            return True

        with self.assertRaisesRegex(RuntimeError, "task failed"):
            execute_series_tasks([1, 2], process, workers=2)


if __name__ == "__main__":
    unittest.main()
