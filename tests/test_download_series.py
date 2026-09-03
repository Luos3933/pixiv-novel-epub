import tempfile
import unittest
from pathlib import Path

from pixiv_novel_scraper import PixivNovelScraper
from pixiv_novel_toolkit.downloads.indexes import load_record_rows
from pixiv_novel_toolkit.downloads.series import (
    build_series_tasks,
    collect_series_page,
    extract_series_contents,
    initial_series_metadata,
    merge_series_page_metadata,
    next_series_cursor,
    normalize_series_update_time,
    parse_series_overview,
    render_series_info,
)


class DownloadSeriesTests(unittest.TestCase):
    def test_extract_series_contents_supports_both_response_shapes(self):
        direct = {"body": {"seriesContents": [{"id": "1"}]}}
        nested = {"body": {"page": {"seriesContents": [{"id": "2"}]}}}
        self.assertEqual(extract_series_contents(direct), [{"id": "1"}])
        self.assertEqual(extract_series_contents(nested), [{"id": "2"}])
        self.assertEqual(extract_series_contents({"body": {}}), [])

    def test_next_cursor_prefers_remote_order(self):
        self.assertEqual(next_series_cursor([{"order": 57}], 30, 30), 57)
        self.assertEqual(next_series_cursor([{"id": "1"}], 30, 30), 60)

    def test_overview_metadata_and_info_rendering(self):
        metadata = parse_series_overview(
            {
                "seriesTitle": "系列标题",
                "user": {"name": "作者"},
                "caption": "<b>简介&amp;</b>",
                "publishedDate": "2026-01-02T03:04:05+09:00",
                "tags": {"tags": [{"tag": "奇幻"}]},
            },
            "99",
        )
        metadata["word_count"] = 100
        metadata["chapter_count"] = 2
        metadata["update_time"] = normalize_series_update_time(metadata["update_time"])
        rendered = render_series_info("99", metadata)
        self.assertIn("系列名称: 系列标题", rendered)
        self.assertIn("作者: 作者", rendered)
        self.assertIn("更新时间: 2026-01-02 03:04:05", rendered)
        self.assertIn("标签: 奇幻", rendered)
        self.assertTrue(rendered.endswith("简介&"))

    def test_page_metadata_fills_only_when_overview_title_is_missing(self):
        page = {
            "body": {
                "title": "分页标题",
                "caption": "分页简介",
            }
        }
        contents = [
            {
                "id": "1",
                "userName": "分页作者",
                "createDate": "2026-02-01T00:00:00",
                "tags": ["连载"],
                "textCount": 12,
            }
        ]
        merged = merge_series_page_metadata(
            initial_series_metadata("99"), page, contents, "99"
        )
        self.assertEqual(merged["title"], "分页标题")
        self.assertEqual(merged["author"], "分页作者")
        self.assertEqual(merged["description"], "分页简介")
        self.assertEqual(collect_series_page(contents), (["1"], 12))

        known = initial_series_metadata("99")
        known["title"] = "总览标题"
        self.assertEqual(
            merge_series_page_metadata(known, page, contents, "99")["author"],
            "",
        )

    def test_build_series_tasks_can_renumber_or_preserve_positions(self):
        ids = ["novel-a", "novel-b"]
        positions = [11, 12]
        self.assertEqual(
            build_series_tasks(ids, positions, 3),
            [("003", "novel-a"), ("004", "novel-b")],
        )
        self.assertEqual(
            build_series_tasks(ids, positions, 3, preserve_positions=True),
            [("011", "novel-a"), ("012", "novel-b")],
        )

    def test_index_only_series_flow_keeps_original_public_entrypoint(self):
        class FakeScraper(PixivNovelScraper):
            def fetch_series_overview(self, series_id):
                return {
                    "title": "测试系列",
                    "userName": "作者",
                    "caption": "<b>简介</b>",
                    "tags": {"tags": [{"tag": "测试"}]},
                }

            def download_series_cover(self, series_id, overview):
                return None

            def request_json(self, url, **kwargs):
                return {
                    "body": {
                        "seriesContents": [
                            {"id": "novel-1", "order": 1, "textCount": 10},
                            {"id": "novel-2", "order": 2, "textCount": 20},
                            {"id": "novel-3", "order": 3, "textCount": 30},
                        ]
                    }
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = FakeScraper(base_dir=temp_dir)
            result = scraper.download_series(
                "99",
                only_update_csv=True,
                chapter_selection="2-3",
            )

            record_file = Path(scraper.build_record_file("series", "99"))
            self.assertTrue(result)
            self.assertEqual(
                load_record_rows(record_file),
                [["002", "novel-2"], ["003", "novel-3"]],
            )
            info_text = Path(scraper.build_series_info_file("99")).read_text(encoding="utf-8")
            self.assertIn("系列名称: 测试系列", info_text)
            self.assertIn("总字数: 60", info_text)


if __name__ == "__main__":
    unittest.main()
