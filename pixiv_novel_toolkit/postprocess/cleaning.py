"""保守的小说正文清洗流水线。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pixiv_novel_toolkit.chapters.markers import parse_chapter_marker
from pixiv_novel_toolkit.common.textio import detect_encoding, read_text
from .formatting import convert_punctuation


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")

_TERMINAL_PUNCTUATION = "。！？!?；;：:，,、…—”’」』）》】"
_CHINESE_NUMBER = "一二两三四五六七八九十百千万零"
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_ILLUSTRATION_MARKER_RE = re.compile(
    r"(?:^【插图\s*[:：]\s*[^】]+】$|^\[uploadedimage:\d+\]$)",
    re.IGNORECASE,
)


def is_suspected_hard_wrap(lines, index, settings):
    """判断相邻两行是否像排版宽度造成的句内硬换行。"""
    if index < 0 or index + 1 >= len(lines):
        return False
    current = lines[index].strip()
    following = lines[index + 1].strip()
    if not current or not following:
        return False
    minimum = settings.get("minimum_previous_length", 30)
    maximum = settings.get("maximum_line_length", 80)
    if len(current) < minimum or (maximum and len(current) > maximum):
        return False
    if current.endswith(tuple(_TERMINAL_PUNCTUATION)):
        return False
    if parse_chapter_marker(current) or parse_chapter_marker(following):
        return False
    return True


def _join_text(left, right):
    """连接两个句内片段；连续拉丁字母或数字之间保留一个空格。"""
    left = left.rstrip()
    right = right.lstrip()
    if left and right and left[-1].isascii() and right[0].isascii():
        if left[-1].isalnum() and right[0].isalnum():
            return f"{left} {right}"
    return left + right


def _is_advertisement_line(line, settings):
    """只识别带明确行首标记的作者求票/求收藏整行。"""
    stripped = line.strip()
    if not stripped:
        return False
    folded = stripped.casefold()
    prefixes = settings.get("required_prefixes", [])
    if not any(folded.startswith(prefix.casefold()) for prefix in prefixes if prefix):
        return False
    return any(keyword in stripped for keyword in settings.get("keywords", []) if keyword)


def _remove_advertisement_blocks(lines, settings):
    """删除明确作者附言及有限数量的广告续段，遇到正常正文立即停止。"""
    cleaned = []
    removed = 0
    index = 0
    maximum = settings.get("maximum_following_paragraphs", 3)
    continuation_keywords = settings.get("continuation_keywords", [])
    while index < len(lines):
        if not _is_advertisement_line(lines[index], settings):
            cleaned.append(lines[index])
            index += 1
            continue

        removed += 1
        index += 1
        following = 0
        while following < maximum and index < len(lines):
            gap_start = index
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index >= len(lines):
                break
            stripped = lines[index].strip()
            if not any(
                keyword in stripped for keyword in continuation_keywords if keyword
            ):
                cleaned.extend(lines[gap_start:index])
                break
            removed += 1
            following += 1
            index += 1
    return cleaned, removed


def find_blank_separated_author_note_blocks(lines, settings):
    """定位章末连续空行后的顶格作者附言及随附插图标记。"""
    minimum_blanks = settings.get("minimum_blank_lines", 3)
    maximum_lines = settings.get("maximum_note_lines", 20)
    signal_scan_lines = settings.get("signal_scan_lines", 3)
    remove_illustrations = settings.get("remove_illustration_markers", True)
    signals = [signal.casefold() for signal in settings.get("signals", []) if signal]
    marker_indexes = [
        index for index, line in enumerate(lines) if parse_chapter_marker(line)
    ]
    if marker_indexes:
        regions = [
            (marker_index + 1, marker_indexes[position + 1]
             if position + 1 < len(marker_indexes) else len(lines))
            for position, marker_index in enumerate(marker_indexes)
        ]
    else:
        regions = [(0, len(lines))]

    def build_block(blank_start, content_start, tail_end, region_end):
        nonempty = [
            (position, lines[position].strip())
            for position in range(content_start, tail_end)
            if lines[position].strip()
        ]
        if not nonempty:
            return None
        first_raw = lines[nonempty[0][0]]
        if (
            first_raw.startswith(("　　", "  ", "\t"))
            and not _ILLUSTRATION_MARKER_RE.fullmatch(nonempty[0][1])
        ):
            return None

        illustrations = [
            {"line": position + 1, "text": text}
            for position, text in nonempty
            if _ILLUSTRATION_MARKER_RE.fullmatch(text)
        ]
        removable = [
            (position, text)
            for position, text in nonempty
            if (
                not _ILLUSTRATION_MARKER_RE.fullmatch(text)
                and not lines[position].startswith(("　　", "  ", "\t"))
            )
        ]
        if not removable or (maximum_lines and len(removable) > maximum_lines):
            return None
        folded = "\n".join(
            text for _, text in removable[:signal_scan_lines]
        ).casefold()
        matched = [signal for signal in signals if signal in folded]
        if not matched:
            return None
        author_indexes = [position for position, _ in removable]
        illustration_indexes = [item["line"] - 1 for item in illustrations]
        remove_indexes = author_indexes + (
            illustration_indexes if remove_illustrations else []
        )
        return {
            "start": blank_start,
            "content_start": content_start,
            "end": region_end,
            "line": removable[0][0] + 1,
            "blank_line": blank_start + 1,
            "blank_count": content_start - blank_start,
            "line_count": len(remove_indexes),
            "author_line_count": len(removable),
            "illustration_count": len(illustrations),
            "matched_signals": matched,
            "preview": " / ".join(text for _, text in removable[:3]),
            "remove_indexes": remove_indexes,
            "removed_illustrations": illustrations if remove_illustrations else [],
        }

    blocks = []
    for region_start, region_end in regions:
        tail_end = region_end
        while tail_end > region_start and not lines[tail_end - 1].strip():
            tail_end -= 1

        last_indented = next(
            (
                position
                for position in range(tail_end - 1, region_start - 1, -1)
                if lines[position].strip()
                and lines[position].startswith(("　　", "  ", "\t"))
            ),
            None,
        )
        if last_indented is not None:
            blank_start = last_indented + 1
            content_start = blank_start
            while content_start < tail_end and not lines[content_start].strip():
                content_start += 1
            if content_start - blank_start >= minimum_blanks:
                block = build_block(
                    blank_start,
                    content_start,
                    tail_end,
                    region_end,
                )
                if block is not None:
                    blocks.append(block)
                    continue

        blank_runs = []
        index = region_start
        while index < tail_end:
            if lines[index].strip():
                index += 1
                continue
            run_start = index
            while index < tail_end and not lines[index].strip():
                index += 1
            if index - run_start >= minimum_blanks:
                blank_runs.append((run_start, index))

        for blank_start, content_start in reversed(blank_runs):
            block = build_block(blank_start, content_start, tail_end, region_end)
            if block is not None:
                blocks.append(block)
                break
    return blocks


def _remove_blank_separated_author_notes(lines, settings):
    """删除已确认的顶格作者附言行及其随附插图文本标记。"""
    blocks = find_blank_separated_author_note_blocks(lines, settings)
    remove_indexes = {
        index for block in blocks for index in block["remove_indexes"]
    }
    cleaned = [line for index, line in enumerate(lines) if index not in remove_indexes]
    return cleaned, sum(block["line_count"] for block in blocks), len(blocks)


def _is_ellipsis_paragraph(text):
    """判断整段是否只是省略号，避免重复插入场景分隔符。"""
    stripped = text.strip()
    return bool(re.fullmatch(r"(?:…{2,}|\.{3,}|。{3,})", stripped))


def _context_paragraphs(lines, start, step, limit):
    """从指定位置向前或向后收集正文段落，遇章节标记停止。"""
    result = []
    index = start
    while 0 <= index < len(lines) and len(result) < limit:
        stripped = lines[index].strip()
        if stripped:
            if parse_chapter_marker(stripped):
                break
            result.append({"line": index + 1, "text": stripped})
        index += step
    if step < 0:
        result.reverse()
    return result


def find_scene_break_candidates(lines, settings, author_note_settings):
    """定位由多个连续空行表示的场景跳转，并附带前后段落。"""
    minimum_blanks = settings.get("minimum_blank_lines", 3)
    context_count = settings.get("context_paragraphs", 2)
    author_blocks = find_blank_separated_author_note_blocks(
        lines,
        author_note_settings,
    )
    author_ranges = [(block["start"], block["end"]) for block in author_blocks]
    candidates = []
    index = 0
    while index < len(lines):
        if lines[index].strip():
            index += 1
            continue
        run_start = index
        while index < len(lines) and not lines[index].strip():
            index += 1
        run_end = index
        if (
            run_end - run_start < minimum_blanks
            or any(start <= run_start < end for start, end in author_ranges)
        ):
            continue

        previous = next(
            (position for position in range(run_start - 1, -1, -1)
             if lines[position].strip()),
            None,
        )
        following = next(
            (position for position in range(run_end, len(lines))
             if lines[position].strip()),
            None,
        )
        if previous is None or following is None:
            continue
        if parse_chapter_marker(lines[previous]) or parse_chapter_marker(lines[following]):
            continue

        existing_marker = (
            _is_ellipsis_paragraph(lines[previous])
            or _is_ellipsis_paragraph(lines[following])
        )
        candidates.append({
            "start": run_start,
            "end": run_end,
            "line": run_start + 1,
            "blank_count": run_end - run_start,
            "existing_marker": existing_marker,
            "before": _context_paragraphs(
                lines,
                run_start - 1,
                -1,
                context_count,
            ),
            "after": _context_paragraphs(
                lines,
                run_end,
                1,
                context_count,
            ),
        })
    return candidates


def _replace_scene_break_blank_lines(lines, settings, author_note_settings):
    """把场景跳转空行替换为省略号段落，已有省略号时不重复插入。"""
    candidates = find_scene_break_candidates(lines, settings, author_note_settings)
    cleaned = list(lines)
    inserted = 0
    normalized = 0
    marker = settings.get("marker", "……") or "……"
    for candidate in reversed(candidates):
        if candidate["existing_marker"]:
            replacement = [""]
            normalized += 1
        else:
            replacement = ["", marker, ""]
            inserted += 1
        cleaned[candidate["start"]:candidate["end"]] = replacement
    return cleaned, inserted, normalized


def _repair_chapter_title(line, settings):
    """修复高置信度的缺“第/章”和编号点号问题。"""
    leading = line[: len(line) - len(line.lstrip())]
    body = line.strip()
    if not body or len(body) > 40 or any(mark in body for mark in "。！？"):
        return line, []
    reasons = []

    if settings.get("remove_number_dots", True):
        dotted = re.match(r"^第([0-9０-９]+(?:[.．][0-9０-９]+)+)([章话节回])(.*)$", body)
        if dotted:
            number = dotted.group(1).replace(".", "").replace("．", "")
            number = number.translate(_FULLWIDTH_DIGITS)
            body = f"第{number}{dotted.group(2)}{dotted.group(3)}"
            reasons.append("移除章节编号中的点号")

    if settings.get("repair_missing_suffix", True):
        missing_suffix = re.match(
            rf"^第([{_CHINESE_NUMBER}0-9０-９]{{1,12}})([ \t　：:、，,]+)(.+)$",
            body,
        )
        if missing_suffix:
            number = missing_suffix.group(1).translate(_FULLWIDTH_DIGITS)
            title = missing_suffix.group(3).strip()
            body = f"第{number}章 {title}"
            reasons.append("补全章节标题的“章”")

    marker = parse_chapter_marker(body)
    if marker and settings.get("repair_missing_prefix", True):
        separated_or_empty = bool(marker["sep"]) or not marker["title"]
        if marker["style"] in {"bare_chinese_sfx", "bare_sfx"} and separated_or_empty:
            body = "第" + body
            reasons.append("补全章节标题的“第”")
        elif (
            marker["style"] == "bare"
            and separated_or_empty
            and settings.get("repair_missing_suffix", True)
        ):
            title = marker["title"].strip()
            body = f"第{marker['num']}章" + (f" {title}" if title else "")
            reasons.append("补全章节标题的“第/章”")
    return leading + body, reasons


def clean_text(text, config):
    """按照 clean 配置清洗一篇文本，返回 ``(新文本, 修改记录)``。"""
    settings = config["clean"]
    changes = []
    had_final_newline = text.endswith(("\n", "\r"))

    quote_rule = settings["join_broken_quote_lines"]
    if quote_rule["enabled"]:
        text, count_one = re.subn(r"([：:][“\"])\r?\n[ \t　]*", r"\1", text)
        text, count_two = re.subn(r"([：:])\r?\n[ \t　]*([“\"])", r"\1\2", text)
        if count_one + count_two:
            changes.append({
                "rule": "join_broken_quote_lines",
                "count": count_one + count_two,
                "message": "合并冒号或开引号后的错误断行",
            })

    lines = text.splitlines()
    title_rule = settings["normalize_chapter_titles"]
    if title_rule["enabled"]:
        repaired = []
        reason_counts = {}
        for line in lines:
            new_line, reasons = _repair_chapter_title(line, title_rule)
            repaired.append(new_line)
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        lines = repaired
        for reason, count in reason_counts.items():
            changes.append({
                "rule": "normalize_chapter_titles",
                "count": count,
                "message": reason,
            })

    duplicate_rule = settings["remove_adjacent_duplicate_lines"]
    if duplicate_rule["enabled"]:
        deduplicated = []
        removed = 0
        minimum = duplicate_rule.get("minimum_length", 4)
        for line in lines:
            stripped = line.strip()
            previous = deduplicated[-1].strip() if deduplicated else ""
            if (
                stripped
                and len(stripped) >= minimum
                and stripped == previous
                and parse_chapter_marker(stripped) is None
            ):
                removed += 1
                continue
            deduplicated.append(line)
        lines = deduplicated
        if removed:
            changes.append({
                "rule": "remove_adjacent_duplicate_lines",
                "count": removed,
                "message": "删除完全相同的相邻重复行",
            })

    advert_rule = settings["remove_advertisement_lines"]
    if advert_rule["enabled"]:
        lines, removed = _remove_advertisement_blocks(lines, advert_rule)
        if removed:
            changes.append({
                "rule": "remove_advertisement_lines",
                "count": removed,
                "message": "删除带明确 PS/作者话前缀的作者附言块",
            })

    blank_note_rule = settings["remove_blank_separated_author_notes"]
    if blank_note_rule["enabled"]:
        lines, removed, block_count = _remove_blank_separated_author_notes(
            lines,
            blank_note_rule,
        )
        if removed:
            changes.append({
                "rule": "remove_blank_separated_author_notes",
                "count": removed,
                "message": (
                    f"删除由连续空行分隔的章末作者附言及随附插图标记"
                    f"（{block_count} 块）"
                ),
            })

    scene_rule = settings["replace_scene_break_blank_lines"]
    if scene_rule["enabled"]:
        lines, inserted, normalized = _replace_scene_break_blank_lines(
            lines,
            scene_rule,
            blank_note_rule,
        )
        if inserted or normalized:
            changes.append({
                "rule": "replace_scene_break_blank_lines",
                "count": inserted + normalized,
                "message": (
                    f"处理连续空行场景跳转（插入分隔符 {inserted} 处，"
                    f"已有分隔符 {normalized} 处）"
                ),
            })

    wrap_rule = settings["join_suspected_hard_wraps"]
    if wrap_rule["enabled"]:
        joined = []
        index = 0
        join_count = 0
        while index < len(lines):
            current = lines[index]
            while is_suspected_hard_wrap(lines, index, wrap_rule):
                current = _join_text(current, lines[index + 1])
                lines[index + 1] = current
                index += 1
                join_count += 1
            joined.append(current)
            index += 1
        lines = joined
        if join_count:
            changes.append({
                "rule": "join_suspected_hard_wraps",
                "count": join_count,
                "message": "合并疑似排版宽度导致的句内硬换行",
            })

    text = "\n".join(lines)
    if had_final_newline:
        text += "\n"
    punctuation_rule = settings["normalize_punctuation"]
    if punctuation_rule["enabled"]:
        text, stats = convert_punctuation(text)
        count = (
            stats["original_quote"]
            + stats["original_exclamation"]
            + stats["original_question"]
        )
        if count:
            changes.append({
                "rule": "normalize_punctuation",
                "count": count,
                "message": "转换英文引号、问号和感叹号",
            })
    return text, changes


class TextCleaner:
    """清洗单个 TXT 或目录，并把结果与报告写入独立目录。"""

    def __init__(self, input_path, output_dir, report_dir, config, *, dry_run=False):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)
        self.config = config
        self.dry_run = dry_run

    def _input_files(self):
        if self.input_path.is_file():
            return [self.input_path]
        return sorted(
            path for path in self.input_path.iterdir()
            if path.is_file() and path.suffix.lower() == ".txt" and not path.name.startswith("_")
        )

    def run(self):
        records = []
        author_note_candidates = []
        scene_break_candidates = []
        sources = self._input_files()
        source_names = {source.name for source in sources}
        stale_output_files = []
        if self.input_path.is_dir() and self.output_dir.is_dir():
            stale_output_files = sorted(
                path.name for path in self.output_dir.iterdir()
                if (
                    path.is_file()
                    and path.suffix.lower() == ".txt"
                    and not path.name.startswith("_")
                    and path.name not in source_names
                )
            )
            if stale_output_files:
                logger.warning(
                    "清洗输出目录含 %d 个不属于本次输入的旧 TXT，已保留并写入报告",
                    len(stale_output_files),
                )
        if not self.dry_run:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        for source in sources:
            original = read_text(source, info=logger.info)
            decoding_changes = []
            raw = source.read_bytes()
            encoding = detect_encoding(source)
            try:
                raw.decode(encoding)
            except UnicodeDecodeError:
                decoding_changes.append({
                    "rule": "decode_recovery",
                    "count": original.count("\ufffd"),
                    "message": f"源文件含损坏字节，按 {encoding} 容错读取并写入替换符",
                })
            if source.name.startswith("000 "):
                cleaned, changes = original, []
            else:
                source_lines = original.splitlines()
                author_rule = self.config["clean"][
                    "remove_blank_separated_author_notes"
                ]
                for block in find_blank_separated_author_note_blocks(
                    source_lines,
                    author_rule,
                ):
                    author_note_candidates.append({
                        "file": source.name,
                        "line": block["line"],
                        "blank_line": block["blank_line"],
                        "blank_count": block["blank_count"],
                        "line_count": block["line_count"],
                        "matched_signals": block["matched_signals"],
                        "preview": block["preview"],
                        "author_line_count": block["author_line_count"],
                        "illustration_count": block["illustration_count"],
                        "removed_illustrations": block[
                            "removed_illustrations"
                        ],
                        "action": (
                            "would_remove" if self.dry_run else "removed"
                        ) if author_rule["enabled"] else "not_enabled",
                    })

                scene_rule = self.config["clean"][
                    "replace_scene_break_blank_lines"
                ]
                for candidate in find_scene_break_candidates(
                    source_lines,
                    scene_rule,
                    author_rule,
                ):
                    if not scene_rule["enabled"]:
                        action = "not_enabled_existing_marker" if candidate[
                            "existing_marker"
                        ] else "not_enabled"
                    elif self.dry_run:
                        action = "would_normalize_existing_marker" if candidate[
                            "existing_marker"
                        ] else "would_insert_marker"
                    else:
                        action = "normalized_existing_marker" if candidate[
                            "existing_marker"
                        ] else "inserted_marker"
                    scene_break_candidates.append({
                        "file": source.name,
                        "line": candidate["line"],
                        "blank_count": candidate["blank_count"],
                        "existing_marker": candidate["existing_marker"],
                        "action": action,
                        "before": candidate["before"],
                        "after": candidate["after"],
                    })
                cleaned, changes = clean_text(original, self.config)
            changes = decoding_changes + changes
            target = self.output_dir / source.name
            if not self.dry_run:
                target.write_text(cleaned, encoding="utf-8")
            records.append({
                "file": source.name,
                "source": str(source),
                "output": str(target),
                "changed": cleaned != original or bool(decoding_changes),
                "changes": changes,
            })
        report = {
            "input": str(self.input_path),
            "output": str(self.output_dir),
            "dry_run": self.dry_run,
            "enabled_rules": [
                name for name, settings in self.config["clean"].items()
                if settings["enabled"]
            ],
            "disabled_rules": [
                name for name, settings in self.config["clean"].items()
                if not settings["enabled"]
            ],
            "stale_output_files": stale_output_files,
            "files": records,
            "summary": {
                "file_count": len(records),
                "changed_files": sum(record["changed"] for record in records),
                "change_count": sum(
                    change["count"]
                    for record in records
                    for change in record["changes"]
                ),
                "by_rule": {
                    rule: sum(
                        change["count"]
                        for record in records
                        for change in record["changes"]
                        if change["rule"] == rule
                    )
                    for rule in sorted({
                        change["rule"]
                        for record in records
                        for change in record["changes"]
                    })
                },
            },
            "feature_reports": {
                "blank_author_notes": {
                    "enabled": self.config["clean"][
                        "remove_blank_separated_author_notes"
                    ]["enabled"],
                    "candidate_count": len(author_note_candidates),
                    "files": "blank_author_notes_report.txt/json",
                },
                "scene_breaks": {
                    "enabled": self.config["clean"][
                        "replace_scene_break_blank_lines"
                    ]["enabled"],
                    "candidate_count": len(scene_break_candidates),
                    "files": "scene_breaks_report.txt/json",
                },
            },
        }
        feature_reports = {
            "blank_author_notes": {
                "input": str(self.input_path),
                "rule": "remove_blank_separated_author_notes",
                "enabled": self.config["clean"][
                    "remove_blank_separated_author_notes"
                ]["enabled"],
                "dry_run": self.dry_run,
                "candidate_count": len(author_note_candidates),
                "candidates": author_note_candidates,
            },
            "scene_breaks": {
                "input": str(self.input_path),
                "rule": "replace_scene_break_blank_lines",
                "enabled": self.config["clean"][
                    "replace_scene_break_blank_lines"
                ]["enabled"],
                "dry_run": self.dry_run,
                "marker": self.config["clean"][
                    "replace_scene_break_blank_lines"
                ].get("marker", "……"),
                "candidate_count": len(scene_break_candidates),
                "candidates": scene_break_candidates,
            },
        }
        self._write_report(report, feature_reports)
        return report

    def _write_report(self, report, feature_reports):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "clean_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary = report["summary"]
        lines = [
            "# 文本清洗报告",
            f"输入：{report['input']}",
            f"输出：{report['output']}",
            f"模式：{'仅预览（未写正文）' if report['dry_run'] else '已写入清洗结果'}",
            f"文件：{summary['file_count']}，有修改：{summary['changed_files']}，"
            f"修改项：{summary['change_count']}",
            "已启用自动修复：" + "、".join(report["enabled_rules"]),
            "未启用自动修复：" + ("、".join(report["disabled_rules"]) or "无"),
            "",
        ]
        if report["stale_output_files"]:
            lines.append(
                "注意：输出目录中保留了不属于本次输入的旧 TXT："
                + "、".join(report["stale_output_files"])
            )
            lines.append("")
        for record in report["files"]:
            lines.append(f"## {record['file']}")
            if not record["changes"]:
                lines.append("- 无修改")
            for change in record["changes"]:
                lines.append(f"- {change['message']}：{change['count']} 处 [{change['rule']}]")
            lines.append("")
        (self.report_dir / "clean_report.txt").write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )
        self._write_feature_reports(feature_reports)

    def _write_feature_reports(self, reports):
        """为两项依赖原始空行结构的规则分别输出候选报告。"""
        action_labels = {
            "not_enabled": "规则关闭，仅报告候选",
            "not_enabled_existing_marker": "规则关闭；相邻已有省略号，仅报告候选",
            "would_remove": "仅预览：将删除",
            "removed": "已删除",
            "would_insert_marker": "仅预览：将插入场景分隔符",
            "inserted_marker": "已插入场景分隔符",
            "would_normalize_existing_marker": "仅预览：已有省略号，将只规范空行",
            "normalized_existing_marker": "相邻已有省略号，未重复插入并已规范空行",
        }
        file_specs = {
            "blank_author_notes": (
                "blank_author_notes_report",
                "连续空行章末作者附言候选报告",
            ),
            "scene_breaks": (
                "scene_breaks_report",
                "连续空行场景跳转候选报告",
            ),
        }
        for key, payload in reports.items():
            stem, title = file_specs[key]
            (self.report_dir / f"{stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            lines = [
                f"# {title}",
                f"输入：{payload['input']}",
                f"规则：{payload['rule']}",
                f"状态：{'已启用' if payload['enabled'] else '默认关闭，仅扫描'}",
                f"候选：{payload['candidate_count']}",
                "",
            ]
            if not payload["candidates"]:
                lines.append("未发现候选。")
            for candidate in payload["candidates"]:
                lines.append(f"## {candidate['file']}:{candidate['line']}")
                lines.append(f"处理：{action_labels[candidate['action']]}")
                lines.append(f"连续空行：{candidate['blank_count']} 行")
                if key == "blank_author_notes":
                    lines.append(
                        "命中信号：" + "、".join(candidate["matched_signals"])
                    )
                    lines.append(f"> {candidate['preview']}")
                    if candidate["removed_illustrations"]:
                        lines.append("随附插图标记（启用后同样删除）：")
                        for item in candidate["removed_illustrations"]:
                            lines.append(f"- {item['line']}: {item['text']}")
                else:
                    lines.append("前 2 段：")
                    for item in candidate["before"]:
                        lines.append(f"- {item['line']}: {item['text']}")
                    lines.append("后 2 段：")
                    for item in candidate["after"]:
                        lines.append(f"- {item['line']}: {item['text']}")
                lines.append("")
            (self.report_dir / f"{stem}.txt").write_text(
                "\n".join(lines).rstrip() + "\n",
                encoding="utf-8",
            )
