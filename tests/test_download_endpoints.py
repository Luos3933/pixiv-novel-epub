import unittest

from pixiv_novel_toolkit.downloads.endpoints import (
    illustration_detail_url,
    novel_detail_url,
    series_content_url,
    series_overview_url,
)
from pixiv_novel_toolkit.downloads.series_flow import fetch_series_overview


class DownloadEndpointTests(unittest.TestCase):
    def test_endpoint_urls_preserve_existing_contract(self):
        self.assertEqual(
            novel_detail_url("123"),
            "https://www.pixiv.net/ajax/novel/123",
        )
        self.assertEqual(
            illustration_detail_url("456"),
            "https://www.pixiv.net/ajax/illust/456",
        )
        self.assertEqual(
            series_overview_url("789"),
            "https://www.pixiv.net/ajax/novel/series/789?lang=zh",
        )
        self.assertEqual(
            series_content_url("789", 30, 57),
            "https://www.pixiv.net/ajax/novel/series_content/789"
            "?limit=30&last_order=57&order_by=asc&lang=zh",
        )

    def test_series_overview_request_and_error_handling(self):
        calls = []

        def request_json(url, **kwargs):
            calls.append((url, kwargs))
            return {"body": {"title": "系列"}}

        self.assertEqual(fetch_series_overview("9", request_json), {"title": "系列"})
        self.assertEqual(calls[0][1]["timeout"], 25)
        self.assertEqual(calls[0][1]["purpose"], "series overview request")

        with self.assertRaisesRegex(ValueError, "Failed to fetch series overview"):
            fetch_series_overview("9", lambda *args, **kwargs: {"error": True})


if __name__ == "__main__":
    unittest.main()
