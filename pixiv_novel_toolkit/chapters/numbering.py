"""章节重编号、输出编号分配与编号统计报告。"""

import re

from .markers import chapter_number_to_chinese


def compress_ranges(nums):
    """把升序编号压缩为 ``001-003、007`` 形式。"""
    if not nums:
        return ""
    parts = []
    start = previous = nums[0]
    for number in nums[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(
            f"{start:03d}" if start == previous else f"{start:03d}-{previous:03d}"
        )
        start = previous = number
    parts.append(f"{start:03d}" if start == previous else f"{start:03d}-{previous:03d}")
    return "、".join(parts)


def normalize_title_key(title):
    """仅保留中英文与数字，用于识别同号同题重发。"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", title or "")


def chapter_name(title):
    """去掉标准章节号前缀；仅有编号或番外标题时保留原文。"""
    stripped = title.strip()
    match = re.match(
        r"^(?:第)?[一二三四五六七八九十百千万零两0-9.]+[章话节回]\s*[：:]?\s*",
        stripped,
    )
    if match:
        name = stripped[match.end() :].strip()
        if name:
            return name
    return stripped


def renumber_segments(segments):
    """按出现顺序修正可编号章节，原地更新标题并返回修正数量。"""
    first_num = None
    base_style = None
    for segment in segments:
        marker = segment["mk"]
        if marker["num"] is not None and marker["style"] not in (None, "fanwai"):
            first_num, base_style = marker["num"], marker["style"]
            break
    if first_num is None or base_style is None:
        return segments, 0

    fixed_count = 0
    counter = 0
    for segment in segments:
        marker = segment["mk"]
        if marker["num"] is None or marker["style"] in (None, "fanwai"):
            continue
        new_num = first_num + counter
        counter += 1
        if new_num != marker["num"]:
            fixed_count += 1

        suffix = marker["suffix"] or "章"
        if base_style == "chinese":
            head = f"第{chapter_number_to_chinese(new_num)}{suffix}"
        elif base_style == "bare_chinese_sfx":
            head = f"{chapter_number_to_chinese(new_num)}{suffix}"
        elif base_style == "arabic":
            head = f"第{new_num}{suffix}"
        elif base_style == "bare_sfx":
            head = f"{new_num}{suffix}"
        else:
            head = f"{new_num}"

        title = marker["title"].rstrip()
        if not title:
            segment["title"] = head
        else:
            segment["title"] = head + (marker["sep"] or " ") + title
    return segments, fixed_count


def allocate_output_number(preferred, used_numbers, last_output, *, warn=None):
    """优先分配原编号；冲突或无编号时从最后输出号之后寻找空位。"""
    if preferred is not None and preferred not in used_numbers:
        used_numbers.add(preferred)
        return preferred, preferred
    if preferred is not None and warn:
        warn(
            f"  章节原编号 {preferred:03d} 重复出现，顺延分配新编号"
            "（--no-renumber 模式下请人工核对）"
        )
    candidate = last_output + 1
    while candidate in used_numbers:
        candidate += 1
    used_numbers.add(candidate)
    return candidate, candidate


def describe_number_gaps(used_numbers):
    """生成相邻导出编号之间的缺口描述。"""
    gaps = []
    numbers = sorted(used_numbers)
    for previous, current in zip(numbers, numbers[1:]):
        if current > previous + 1:
            start, end = previous + 1, current - 1
            missing = f"{start:03d}-{end:03d}" if end > start else f"{start:03d}"
            gaps.append(f"{previous:03d}->{current:03d}（缺 {missing}）")
    return gaps


def build_number_report(
    export_log,
    *,
    rejected_markers=None,
    suspicious=None,
    gap_limit=0,
):
    """生成 `_编号统计.txt` 的完整 UTF-8 文本。"""
    rejected_markers = rejected_markers or []
    suspicious = suspicious or []
    lines = ["# 章节编号统计（split 自动生成，按章节标记原编号统计）"]
    originals = [entry["orig"] for entry in export_log if entry["orig"] is not None]
    unnumbered = len(export_log) - len(originals)
    if not originals:
        lines.append(f"# 共 {len(export_log)} 章，全部为无编号标记（番外等），无编号统计。")
        return "\n".join(lines) + "\n"

    numbers = sorted(originals)
    lowest, highest = numbers[0], numbers[-1]
    missing = []
    for previous, current in zip(numbers, numbers[1:]):
        if current > previous + 1:
            missing.extend(range(previous + 1, current))

    by_original = {}
    for entry in export_log:
        if entry["orig"] is not None:
            by_original.setdefault(entry["orig"], []).append(entry)
    duplicates = {
        number: entries for number, entries in by_original.items() if len(entries) > 1
    }

    lines.append(
        f"# 共 {len(export_log)} 章"
        + (
            f"（编号章 {len(originals)}、无编号/番外 {unnumbered}）"
            if unnumbered
            else ""
        )
    )
    lines.append(
        f"# 原编号范围 {lowest:03d}~{highest:03d}：缺失 {len(missing)} 个，"
        f"重复 {len(duplicates)} 处"
    )
    lines.append("")

    if lowest > 1:
        lines.append("## 起始编号提示")
        lines.append(
            f"首个编号为 {lowest:03d}（1~{lowest - 1:03d} 未出现；"
            "若非节选/续篇，请检查开头章节是否漏识别）"
        )
        lines.append("")
    if missing:
        lines.append(f"## 缺失编号（{len(missing)} 个：原文缺号或有章节标记未被识别）")
        lines.append(compress_ranges(missing))
        lines.append("")
    if duplicates:
        lines.append(f"## 重复编号（{len(duplicates)} 处：作者标号错误，重复章已顺延分配导出编号）")
        for number in sorted(duplicates):
            for entry in duplicates[number]:
                mark = (
                    "（原编号）"
                    if entry["out"] == number
                    else f"（顺延为 {entry['out']:03d}）"
                )
                lines.append(f"- {number:03d} {mark}: {entry['name']}")
        lines.append("")
    if rejected_markers:
        lines.append(
            f"## 被连续性校验拒绝的疑似标记（{len(rejected_markers)} 行：编号比最高"
            f"编号回退超过 {gap_limit} 章，已并入上一章正文，未拆分为章节）"
        )
        for line_number, text in rejected_markers:
            lines.append(f"- 行{line_number}: {text}")
        lines.append("")
    if suspicious:
        lines.append(
            f"## 疑似未识别的章节标记（{len(suspicious)} 行：编号落在已识别范围内"
            "但形式未匹配——粘连/含句号/标题正文同行等，请人工核对）"
        )
        for line_number, text in suspicious:
            lines.append(f"- 行{line_number}: {text}")
        lines.append("")
    if not missing and not duplicates and lowest == 1 and not suspicious and not rejected_markers:
        lines.append("编号从 001 起连续，无缺失、无重复。")
    return "\n".join(lines) + "\n"
