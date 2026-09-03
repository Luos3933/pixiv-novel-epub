"""
Pixiv 小说下载工具。

功能概览：
- 支持按单章下载小说正文。
- 支持根据 CSV 记录批量下载多章内容。
- 支持解析系列并自动下载全部章节。
- 支持下载正文中引用或嵌入的插图，并在文本中替换为本地文件标记。
"""

import logging
import time

import requests

from pixiv_novel_toolkit import __version__
from pixiv_novel_toolkit.downloads import (
    build_chapters_dir as make_chapters_dir,
    build_cover_file as make_cover_file,
    build_images_dir as make_images_dir,
    build_metadata_file as make_metadata_file,
    build_novel_output_dir as make_novel_output_dir,
    build_record_file as make_record_file,
    build_series_catalog_file as make_series_catalog_file,
    build_series_info_file as make_series_info_file,
    build_series_output_dir as make_series_output_dir,
    build_series_tasks,
    build_summary_file as make_summary_file,
    chapter_file_exists as has_chapter_file,
    build_request_headers,
    clean_filename,
    clean_html,
    DEFAULT_CHAPTER_DELAY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRY_DELAY,
    decode_json_response,
    extract_tag_names,
    ensure_directory,
    execute_batch_tasks,
    execute_series_tasks,
    fetch_and_save_novel,
    fetch_series_catalog,
    fetch_series_overview as request_series_overview,
    find_missing_records,
    initial_series_metadata,
    load_cookie_file,
    load_record_rows,
    normalize_chapter_number,
    normalize_series_update_time,
    NovelApiError,
    parse_chapter_selection,
    parse_series_overview,
    regenerate_summary,
    record_rows_to_tasks,
    render_series_info,
    request_with_retry as perform_request_with_retry,
    save_chapter_record,
    save_metadata_record,
    save_series_cover,
    SeriesApiError,
    sum_word_count_from_metadata,
    update_series_catalog,
    unresolved_chapter_numbers,
    write_stream_response,
)
from pixiv_novel_toolkit.downloads.scraper import (
    PixivNovelScraper as _PackagePixivNovelScraper,
)

logger = logging.getLogger("pixiv_novel_toolkit")


class PixivNovelScraper(_PackagePixivNovelScraper):
    """旧模块兼容类；保留 requests.get 的历史补丁入口。"""

    def request_with_retry(self, url, *, stream=False, timeout=None, purpose="request"):
        return perform_request_with_retry(
            url,
            headers=self.headers,
            stream=stream,
            timeout=timeout or self.request_timeout,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            purpose=purpose,
            request_get=requests.get,
            sleep=time.sleep,
            log=logger,
        )


if __name__ == "__main__":
    # 库文件不直接包含交互逻辑，交由 cli.py 统一入口处理（懒导入避免循环依赖）。
    # 直接运行 `python pixiv_novel_scraper.py` 与 `python cli.py` 行为一致。
    from cli import main
    main()
