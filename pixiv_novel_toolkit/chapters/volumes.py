"""卷/篇配置读取与校验。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from os import PathLike


LogCallback = Callable[[str], None] | None


def _emit(callback: LogCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def load_volumes_file(
    volumes_file: str | PathLike[str] | None,
    *,
    error: LogCallback = None,
    warning: LogCallback = None,
    info: LogCallback = None,
) -> list[dict] | None:
    """读取卷配置并返回按 ``start`` 排序的兼容字典列表。

    未指定文件返回空列表；文件不存在或 JSON 根类型错误返回 ``None``；单条无效
    配置会被跳过并通过回调报告。
    """
    if not volumes_file:
        return []
    if not os.path.isfile(volumes_file):
        _emit(error, f"卷/篇配置文件不存在: {volumes_file}")
        return None
    try:
        with open(volumes_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        _emit(error, f"卷/篇配置文件解析失败: {exc}")
        return None
    if not isinstance(data, list):
        _emit(error, '卷/篇配置文件应为 JSON 列表，如 [{"name": "第一卷", "start": 1, "end": 17}]')
        return None

    volumes = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not item.get("name"):
            _emit(warning, f"第 {index} 条卷配置无效（缺少 name），已跳过: {item}")
            continue
        try:
            start = int(item.get("start"))
            end = int(item.get("end", start))
        except (TypeError, ValueError):
            _emit(
                warning,
                f"第 {index} 条卷配置 {item.get('name')!r} 的 start/end 不是数字，已跳过",
            )
            continue
        if start < 0 or end < start:
            _emit(
                warning,
                f"第 {index} 条卷配置 {item.get('name')!r} 范围无效"
                f"（start={start}, end={end}），已跳过",
            )
            continue
        volumes.append({"name": item["name"], "start": start, "end": end})

    volumes.sort(key=lambda volume: volume["start"])
    if volumes:
        _emit(info, f"已读取卷/篇配置: {len(volumes)} 卷")
    return volumes

