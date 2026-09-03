"""章节标记位置扫描与带连续性校验的章节分段。"""

from dataclasses import dataclass

from .markers import parse_chapter_marker
from .numbering import normalize_title_key


@dataclass
class ChapterScanResult:
    """单个文本扫描后的章节、前言与被拒标记。"""

    segments: list
    preamble: list
    rejected_markers: list


def scan_marker_lines(lines, parse_marker=parse_chapter_marker):
    """返回 ``(零基行索引, 标记字典)`` 列表。"""
    markers = []
    for index, line in enumerate(lines):
        marker = parse_marker(line)
        if marker:
            markers.append((index, marker))
    return markers


def scan_chapter_segments(
    lines,
    parse_marker,
    *,
    gap_limit=0,
    unify_marker=None,
    info=None,
    warn=None,
):
    """扫描章节段落，并按最高已识别编号执行大幅回退校验。"""
    segments = []
    preamble = []
    rejected_markers = []
    current = None
    max_num = None
    seen_titles = {}

    for line_number, line in enumerate(lines, 1):
        marker = parse_marker(line)
        if (
            marker
            and marker["num"] is not None
            and marker["style"] not in (None, "fanwai")
            and gap_limit
            and max_num is not None
            and marker["num"] < max_num
            and max_num - marker["num"] > gap_limit
        ):
            key = normalize_title_key(marker["title"] or marker["raw"])
            if key and key in seen_titles.get(marker["num"], set()):
                if info:
                    info(
                        f"  行{line_number} 编号 {marker['num']} 回退 "
                        f"{max_num - marker['num']} 章但与之前同号同题，"
                        f"判定为作者重发，正常拆分: {line.strip()[:40]}"
                    )
            else:
                if warn:
                    warn(
                        f"  行{line_number} 疑似误判标记（编号 {marker['num']} 比最高编号"
                        f" {max_num} 回退超过 {gap_limit} 章），并入上一章正文: "
                        f"{line.strip()[:40]}"
                    )
                rejected_markers.append((line_number, line.strip()[:60]))
                marker = None

        if marker:
            if (
                unify_marker
                and marker["num"] is not None
                and marker["style"] not in (None, "fanwai")
            ):
                marker = unify_marker(marker)
            title = marker["raw"]
            if (
                marker["style"] == "bare"
                and marker["num"] is not None
                and not marker["title"]
            ):
                title = f"第{marker['num']}{marker['suffix'] or '章'}"
            if marker["num"] is not None and marker["style"] not in (None, "fanwai"):
                max_num = marker["num"] if max_num is None else max(max_num, marker["num"])
                seen_titles.setdefault(marker["num"], set()).add(
                    normalize_title_key(marker["title"] or marker["raw"])
                )
            current = {
                "marker": marker["raw"],
                "mk": marker,
                "title": title,
                "lines": [],
            }
            segments.append(current)
        elif current is None:
            if line.strip():
                preamble.append(line.strip())
        else:
            current["lines"].append(line)

    return ChapterScanResult(segments, preamble, rejected_markers)
