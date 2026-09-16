import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from pixiv_novel_toolkit.quick import (
    _book_output_stem,
    _resolve_epub_styles,
    build_series_book,
)


class FakeScraper:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.calls = []

    def build_series_output_dir(self, series_id):
        return str(self.base_dir / "series" / f"series_{series_id}")

    @staticmethod
    def build_chapters_dir(work_dir):
        return str(Path(work_dir) / "chapters")

    def download_series(self, series_id, *, force=False, workers=1):
        self.calls.append((series_id, force, workers))
        work_dir = Path(self.build_series_output_dir(series_id))
        chapters = work_dir / "chapters"
        chapters.mkdir(parents=True)
        (chapters / "001 开始.txt").write_text("正文一", encoding="utf-8")
        (chapters / "002 继续.txt").write_text("正文二", encoding="utf-8")
        (work_dir / f"series_{series_id}_info.txt").write_text(
            "系列ID: 99\n系列名称: 快速测试书\n作者: 测试作者\n"
            "更新时间: 2026-09-16 12:00:00\n总字数: 6\n"
            "章节数: 2\n标签: 测试\n简介:\n测试简介\n",
            encoding="utf-8",
        )
        return True


class QuickBuildTests(unittest.TestCase):
    def test_build_series_book_runs_default_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(temp_dir)

            result = build_series_book(
                scraper,
                "pixiv.net/novel/series/99",
                force=True,
                workers=3,
            )

            self.assertIsNotNone(result)
            self.assertEqual(scraper.calls, [("99", True, 3)])
            self.assertTrue(Path(result.standardized_dir).is_dir())
            self.assertTrue(Path(result.corrected_dir).is_dir())
            self.assertTrue(Path(result.txt_file).is_file())
            self.assertTrue(Path(result.epub_file).is_file())
            self.assertEqual(Path(result.txt_file).name, "快速测试书.txt")
            self.assertEqual(Path(result.epub_file).name, "快速测试书.epub")
            self.assertIn("快速测试书", Path(result.txt_file).read_text(encoding="utf-8"))
            with zipfile.ZipFile(result.epub_file) as archive:
                self.assertIn("OEBPS/chap_001.xhtml", archive.namelist())
                self.assertIn("OEBPS/chap_002.xhtml", archive.namelist())

    def test_build_series_book_applies_volume_maker_and_style_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(temp_dir)
            volumes_file = Path(temp_dir) / "volumes.json"
            volumes_file.write_text(
                json.dumps(
                    [{"name": "第一卷 开端", "start": 1, "end": 2}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_series_book(
                scraper,
                "99",
                volumes_file=str(volumes_file),
                maker="测试制作人",
                indent=True,
                title_style_name="split_title",
                vol_style_name="default",
                title_align="left",
            )

            self.assertIsNotNone(result)
            merged = Path(result.txt_file).read_text(encoding="utf-8")
            self.assertIn("TXT制作：测试制作人", merged)
            self.assertIn("第一卷 开端", merged)
            with zipfile.ZipFile(result.epub_file) as archive:
                self.assertIn("OEBPS/vol_1.xhtml", archive.namelist())
                book_info = archive.read("OEBPS/book_info.xhtml").decode("utf-8")
                stylesheet = archive.read("OEBPS/style.css").decode("utf-8")
                self.assertIn("EPUB制作：测试制作人", book_info)
                self.assertIn("text-align: left", stylesheet)
                self.assertIn(".chapter-num", stylesheet)

    def test_build_series_book_stops_after_download_failure(self):
        class FailingScraper:
            @staticmethod
            def build_series_output_dir(series_id):
                return "unused"

            @staticmethod
            def build_chapters_dir(work_dir):
                return "unused/chapters"

            @staticmethod
            def download_series(series_id, *, force=False, workers=1):
                return False

        self.assertIsNone(build_series_book(FailingScraper(), "99"))

    def test_book_output_stem_sanitizes_book_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info_file = Path(temp_dir) / "000 书籍信息.txt"
            info_file.write_text(
                "【书籍信息】\n测试：书名? / 第一部\n作者：测试\n",
                encoding="utf-8",
            )

            self.assertEqual(_book_output_stem(temp_dir), "测试：书名 第一部")

    def test_book_output_stem_falls_back_for_missing_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info_file = Path(temp_dir) / "000 书籍信息.txt"
            info_file.write_text(
                "【书籍信息】\n未填\n作者：未填\n",
                encoding="utf-8",
            )

            self.assertEqual(_book_output_stem(temp_dir), "全书")

    def test_resolve_epub_styles_rejects_unknown_preset(self):
        self.assertIsNone(_resolve_epub_styles(title_style_name="不存在的样式"))


if __name__ == "__main__":
    unittest.main()
