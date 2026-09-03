"""系列目录分页获取与下载任务执行。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .endpoints import series_content_url, series_overview_url
from .series import (
    collect_series_page,
    extract_series_contents,
    merge_series_page_metadata,
    next_series_cursor,
)


class SeriesApiError(Exception):
    """系列接口明确返回 ``error=true``。"""


@dataclass
class SeriesCatalog:
    """完整系列分页抓取后的目录与聚合信息。"""

    chapter_ids: list
    word_count: int
    metadata: dict


def fetch_series_overview(series_id, request_json):
    """请求独立系列总览，并沿用旧版错误与 body 回退规则。"""
    data = request_json(
        series_overview_url(series_id),
        timeout=25,
        purpose="series overview request",
    )
    if data.get("error"):
        raise ValueError(data.get("message") or "Failed to fetch series overview")
    return data.get("body", {}) or {}


def fetch_series_catalog(series_id, request_json, metadata, page_limit=30):
    """遍历 Pixiv 系列分页接口并聚合章节、字数与回退元数据。"""
    chapter_ids = []
    word_count = 0
    current_metadata = dict(metadata)
    last_order = 0

    while True:
        api_url = series_content_url(series_id, page_limit, last_order)
        data = request_json(
            api_url,
            timeout=25,
            purpose="series metadata request",
        )
        if data.get("error"):
            raise SeriesApiError(data.get("message"))

        contents = extract_series_contents(data)
        if not contents:
            break

        page_ids, page_word_count = collect_series_page(contents)
        chapter_ids.extend(page_ids)
        word_count += page_word_count
        current_metadata = merge_series_page_metadata(
            current_metadata,
            data,
            contents,
            series_id,
        )

        if len(contents) < page_limit:
            break
        last_order = next_series_cursor(contents, last_order, page_limit)

    return SeriesCatalog(chapter_ids, word_count, current_metadata)


def execute_series_tasks(
    tasks,
    process_task,
    *,
    workers=1,
    index_only=False,
    progress=None,
):
    """串行或并发执行系列任务，返回回调结果为真时的成功数量。"""
    if index_only or workers <= 1:
        iterator = progress(tasks, desc="Series", unit="chap") if progress else tasks
        return sum(1 for task in iterator if process_task(task))

    success_count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_task, task): task for task in tasks}
        completed = as_completed(futures)
        if progress:
            completed = progress(
                completed,
                total=len(futures),
                desc=f"Series(x{workers})",
                unit="chap",
            )
        for future in completed:
            if future.result():
                success_count += 1
    return success_count
