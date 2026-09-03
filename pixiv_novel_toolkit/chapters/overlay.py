"""章节文件的数字前缀索引与多目录覆盖规则。"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from collections.abc import Callable, Iterable


def file_prefix(filename: str) -> str | None:
    """返回文件名开头的数字前缀，无前缀返回 ``None``。"""
    match = re.match(r"^(\d+)", filename)
    return match.group(1) if match else None


def list_text_files(directory: str) -> list[str]:
    """列出可参与章节处理的 TXT，跳过下划线开头的系统文件。"""
    if not os.path.isdir(directory):
        return []
    return [
        filename
        for filename in os.listdir(directory)
        if filename.lower().endswith(".txt") and not filename.startswith("_")
    ]


def build_prefix_index(
    directory: str,
    *,
    warn: Callable[[str], None] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """按数字前缀建立章节索引，并保留无数字前缀文件名。"""
    prefix_map: dict[str, str] = {}
    no_prefix: list[str] = []
    for filename in list_text_files(directory):
        prefix = file_prefix(filename)
        if prefix is None:
            no_prefix.append(filename)
            continue
        if prefix in prefix_map and warn is not None:
            warn(
                f"前缀冲突: 目录 {directory} 下 {prefix_map[prefix]!r} 与 "
                f"{filename!r} 共用前缀 {prefix!r}，配对时将取后者"
            )
        prefix_map[prefix] = filename
    return prefix_map, no_prefix


def collect_text_overlay(
    directories: Iterable[str],
    *,
    exclude_book_info: bool = False,
    warn_missing: Callable[[str], None] | None = None,
):
    """按“后列目录优先”收集 TXT 文件。

    返回 ``OrderedDict[key, (filename, path)]``。数字前缀作为 key，无数字前缀时
    使用完整文件名；下划线开头的系统文件始终跳过。
    """
    collected = OrderedDict()
    for directory in directories:
        if not os.path.isdir(directory):
            if warn_missing is not None:
                warn_missing(f"输入目录不存在，已跳过: {directory}")
            continue
        for filename in os.listdir(directory):
            if not filename.lower().endswith(".txt") or filename.startswith("_"):
                continue
            if exclude_book_info and filename.startswith("000 "):
                continue
            prefix = file_prefix(filename)
            key = prefix if prefix is not None else filename
            collected[key] = (filename, os.path.join(directory, filename))
    return collected

