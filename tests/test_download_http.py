import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from requests import exceptions as requests_exceptions

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.http import (
    decode_json_response,
    request_with_retry,
    write_stream_response,
)


class FakeResponse:
    def __init__(self, data=None, chunks=()):
        self.data = data
        self.chunks = chunks

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        return iter(self.chunks)


class DownloadHttpTests(unittest.TestCase):
    def test_retry_uses_linear_backoff_and_returns_response(self):
        calls = []
        sleeps = []
        response = FakeResponse({"ok": True})

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            if len(calls) == 1:
                raise requests_exceptions.ConnectionError("temporary")
            return response

        actual = request_with_retry(
            "https://example.test/data",
            headers={"Cookie": "secret"},
            stream=True,
            timeout=9,
            max_retries=3,
            retry_delay=0.5,
            request_get=fake_get,
            sleep=sleeps.append,
        )

        self.assertIs(actual, response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.5])
        self.assertTrue(calls[1][1]["stream"])
        self.assertEqual(calls[1][1]["timeout"], 9)

    def test_json_error_includes_request_purpose(self):
        with self.assertRaisesRegex(ValueError, "novel metadata request"):
            decode_json_response(FakeResponse(ValueError("bad json")), "novel metadata request")

    def test_http_status_error_is_not_retried(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            response = type("ErrorResponse", (), {"status_code": 403})()
            raise requests_exceptions.HTTPError("forbidden", response=response)

        with self.assertRaises(requests_exceptions.HTTPError):
            request_with_retry(
                "https://example.test/forbidden",
                headers={},
                max_retries=3,
                request_get=fake_get,
                sleep=lambda delay: self.fail("HTTP errors must not be retried"),
            )
        self.assertEqual(calls, ["https://example.test/forbidden"])

    def test_stream_writer_skips_empty_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "image.bin"
            response = FakeResponse(chunks=[b"ab", b"", b"cd"])
            write_stream_response(response, output)
            self.assertEqual(output.read_bytes(), b"abcd")
            self.assertEqual(response.chunk_size, 1024)

    def test_scraper_method_delegates_and_keeps_requests_patch_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = PixivNovelScraper(base_dir=temp_dir)
            scraper.retry_delay = 0
            response = FakeResponse({"body": {}})
            with patch("pixiv_novel_scraper.requests.get", return_value=response) as mocked_get:
                self.assertEqual(scraper.request_json("https://example.test"), {"body": {}})
            mocked_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
