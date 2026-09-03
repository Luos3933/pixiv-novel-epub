import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.novel_flow import (
    NovelApiError,
    fetch_and_save_novel,
)


class DownloadNovelFlowTests(unittest.TestCase):
    def test_flow_fetches_media_writes_text_and_returns_index_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            images = root / "images"
            chapters.mkdir()
            images.mkdir()
            requests = []

            def request_json(url, **kwargs):
                requests.append((url, kwargs))
                if "/illust/" in url:
                    return {"body": {"urls": {"original": "https://img.test/ref.jpg"}}}
                return {
                    "body": {
                        "title": "标题:一",
                        "content": "A[newpage][uploadedimage:7][pixivimage:8]",
                        "description": "<b>简介</b>",
                        "createDate": "2026-01-02T03:04:05+09:00",
                        "textCount": 50,
                        "textEmbeddedImages": {
                            "7": {"urls": {"original": "https://img.test/up.png"}}
                        },
                    }
                }

            def download_image(url, path):
                Path(path).write_bytes(b"image")
                return True

            result = fetch_and_save_novel(
                "123",
                "004",
                chapters,
                images,
                request_json,
                download_image,
            )

            self.assertEqual(Path(result.filepath).name, "004 标题_一.txt")
            self.assertEqual(result.title, "标题:一")
            self.assertEqual(result.formatted_time, "2026-01-02 03:04:05")
            self.assertEqual(result.word_count, 50)
            content = Path(result.filepath).read_text(encoding="utf-8")
            self.assertIn("【插图: ch004_up_7.png】", content)
            self.assertIn("【插图: ch004_pid_8.jpg】", content)
            self.assertTrue(requests[0][0].endswith("/ajax/novel/123"))

    def test_flow_raises_distinct_api_error_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(NovelApiError, "作品不可用"):
                fetch_and_save_novel(
                    "123",
                    "001",
                    root,
                    root,
                    lambda *args, **kwargs: {"error": True, "message": "作品不可用"},
                    lambda *args: True,
                )
            self.assertEqual(list(root.glob("*.txt")), [])

    def test_legacy_method_converts_api_error_to_false(self):
        class FakeScraper(PixivNovelScraper):
            def request_json(self, url, **kwargs):
                return {"error": True, "message": "作品不可用"}

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(base_dir=temp_dir)
            self.assertFalse(scraper.download_novel("123", "001"))
            self.assertFalse(Path(scraper.build_record_file("novel", "123")).exists())


if __name__ == "__main__":
    unittest.main()
