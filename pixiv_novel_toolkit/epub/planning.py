"""EPUB 阅读顺序与卷章节层级规划。"""

from __future__ import annotations

from collections.abc import Callable


LogCallback = Callable[[str], None] | None


def _emit(callback: LogCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def plan_spine(
    chapters: list[tuple[str, str, str]],
    volumes: list[dict],
    *,
    warning: LogCallback = None,
    info: LogCallback = None,
) -> tuple[list[dict], dict[int, list[str]]]:
    """把章节与卷范围转换为 EPUB spine 条目和卷章节映射。"""
    valid_volumes = []
    for volume in volumes:
        keys = [
            key
            for key, _, _ in chapters
            if key.isdigit() and volume["start"] <= int(key) <= volume["end"]
        ]
        if not keys:
            _emit(
                warning,
                f"卷「{volume['name']}」范围内没有匹配章节"
                f"（{volume['start']}-{volume['end']}），不生成该卷页",
            )
            continue
        valid_volumes.append(
            {
                "name": volume["name"],
                "start": volume["start"],
                "end": volume["end"],
                "keys": keys,
            }
        )
        _emit(info, f"卷「{volume['name']}」: 覆盖 {len(keys)} 章（{keys[0]}~{keys[-1]}）")

    first_chapter = {
        index + 1: volume["keys"][0] for index, volume in enumerate(valid_volumes)
    }
    volume_chapters = {
        index + 1: volume["keys"] for index, volume in enumerate(valid_volumes)
    }

    spine_items = []
    chapter_sequence = 0
    for key, display_title, path in chapters:
        volume_index = None
        if key.isdigit():
            for index, volume in enumerate(valid_volumes, start=1):
                if volume["start"] <= int(key) <= volume["end"]:
                    volume_index = index
                    break
        if volume_index is not None and key == first_chapter[volume_index]:
            spine_items.append(
                {
                    "kind": "vol",
                    "fname": f"vol_{volume_index}.xhtml",
                    "id": f"vol_{volume_index}",
                    "title": valid_volumes[volume_index - 1]["name"],
                    "vol": volume_index,
                }
            )
        chapter_sequence += 1
        filename = f"chap_{key}.xhtml" if key.isdigit() else f"chap_{chapter_sequence:04d}.xhtml"
        spine_items.append(
            {
                "kind": "chap",
                "key": key,
                "fname": filename,
                "id": filename[:-6],
                "title": display_title,
                "path": path,
                "vol": volume_index,
            }
        )
    return spine_items, volume_chapters

