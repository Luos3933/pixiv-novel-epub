import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.novel import (
    cover_extension,
    localize_embedded_images,
    localize_referenced_images,
    parse_novel_payload,
    save_series_cover,
    select_cover_url,
)


class DownloadNovelTests(unittest.TestCase):
    def test_cover_selection_and_extension_fallback(self):
        overview = {
            "cover": {
                "urls": {
                    "480mw": "https://img.test/cover.PNG?token=1",
                    "240x480": "https://img.test/small.jpg",
                }
            }
        }
        selected = select_cover_url(overview)
        self.assertEqual(selected, "https://img.test/cover.PNG?token=1")
        self.assertEqual(cover_extension(selected), ".png")
        self.assertEqual(cover_extension("https://img.test/no-extension"), ".jpg")

    def test_series_cover_saves_once_and_reuses_existing_file(self):
        overview = {
            "cover": {"urls": {"original": "https://img.test/cover.webp?token=1"}}
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = []

            def download_image(url, path):
                downloads.append((url, path))
                Path(path).write_bytes(b"cover")
                return True

            first = save_series_cover(overview, temp_dir, download_image)
            second = save_series_cover(overview, temp_dir, download_image)
            self.assertEqual(Path(first).name, "cover.webp")
            self.assertEqual(second, first)
            self.assertEqual(len(downloads), 1)

    def test_legacy_cover_method_keeps_overridable_downloader(self):
        class FakeScraper(PixivNovelScraper):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.downloads = []

            def download_image(self, image_url, save_path):
                self.downloads.append((image_url, save_path))
                Path(save_path).write_bytes(b"cover")
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(base_dir=temp_dir)
            Path(scraper.build_series_output_dir("99")).mkdir(parents=True)
            result = scraper.download_series_cover(
                "99",
                {"cover": {"urls": {"480mw": "https://img.test/cover.png"}}},
            )
            self.assertEqual(Path(result).name, "cover.png")
            self.assertEqual(len(scraper.downloads), 1)

    def test_parse_novel_payload_normalizes_fields(self):
        parsed = parse_novel_payload(
            {
                "body": {
                    "title": "标题",
                    "content": "前页[newpage]后页",
                    "description": "<b>简介&amp;</b>",
                    "createDate": "2026-01-02T03:04:05+09:00",
                    "textCount": 123,
                    "textEmbeddedImages": {"7": {"urls": {"original": "x.jpg"}}},
                }
            }
        )
        self.assertEqual(parsed["content"], "前页\n\n后页")
        self.assertEqual(parsed["description"], "简介&")
        self.assertEqual(parsed["formatted_time"], "2026-01-02 03:04:05")
        self.assertEqual(parsed["word_count"], 123)
        self.assertIn("7", parsed["embedded_images"])

    def test_media_localizers_preserve_success_and_failure_markers(self):
        downloads = []

        def download_image(url, path):
            downloads.append((url, Path(path).name))
            return True

        content = localize_embedded_images(
            "A[uploadedimage:7]B",
            {"7": {"urls": {"original": "https://img.test/a.png"}}},
            "003",
            "images",
            download_image,
        )
        self.assertIn("【插图: ch003_up_7.png】", content)

        content += "[pixivimage:10][pixivimage:11][pixivimage:12]"

        def request_json(url, **kwargs):
            if url.endswith("/10"):
                return {"body": {"urls": {"original": "https://img.test/b.jpg"}}}
            if url.endswith("/11"):
                return {"error": True}
            raise ValueError("bad response")

        localized = localize_referenced_images(
            content,
            "003",
            "images",
            request_json,
            download_image,
        )
        self.assertIn("【插图: ch003_pid_10.jpg】", localized)
        self.assertIn("【插图失效: 原图 11 已删除】", localized)
        self.assertIn("【插图获取失败: 原图 12 返回数据异常】", localized)
        self.assertEqual(downloads[0][1], "ch003_up_7.png")
        self.assertEqual(downloads[1][1], "ch003_pid_10.jpg")

    def test_download_novel_keeps_legacy_output_contract(self):
        class FakeScraper(PixivNovelScraper):
            def request_json(self, url, **kwargs):
                if "/illust/" in url:
                    return {"body": {"urls": {"original": "https://img.test/ref.jpg"}}}
                return {
                    "body": {
                        "title": "测试:章节",
                        "content": "正文[newpage][uploadedimage:7][pixivimage:10]",
                        "description": "<b>简介</b>",
                        "createDate": "2026-01-02T03:04:05+09:00",
                        "textCount": 88,
                        "textEmbeddedImages": {
                            "7": {"urls": {"original": "https://img.test/up.png"}}
                        },
                    }
                }

            def download_image(self, image_url, save_path):
                Path(save_path).write_bytes(b"image")
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(base_dir=temp_dir)
            scraper.chapter_delay = 0
            self.assertTrue(
                scraper.download_novel(
                    "pixiv.net/novel/show.php?id=123",
                    "001",
                )
            )

            work_dir = Path(scraper.build_novel_output_dir("123"))
            chapter_file = work_dir / "chapters" / "001 测试_章节.txt"
            content = chapter_file.read_text(encoding="utf-8")
            self.assertIn("【插图: ch001_up_7.png】", content)
            self.assertIn("【插图: ch001_pid_10.jpg】", content)
            self.assertTrue((work_dir / "illustrations" / "ch001_up_7.png").exists())
            self.assertTrue((work_dir / "illustrations" / "ch001_pid_10.jpg").exists())
            self.assertIn(
                "001,123",
                Path(scraper.build_record_file("novel", "123")).read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
