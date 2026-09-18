"""小说正文质量检查与报告输出。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pixiv_novel_toolkit.chapters.markers import parse_chapter_marker
from pixiv_novel_toolkit.common.textio import read_text_lines
from .cleaning import find_blank_separated_author_note_blocks, is_suspected_hard_wrap


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")
_NUMBERED_CHAPTER_FILE_RE = re.compile(r"^\d+\s")


def _finding(rule, file_name, line, message, text="", *, severity="warning", context=None):
    result = {
        "rule": rule,
        "severity": severity,
        "file": file_name,
        "line": line,
        "message": message,
        "text": text,
    }
    if context is not None:
        result["context"] = context
    return result


def _line_context(lines, index, before, after):
    start = max(0, index - before)
    end = min(len(lines), index + after + 1)
    return [
        {"line": position + 1, "text": lines[position]}
        for position in range(start, end)
    ]


def audit_lines(lines, file_name, config):
    """检查单个文件的行列表并返回结构化问题清单。"""
    settings = config["audit"]
    findings = []

    decoding_rule = settings["decoding_anomalies"]
    if decoding_rule["enabled"]:
        for index, line in enumerate(lines):
            count = line.count("\ufffd")
            if count:
                findings.append(_finding(
                    "decoding_anomalies",
                    file_name,
                    index + 1,
                    f"本行含 {count} 个解码替换符，源文件可能存在损坏字节",
                    line.strip(),
                ))

    quote_rule = settings["quote_balance"]
    if quote_rule["enabled"]:
        content = "\n".join(lines)
        english = content.count('"')
        chinese_open = content.count("“")
        chinese_close = content.count("”")
        corner_open = content.count("「") + content.count("『")
        corner_close = content.count("」") + content.count("』")
        if english % 2 or chinese_open != chinese_close or corner_open != corner_close:
            findings.append(_finding(
                "quote_balance",
                file_name,
                None,
                "引号数量不配对",
                f'英文双引号 {english}；中文 “ {chinese_open}/” {chinese_close}；'
                f"直角引号 {corner_open}/{corner_close}",
            ))

    paragraph_rule = settings["long_paragraph"]
    if paragraph_rule["enabled"]:
        minimum = paragraph_rule.get("minimum_length", 339)
        for index, line in enumerate(lines):
            stripped = line.strip()
            if len(stripped) >= minimum:
                findings.append(_finding(
                    "long_paragraph",
                    file_name,
                    index + 1,
                    f"段落长度 {len(stripped)}，达到检查阈值 {minimum}",
                    stripped,
                ))

    duplicate_rule = settings["duplicate_lines"]
    if duplicate_rule["enabled"]:
        minimum = duplicate_rule.get("minimum_length", 4)
        for index in range(1, len(lines)):
            current = lines[index].strip()
            previous = lines[index - 1].strip()
            if current and len(current) >= minimum and current == previous:
                findings.append(_finding(
                    "duplicate_lines",
                    file_name,
                    index + 1,
                    "与上一行完全相同",
                    current,
                ))

    chapter_rule = settings["duplicate_chapter_titles"]
    if chapter_rule["enabled"]:
        nearby = chapter_rule.get("nearby_line_limit", 5)
        recent = {}
        for index, line in enumerate(lines):
            marker = parse_chapter_marker(line)
            if not marker:
                continue
            key = marker["num"] if marker["num"] is not None else marker["raw"]
            if key in recent and index - recent[key][0] <= nearby:
                previous_index, previous_text = recent[key]
                findings.append(_finding(
                    "duplicate_chapter_titles",
                    file_name,
                    index + 1,
                    f"与第 {previous_index + 1} 行的章节标记重复或编号相同",
                    f"{previous_text}  ->  {line.strip()}",
                ))
            recent[key] = (index, line.strip())

    title_anomaly_rule = settings["chapter_title_anomalies"]
    if title_anomaly_rule["enabled"]:
        missing_suffix_pattern = re.compile(
            r"^第[一二两三四五六七八九十百千万零0-9０-９]{1,12}[ \t　：:、，,]+.+$"
        )
        candidate_indexes = range(len(lines))
        if _NUMBERED_CHAPTER_FILE_RE.match(file_name):
            first_nonempty = next(
                (index for index, line in enumerate(lines) if line.strip()),
                None,
            )
            candidate_indexes = [] if first_nonempty is None else [first_nonempty]
        for index in candidate_indexes:
            line = lines[index]
            stripped = line.strip()
            marker = parse_chapter_marker(stripped)
            message = None
            if marker and marker["style"] in {"bare_chinese_sfx", "bare_sfx"}:
                message = "章节标记可能缺少“第”"
                if marker["title"] and not marker["sep"]:
                    message += "，且编号与标题粘连；默认不自动修复"
            elif marker and marker["style"] == "bare":
                message = "纯数字章节标记可能缺少“第/章”"
                if marker["title"] and not marker["sep"]:
                    message += "，且编号与标题粘连；默认不自动修复"
            elif missing_suffix_pattern.match(stripped):
                message = "章节标记可能缺少“章”"
            if message:
                findings.append(_finding(
                    "chapter_title_anomalies",
                    file_name,
                    index + 1,
                    message,
                    stripped,
                ))

    context_rule = settings["chapter_context"]
    if context_rule["enabled"]:
        maximum = context_rule.get("maximum_entries", 100)
        count = 0
        for index, line in enumerate(lines):
            if parse_chapter_marker(line) is None:
                continue
            findings.append(_finding(
                "chapter_context",
                file_name,
                index + 1,
                "章节标记前后文",
                line.strip(),
                severity="info",
                context=_line_context(
                    lines,
                    index,
                    context_rule.get("before", 2),
                    context_rule.get("after", 2),
                ),
            ))
            count += 1
            if maximum and count >= maximum:
                break

    advert_rule = settings["advertisement_keywords"]
    if advert_rule["enabled"]:
        keywords = advert_rule.get("keywords", [])
        for index, line in enumerate(lines):
            matched = [keyword for keyword in keywords if keyword and keyword in line]
            if matched:
                findings.append(_finding(
                    "advertisement_keywords",
                    file_name,
                    index + 1,
                    f"命中疑似广告/作者话关键词：{'、'.join(matched)}",
                    line.strip(),
                    context=_line_context(
                        lines,
                        index,
                        advert_rule.get("before", 2),
                        advert_rule.get("after", 2),
                    ),
                ))

    blank_note_rule = settings["blank_separated_author_notes"]
    if blank_note_rule["enabled"]:
        for block in find_blank_separated_author_note_blocks(lines, blank_note_rule):
            findings.append(_finding(
                "blank_separated_author_notes",
                file_name,
                block["line"],
                f"连续空行后发现疑似章末作者附言，共 {block['line_count']} 行",
                block["preview"],
            ))

    wrap_rule = settings["suspected_hard_wraps"]
    if wrap_rule["enabled"]:
        for index in range(len(lines) - 1):
            if is_suspected_hard_wrap(lines, index, wrap_rule):
                findings.append(_finding(
                    "suspected_hard_wraps",
                    file_name,
                    index + 1,
                    f"本行可能与第 {index + 2} 行属于同一句",
                    f"{lines[index].strip()} ↩ {lines[index + 1].strip()}",
                ))

    punctuation_rule = settings["punctuation_anomalies"]
    if punctuation_rule["enabled"]:
        for index, line in enumerate(lines):
            stripped = line.strip()
            if re.search(r"[\u4e00-\u9fff][”」』]$", stripped):
                findings.append(_finding(
                    "punctuation_anomalies",
                    file_name,
                    index + 1,
                    "右引号前可能缺少句末标点",
                    stripped,
                ))
            if stripped.endswith(("：", ":")):
                next_nonempty = next(
                    (candidate.strip() for candidate in lines[index + 1:] if candidate.strip()),
                    "",
                )
                if next_nonempty and not next_nonempty.startswith(("“", '"', "「", "『")):
                    findings.append(_finding(
                        "punctuation_anomalies",
                        file_name,
                        index + 1,
                        "冒号后的下一段未以开引号开始，请人工确认",
                        f"{stripped} ↩ {next_nonempty}",
                    ))
    return findings


class TextAuditor:
    """检查单个 TXT 或目录并生成 TXT/JSON 报告。"""

    def __init__(self, input_path, report_dir, config, *, report_format="both"):
        self.input_path = Path(input_path)
        self.report_dir = Path(report_dir)
        self.config = config
        self.report_format = report_format
        self.skipped_files = []

    def _input_files(self):
        if self.input_path.is_file():
            return [self.input_path]
        candidates = sorted(
            path for path in self.input_path.iterdir()
            if (
                path.is_file()
                and path.suffix.lower() == ".txt"
                and not path.name.startswith(("_", "000 "))
            )
        )
        files = [path for path in candidates if _NUMBERED_CHAPTER_FILE_RE.match(path.name)]
        self.skipped_files = [path.name for path in candidates if path not in files]
        if self.skipped_files:
            logger.info(
                "目录审计忽略 %d 个无数字前缀 TXT（可作为单文件单独审计）",
                len(self.skipped_files),
            )
        return files

    def run(self):
        findings = []
        files = self._input_files()
        for source in files:
            lines = read_text_lines(source, info=logger.info)
            findings.extend(audit_lines(lines, source.name, self.config))
        by_rule = {}
        for finding in findings:
            by_rule[finding["rule"]] = by_rule.get(finding["rule"], 0) + 1
        report = {
            "input": str(self.input_path),
            "file_count": len(files),
            "skipped_files": self.skipped_files,
            "finding_count": len(findings),
            "by_rule": by_rule,
            "findings": findings,
        }
        self._write_report(report)
        return report

    def _write_report(self, report):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        if self.report_format in {"json", "both"}:
            (self.report_dir / "audit_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if self.report_format not in {"txt", "both"}:
            return
        lines = [
            "# 文本质量检查报告",
            f"输入：{report['input']}",
            f"文件：{report['file_count']}，发现：{report['finding_count']}",
        ]
        if report["skipped_files"]:
            lines.append(
                "目录模式已忽略无数字前缀 TXT：" + "、".join(report["skipped_files"])
            )
        if report["by_rule"]:
            lines.append("规则统计：" + "、".join(
                f"{rule}={count}" for rule, count in sorted(report["by_rule"].items())
            ))
        lines.append("")
        if not report["findings"]:
            lines.append("未发现已启用规则能够识别的问题。")
        for finding in report["findings"]:
            location = finding["file"]
            if finding["line"] is not None:
                location += f":{finding['line']}"
            lines.append(
                f"## [{finding['severity']}] {finding['rule']} — {location}"
            )
            lines.append(finding["message"])
            if finding["text"]:
                lines.append(f"> {finding['text']}")
            if finding.get("context"):
                lines.append("上下文：")
                for item in finding["context"]:
                    lines.append(f"- {item['line']}: {item['text']}")
            lines.append("")
        (self.report_dir / "audit_report.txt").write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )
