"""单章小说响应与封面、正文插图的解析和本地化。"""

import logging
import os
import re

from requests import exceptions as requests_exceptions

from .endpoints import illustration_detail_url
from .parsing import clean_html
from .paths import build_cover_file, find_existing_cover


LOGGER = logging.getLogger("pixiv_novel_toolkit")
PIXIV_IMAGE_RE = re.compile(r"\[pixivimage:(\d+)\]")
SUPPORTED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def select_cover_url(overview):
    """按清晰度回退链选择系列封面 URL。"""
    cover = overview.get("cover") or {}
    urls = cover.get("urls") or {}
    return (
        urls.get("original")
        or urls.get("480mw")
        or urls.get("1200x1200")
        or urls.get("240x480")
    )


def cover_extension(cover_url):
    """从封面 URL 提取受支持的扩展名，无法判断时回退 JPG。"""
    extension = os.path.splitext(cover_url.split("?")[0])[1].lower()
    return extension if extension in SUPPORTED_COVER_EXTENSIONS else ".jpg"


def save_series_cover(
    overview,
    work_dir,
    download_image,
    *,
    build_cover_path=None,
    log=None,
):
    """按回退链保存系列封面；已有封面时直接返回其路径。"""
    log = log or LOGGER
    cover_url = select_cover_url(overview)
    if not cover_url:
        log.info("Series overview has no cover image.")
        return None

    existing = find_existing_cover(work_dir)
    if existing:
        log.info(f"Cover image already exists. Skipping download: {existing}")
        return existing

    build_cover_path = build_cover_path or build_cover_file
    cover_file = build_cover_path(work_dir, cover_extension(cover_url))
    log.info(f"Downloading series cover image: {cover_url}")
    if download_image(cover_url, cover_file):
        log.info(f"Cover image saved: {cover_file}")
        return cover_file
    log.warning("Cover image download failed.")
    return None


def parse_novel_payload(data):
    """从成功的小说接口响应提取下载阶段所需字段。"""
    body = data["body"]
    content = body["content"]
    raw_time = body.get("createDate", "未知时间")
    return {
        "title": body["title"],
        "content": content.replace("[newpage]", "\n\n"),
        "description": clean_html(body.get("description", "")),
        "formatted_time": (
            raw_time.replace("T", " ")[:19] if raw_time != "未知时间" else raw_time
        ),
        "word_count": body.get("textCount", len(content)),
        "embedded_images": body.get("textEmbeddedImages") or {},
    }


def _image_suffix(image_url):
    """沿用旧下载器的正文插图后缀提取规则。"""
    return image_url.split(".")[-1]


def localize_embedded_images(
    content,
    embedded_images,
    chapter_num,
    image_folder,
    download_image,
    *,
    log=None,
):
    """下载作者上传插图，并把成功项替换为本地插图标记。"""
    log = log or LOGGER
    for image_id, image_info in embedded_images.items():
        image_url = image_info["urls"]["original"]
        image_name = f"ch{chapter_num}_up_{image_id}.{_image_suffix(image_url)}"
        log.info(f"  Embedded illustration detected. Downloading: {image_name}")
        if download_image(image_url, os.path.join(image_folder, image_name)):
            content = content.replace(
                f"[uploadedimage:{image_id}]",
                f"\n\n【插图: {image_name}】\n\n",
            )
    return content


def localize_referenced_images(
    content,
    chapter_num,
    image_folder,
    request_json,
    download_image,
    *,
    log=None,
):
    """解析站内插图引用，下载原图并将标记替换为本地提示。"""
    log = log or LOGGER
    image_ids = PIXIV_IMAGE_RE.findall(content)
    for image_id in image_ids:
        log.info(
            f"  Referenced Pixiv illustration detected. Resolving ID: {image_id}..."
        )
        api_url = illustration_detail_url(image_id)
        try:
            response = request_json(
                api_url,
                timeout=20,
                purpose="illustration metadata request",
            )
        except requests_exceptions.RequestException as exc:
            log.warning(f"    Failed to resolve referenced illustration metadata: {exc}")
            content = content.replace(
                f"[pixivimage:{image_id}]",
                f"\n\n【插图获取失败: 原图 {image_id} 请求超时或网络异常】\n\n",
            )
            continue
        except ValueError as exc:
            log.warning(f"    Failed to parse referenced illustration metadata: {exc}")
            content = content.replace(
                f"[pixivimage:{image_id}]",
                f"\n\n【插图获取失败: 原图 {image_id} 返回数据异常】\n\n",
            )
            continue

        if not response.get("error"):
            image_url = response["body"]["urls"]["original"]
            image_name = f"ch{chapter_num}_pid_{image_id}.{_image_suffix(image_url)}"
            if download_image(image_url, os.path.join(image_folder, image_name)):
                content = content.replace(
                    f"[pixivimage:{image_id}]",
                    f"\n\n【插图: {image_name}】\n\n",
                )
        else:
            log.warning(
                "    Failed to resolve referenced illustration. "
                "The original image may have been removed."
            )
            content = content.replace(
                f"[pixivimage:{image_id}]",
                f"\n\n【插图失效: 原图 {image_id} 已删除】\n\n",
            )
    return content
