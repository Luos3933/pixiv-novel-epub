"""书籍信息文本和 Pixiv 元数据的解析、格式化工具。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from os import PathLike


TEXT_BOOK_INFO_TEMPLATE = """书籍信息

{title}

作者：{author}

连载平台：{platform}

连载状态：{status}

字数：{word_count}

简介：

{description}"""

BLANK_BOOK_INFO_TEMPLATE = """书籍信息

未填

作者：未填

连载于：未填

连载状态：未填

字数：未填

简介：

未填"""


def parse_pixiv_info_file(path: str | PathLike[str]) -> dict | None:
    """解析下载器生成的 ``series_<ID>_info.txt``。"""
    info = {
        "title": "未填",
        "author": "未填",
        "platform": "Pixiv",
        "update_time": "",
        "word_count": 0,
        "chapter_count": 0,
        "tags": [],
        "description": "",
    }
    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()
    except OSError:
        return None

    in_description = False
    description_lines = []
    for line in content.splitlines():
        if in_description:
            if line.strip():
                description_lines.append(line.strip())
            continue
        if ":" not in line and "：" not in line:
            continue
        key, _, value = line.partition(":" if ":" in line else "：")
        key = key.strip()
        value = value.strip()
        if key == "系列名称":
            info["title"] = value
        elif key == "作者":
            info["author"] = value
        elif key == "更新时间":
            info["update_time"] = value
        elif key == "总字数":
            digits = "".join(char for char in value if char.isdigit())
            info["word_count"] = int(digits) if digits else 0
        elif key == "章节数":
            digits = "".join(char for char in value if char.isdigit())
            info["chapter_count"] = int(digits) if digits else 0
        elif key == "标签":
            info["tags"] = [
                tag.strip() for tag in value.replace("、", ",").split(",") if tag.strip()
            ]
        elif key == "简介":
            in_description = True
            if value:
                description_lines.append(value)

    info["description"] = "\n\n".join(description_lines) if description_lines else "未填"
    return info


def parse_pixiv_metadata_file(path: str | PathLike[str]) -> dict | None:
    """从下载器 metadata JSON 汇总章节数、番外数与字数。"""
    try:
        with open(path, "r", encoding="utf-8") as file:
            records = json.load(file)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(records, dict):
        return None

    total_word_count = sum(
        record.get("word_count", 0) for record in records.values() if isinstance(record, dict)
    )
    extra_count = sum(
        1
        for record in records.values()
        if isinstance(record, dict) and "番外" in record.get("title", "")
    )
    return {
        "title": "未填",
        "author": "未填",
        "platform": "Pixiv",
        "update_time": "",
        "word_count": total_word_count,
        "chapter_count": len(records),
        "extra_count": extra_count,
        "tags": [],
        "description": "未填",
    }


def format_word_count(word_count) -> str:
    """把字数转为一位小数的“万字”格式。"""
    try:
        value = float(word_count) / 10000.0
    except (TypeError, ValueError):
        return "未填"
    return f"{value:.1f}万字"


def format_update_date(update_time: str) -> str:
    """把 ISO 风格日期转换为中文年月日。"""
    if not update_time:
        return "未知日期"
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", update_time)
    if not match:
        return update_time[:10]
    year, month, day = match.groups()
    return f"{int(year)}年{int(month)}月{int(day)}日"


def parse_book_info_file(path: str | PathLike[str]) -> dict:
    """解析流水线中的 ``000 书籍信息.txt``。"""
    with open(path, "r", encoding="utf-8") as file:
        lines = file.read().splitlines()
    info = {
        "title": "未填",
        "author": "未填",
        "platform": "",
        "status": "",
        "word_count": "",
        "vol_count": "",
        "maker": "",
        "description": "",
    }

    non_empty = [line.strip() for line in lines if line.strip()]
    if len(non_empty) >= 2:
        info["title"] = non_empty[1]

    in_description = False
    description_lines = []
    for line in lines:
        stripped = line.strip()
        if in_description:
            if stripped:
                description_lines.append(stripped)
            continue
        for separator in ("：", ":"):
            if separator not in stripped:
                continue
            key, _, value = stripped.partition(separator)
            key = key.strip()
            value = value.strip()
            if key == "作者":
                info["author"] = value
            elif key in ("连载平台", "连载于"):
                info["platform"] = value
            elif key == "连载状态":
                info["status"] = value
            elif key in ("卷/篇数", "卷数", "分卷"):
                info["vol_count"] = value
            elif key == "字数":
                info["word_count"] = value
            elif key in ("TXT制作", "EPUB制作", "制作人"):
                if not info["maker"]:
                    info["maker"] = value
            elif key == "简介":
                in_description = True
                if value:
                    description_lines.append(value)
            break
    if description_lines:
        info["description"] = "\n".join(description_lines)
    return info


def upsert_maker_line(
    content: str,
    maker: str | None,
    *,
    info: Callable[[str], None] | None = None,
) -> tuple[str, bool]:
    """在字数行后写入或更新 ``TXT制作`` 行；空 maker 保持内容不变。"""
    if not maker:
        return content, True
    without_old = re.sub(r"^TXT制作[：:].*$\n?", "", content, flags=re.MULTILINE)
    match = re.search(r"^字数[：:].*$\n?", without_old, flags=re.MULTILINE)
    if match is None:
        return without_old, False
    replacement = match.group(0) + f"\nTXT制作：{maker}\n"
    updated = without_old[: match.start()] + replacement + without_old[match.end() :]
    if info is not None:
        info(f"已补充书籍信息 TXT制作: {maker}")
    return updated, True

