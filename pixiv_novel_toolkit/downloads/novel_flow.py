"""单章小说请求、媒体本地化与正文落盘流程。"""

import logging
import os
from dataclasses import dataclass

from .endpoints import novel_detail_url
from .novel import (
    localize_embedded_images,
    localize_referenced_images,
    parse_novel_payload,
)
from .parsing import clean_filename


LOGGER = logging.getLogger("pixiv_novel_toolkit")


class NovelApiError(Exception):
    """小说接口明确返回 ``error=true``。"""


@dataclass
class DownloadedNovel:
    """单章落盘后供索引更新使用的结果。"""

    filepath: str
    title: str
    formatted_time: str
    word_count: object
    description: str


def fetch_and_save_novel(
    novel_id,
    chapter_num,
    chapters_dir,
    image_folder,
    request_json,
    download_image,
    *,
    log=None,
):
    """请求单章、处理两类插图标记并以旧命名规则保存正文。"""
    log = log or LOGGER
    data = request_json(
        novel_detail_url(novel_id),
        timeout=25,
        purpose="novel metadata request",
    )
    if data.get("error"):
        raise NovelApiError(data.get("message"))

    novel = parse_novel_payload(data)
    content = localize_embedded_images(
        novel["content"],
        novel["embedded_images"],
        chapter_num,
        image_folder,
        download_image,
        log=log,
    )
    content = localize_referenced_images(
        content,
        chapter_num,
        image_folder,
        request_json,
        download_image,
        log=log,
    )

    safe_title = clean_filename(novel["title"])
    filepath = os.path.join(chapters_dir, f"{chapter_num} {safe_title}.txt")
    with open(filepath, "w", encoding="utf-8") as file_obj:
        file_obj.write(content)

    return DownloadedNovel(
        filepath=filepath,
        title=novel["title"],
        formatted_time=novel["formatted_time"],
        word_count=novel["word_count"],
        description=novel["description"],
    )
