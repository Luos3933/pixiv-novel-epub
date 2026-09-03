"""EPUB 插图信息文件解析。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from os import PathLike


ILLUSTRATION_MARKER_RE = re.compile(r"【插图[:：]\s*([^】]+)】")
LogCallback = Callable[[str], None] | None


def _emit(callback: LogCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def parse_illustrations_text(
    content: str,
    *,
    warning: LogCallback = None,
) -> dict[str, list[dict]]:
    """解析带章节头与 ``【插图: 文件名】`` 标记的文本格式。"""
    entries = {}
    current_chapter = None
    current_entry = None

    def store(entry):
        if not entry["chapter"]:
            _emit(warning, f"插图条目无法确定归属章节，已跳过: {entry['img']}")
            return
        entries.setdefault(entry["chapter"], []).append(
            {"img": entry["img"], "desc": entry["desc"]}
        )

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        chapter_match = re.match(r"^(\d{3})(?:\s|$)", stripped)
        if chapter_match:
            current_chapter = chapter_match.group(1)
            current_entry = None
            continue
        marker_match = ILLUSTRATION_MARKER_RE.fullmatch(stripped)
        if marker_match:
            if current_entry is not None:
                store(current_entry)
            image_name = marker_match.group(1).strip()
            filename_chapter = re.search(r"ch(\d+)", image_name, re.IGNORECASE)
            chapter = filename_chapter.group(1) if filename_chapter else current_chapter
            current_entry = {"img": image_name, "chapter": chapter, "desc": []}
            continue
        if current_entry is not None:
            current_entry["desc"].append(stripped)
    if current_entry is not None:
        store(current_entry)
    return entries


def parse_illustrations_json(
    data,
    *,
    warning: LogCallback = None,
) -> dict[str, list[dict]]:
    """解析严格的 JSON 数组插图格式。"""
    entries = {}
    if not isinstance(data, list):
        _emit(warning, '插图信息 JSON 应为数组 [{"chapter": 1, "img": "..."}, ...]')
        return entries
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not item.get("img"):
            _emit(warning, f"插图信息 JSON 第 {index} 条无效（缺少 img），已跳过: {item}")
            continue
        image_name = str(item["img"]).strip()
        filename_chapter = re.search(r"ch(\d+)", image_name, re.IGNORECASE)
        chapter = filename_chapter.group(1) if filename_chapter else None
        if "chapter" in item:
            try:
                chapter = f"{int(item['chapter']):03d}"
            except (TypeError, ValueError):
                chapter = None
        if not chapter:
            _emit(
                warning,
                f"插图信息 JSON 第 {index} 条无法确定归属章节，已跳过: {image_name}",
            )
            continue
        description = [
            line.strip() for line in str(item.get("desc") or "").splitlines() if line.strip()
        ]
        entries.setdefault(chapter, []).append({"img": image_name, "desc": description})
    return entries


def parse_illustrations_file(
    path: str | PathLike[str],
    *,
    warning: LogCallback = None,
    info: LogCallback = None,
) -> dict[str, list[dict]]:
    """按首个非空字符自动识别 JSON 或文本插图信息文件。"""
    with open(path, "r", encoding="utf-8-sig") as file:
        content = file.read()
    stripped = content.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            _emit(warning, f"插图信息文件 {path} 解析 JSON 失败，已按 txt 格式处理")
            return parse_illustrations_text(content, warning=warning)
        _emit(info, "插图信息文件格式: JSON")
        return parse_illustrations_json(data, warning=warning)
    return parse_illustrations_text(content, warning=warning)

