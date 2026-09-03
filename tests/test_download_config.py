import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.scraper import PixivNovelScraper as PackageScraper
from pixiv_novel_toolkit.downloads.config import (
    DEFAULT_CHAPTER_DELAY,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRY_DELAY,
    build_request_headers,
    load_cookie_file,
)


class DownloadConfigTests(unittest.TestCase):
    def test_legacy_scraper_subclasses_package_implementation(self):
        self.assertTrue(issubclass(PixivNovelScraper, PackageScraper))

    def test_headers_are_independent_and_cookie_is_optional(self):
        anonymous = build_request_headers()
        authenticated = build_request_headers("session=value")
        self.assertNotIn("Cookie", anonymous)
        self.assertEqual(authenticated["Cookie"], "session=value")
        authenticated["Referer"] = "changed"
        self.assertEqual(DEFAULT_HEADERS["Referer"], "https://www.pixiv.net/")
        self.assertEqual(anonymous["Referer"], "https://www.pixiv.net/")

    def test_cookie_reader_trims_content_and_warns_only_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "cookie.txt"
            warnings = []
            self.assertEqual(load_cookie_file(cookie_file, warn=warnings.append), "")
            self.assertEqual(len(warnings), 1)

            cookie_file.write_text("  a=b; c=d\n", encoding="utf-8")
            warnings.clear()
            self.assertEqual(load_cookie_file(cookie_file, warn=warnings.append), "a=b; c=d")
            self.assertEqual(warnings, [])

    def test_scraper_keeps_public_mutable_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = PixivNovelScraper(cookie="session=value", base_dir=temp_dir)
            self.assertEqual(scraper.request_timeout, DEFAULT_REQUEST_TIMEOUT)
            self.assertEqual(scraper.max_retries, DEFAULT_MAX_RETRIES)
            self.assertEqual(scraper.retry_delay, DEFAULT_RETRY_DELAY)
            self.assertEqual(scraper.chapter_delay, DEFAULT_CHAPTER_DELAY)
            self.assertEqual(scraper.headers["Cookie"], "session=value")

            scraper.request_timeout = 99
            scraper.headers["X-Test"] = "yes"
            self.assertEqual(scraper.request_timeout, 99)
            self.assertEqual(scraper.headers["X-Test"], "yes")

    def test_legacy_cookie_method_delegates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "cookie.txt"
            cookie_file.write_text("legacy=cookie", encoding="utf-8")
            scraper = PixivNovelScraper(base_dir=temp_dir)
            self.assertEqual(scraper.load_cookie_from_file(cookie_file), "legacy=cookie")


if __name__ == "__main__":
    unittest.main()
