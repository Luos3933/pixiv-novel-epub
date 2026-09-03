"""拆卷输入发现、卷规划与疑似章节诊断。"""

from dataclasses import dataclass
import json
import os
import re


@dataclass(frozen=True)
class SplitInputs:
    """已解析的拆卷输入；单个整本 txt 也统一为文件列表。"""

    source_dir: str
    filenames: list[str]
    single_file: bool


def numeric_filename_sort_key(filename):
    """章节文件按开头数字优先排序，无数字文件随后按名称排序。"""
    match = re.search(r"^(\d+)", filename)
    return (0, int(match.group(1))) if match else (1, filename)


def list_chapter_text_files(directory):
    """列出可作为章节输入的 txt，排除工具索引、统计及书籍信息文件。"""
    files = [name for name in os.listdir(directory) if name.lower().endswith(".txt")]
    files = [
        name
        for name in files
        if not name.startswith(("series_", "_", "000 "))
    ]
    return sorted(files, key=numeric_filename_sort_key)


def discover_split_inputs(input_path):
    """识别整本 txt 或多卷目录；路径类型不合法时返回 ``None``。"""
    if os.path.isfile(input_path) and input_path.lower().endswith(".txt"):
        source_dir = os.path.dirname(os.path.abspath(input_path)) or "."
        return SplitInputs(source_dir, [os.path.basename(input_path)], True)
    if os.path.isdir(input_path):
        return SplitInputs(input_path, list_chapter_text_files(input_path), False)
    return None


def volume_name_from_filename(filename):
    """从卷文件名移除排序前缀和 txt 扩展名。"""
    stem = re.sub(r"^\d+\s*", "", filename)
    if stem.lower().endswith(".txt"):
        stem = stem[:-4]
    return stem.strip()


def sanitize_filename_part(text):
    """清理章节标题中不能出现在 Windows 文件名里的字符。"""
    return re.sub(r'[\\/:*?"<>|]', " ", text).strip()


def scan_suspicious_markers(
    lines,
    export_log,
    rejected_markers,
    quantity_starters,
    limit=100,
):
    """扫描已识别编号范围内、但未被解析为章节的数字起始行。"""
    rejected_lines = {line_number for line_number, _ in rejected_markers}
    original_numbers = {
        entry["orig"] for entry in export_log if entry.get("orig") is not None
    }
    if not original_numbers:
        return []

    low, high = min(original_numbers), max(original_numbers)
    suspicious = []
    for line_number, line in enumerate(lines, 1):
        if line_number in rejected_lines:
            continue
        stripped = line.strip()
        match = re.match(r"^(\d{1,4})(?!\d)", stripped)
        if not match:
            continue
        number = int(match.group(1))
        if not (low <= number <= high) or number in original_numbers:
            continue
        next_char = stripped[match.end() : match.end() + 1]
        if (
            next_char
            and next_char in quantity_starters
            and ("。" in stripped or len(stripped) > 40)
        ):
            continue
        suspicious.append((line_number, stripped[:60]))
        if len(suspicious) >= limit:
            break
    return suspicious


def find_volume_overlaps(volumes):
    """返回相邻卷中发生编号范围重叠的卷对。"""
    return [
        (previous, current)
        for previous, current in zip(volumes, volumes[1:])
        if current["start"] <= previous["end"]
    ]


def write_volumes_file(output_dir, volumes):
    """把卷配置写到章节输出目录的上级并返回路径。"""
    parent = os.path.dirname(os.path.abspath(output_dir)) or output_dir
    path = os.path.join(parent, "volumes.json")
    with open(path, "w", encoding="utf-8") as file:
        file.write(json.dumps(volumes, ensure_ascii=False, indent=4) + "\n")
    return path
