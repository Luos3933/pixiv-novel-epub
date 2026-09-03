"""EPUB 章标题与卷标题样式预设的读取和校验。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from os import PathLike

from .templates import STYLE_SAMPLE


LogCallback = Callable[[str], None] | None


def _emit(callback: LogCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def parse_style_section(
    styles: dict,
    *,
    volume: bool = False,
    warning: LogCallback = None,
) -> dict:
    """解析 chapter 或 volume 样式段，并补齐兼容默认值。"""
    presets = {}
    for name, style in styles.items():
        if not isinstance(style, dict):
            _emit(warning, f"样式预设 {name!r} 无效（应为对象），已跳过")
            continue
        if volume:
            presets[name] = {
                "vol_split": bool(style.get("vol_split", True)),
                "vol_num_color": str(style.get("vol_num_color", "#555555")),
                "vol_num_size": str(style.get("vol_num_size", "1.2em")),
                "vol_color": str(style.get("vol_color", "#8B0000")),
                "vol_size": str(style.get("vol_size", "2.5em")),
                "vol_gap": str(style.get("vol_gap", "0.6em")),
                "desc": str(style.get("desc", "")),
            }
            continue
        align = style.get("align", "center")
        if align not in ("center", "left"):
            _emit(
                warning,
                f"样式预设 {name!r} 的 align {align!r} 无效（仅支持 center/left），已跳过",
            )
            continue
        presets[name] = {
            "align": align,
            "color": str(style.get("color", "")),
            "size": str(style.get("size", "1.5em")),
            "underline": bool(style.get("underline", False)),
            "split": bool(style.get("split", False)),
            "num_color": str(style.get("num_color", "")),
            "num_size": str(style.get("num_size", "1em")),
            "desc": str(style.get("desc", "")),
        }
    return presets


def load_style_presets(
    styles_file: str | PathLike[str],
    *,
    sample: dict = STYLE_SAMPLE,
    warning: LogCallback = None,
    info: LogCallback = None,
) -> dict:
    """读取两段式样式预设；兼容旧版顶层扁平 chapter 格式。"""
    empty = {"chapter": {}, "volume": {}}
    if not os.path.isfile(styles_file):
        try:
            with open(styles_file, "w", encoding="utf-8") as file:
                file.write(json.dumps(sample, ensure_ascii=False, indent=4) + "\n")
            _emit(info, f"未找到样式预设文件，已生成示例模板: {styles_file}")
        except OSError as exc:
            _emit(warning, f"无法创建样式预设文件 {styles_file}: {exc}")
            return empty
    try:
        with open(styles_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        _emit(warning, f"样式预设文件解析失败（{styles_file}）: {exc}")
        return empty
    if not isinstance(data, dict):
        _emit(warning, '样式预设文件应为 JSON 对象 {"chapter": {...}, "volume": {...}}')
        return empty

    if "chapter" in data or "volume" in data:
        chapter_raw = data.get("chapter", {})
        volume_raw = data.get("volume", {})
    else:
        _emit(
            warning,
            '样式预设文件为旧版扁平格式，已按 chapter 段读取'
            '（卷样式请改为 "volume" 段，并用 --vol-style 调用）',
        )
        chapter_raw = data
        volume_raw = {}
    return {
        "chapter": parse_style_section(chapter_raw, warning=warning),
        "volume": parse_style_section(volume_raw, volume=True, warning=warning),
    }

