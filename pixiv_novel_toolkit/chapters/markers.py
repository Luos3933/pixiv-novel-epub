"""章节标记解析。

这里存放 split、toc 和 epub 共用的纯解析逻辑，避免通过实例化
``VolumeSplitter`` 来借用其私有方法。
"""

from __future__ import annotations

import re


MARKER_RE = re.compile(r"^第([一二三四五六七八九十百千万零两0-9.]+)([章话节回])")
FANWAI_RE = re.compile(r"^番外([：:\s].*)?$")
BARE_SUFFIX_RE = re.compile(r"^(\d{1,4})([章话节回])")
BARE_HEAD_RE = re.compile(r"^(\d{1,4})")

# 无分隔符粘连标题中应排除的日期、数量词和正文常见起始字。
GLUED_BLOCK_CHARS = "年月日时分秒个十百千万亿倍元斤米人次度里的是在和与就才都很也又把被让给"
GLUED_QUANTITY_STARTERS = "年月日时分秒个十百千万亿倍元斤米人次度里多约近余"


def chapter_number_to_chinese(num: int) -> str:
    """阿拉伯数字转中文数字，如 43 -> 四十三。"""
    zh_num = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    zh_unit = ["", "十", "百", "千", "万"]
    if num == 0:
        return zh_num[0]
    result = ""
    num_str = str(num)
    length = len(num_str)
    for index, char in enumerate(num_str):
        digit = int(char)
        if digit != 0:
            result += zh_num[digit] + zh_unit[length - index - 1]
        elif not result.endswith("零"):
            result += "零"
    result = result.rstrip("零")
    if result.startswith("一十"):
        result = result[1:]
    return result


def chinese_chapter_number_to_int(text: str) -> int | None:
    """中文章节数字转整数；兼容 ``一四四`` 这种逐位写法。"""
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if not text:
        return None
    if all(char in digits for char in text):
        if len(text) > 4:
            return None
        value = int("".join(str(digits[char]) for char in text))
        return value if value > 0 else None

    total = 0
    section = 0
    number = 0
    for char in text:
        if char in digits:
            number = digits[char]
        elif char in units:
            unit = units[char]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
            if unit == 10000:
                total = (total + section) * unit
                section = 0
        else:
            return None
    total += section + number
    return total if total > 0 else None


def _marker(raw, number, style, suffix, separator, title):
    return {
        "raw": raw,
        "num": number,
        "style": style,
        "suffix": suffix,
        "sep": separator,
        "title": title,
    }


def _split_separator_and_title(rest: str) -> tuple[str, str]:
    if not rest:
        return "", ""
    first = rest[0]
    if first in "：:、，,":
        return first, rest[1:].strip()
    if first.isspace():
        return " ", rest.strip()
    return "", rest.strip()


def parse_chapter_marker(
    line: str,
    *,
    marker_max_len: int = 40,
    title_len_limit: bool = False,
):
    """解析单行章节标记，返回兼容旧代码的字典；非标记返回 ``None``。"""
    text = line.strip()
    if not text or len(text) > marker_max_len:
        return None

    match = MARKER_RE.match(text)
    if match:
        rest = text[match.end() :]
        if rest and not rest[0].isspace() and rest[0] not in "：:、，,":
            if "。" in text or (title_len_limit and len(text) > 20):
                return None
        number_text = match.group(1)
        suffix = match.group(2)
        separator, title = _split_separator_and_title(rest)
        if re.fullmatch(r"\d+", number_text):
            return _marker(text, int(number_text), "arabic", suffix, separator, title)
        number = chinese_chapter_number_to_int(number_text)
        if number is not None:
            return _marker(text, number, "chinese", suffix, separator, title)
        return _marker(text, None, None, suffix, separator, title)

    if FANWAI_RE.match(text):
        if "。" in text:
            return None
        return _marker(text, None, "fanwai", None, "", text)

    match = BARE_SUFFIX_RE.match(text)
    if match:
        rest = text[match.end() :]
        glued = bool(rest) and not rest[0].isspace() and rest[0] not in "：:、，,"
        if "。" in text or (glued and title_len_limit and len(text) > 20):
            return None
        separator, title = _split_separator_and_title(rest)
        return _marker(text, int(match.group(1)), "bare_sfx", match.group(2), separator, title)

    match = BARE_HEAD_RE.match(text)
    if match and len(text) > match.end():
        rest = text[match.end() :]
        first = rest[0]
        if first in "：:、，,":
            title = rest[1:].strip()
            if "。" not in text:
                return _marker(text, int(match.group(1)), "bare", None, first, title)
        elif first.isspace():
            title = rest.strip()
            if "。" not in text:
                return _marker(text, int(match.group(1)), "bare", None, " ", title)
        elif (
            "。" not in text
            and first not in GLUED_BLOCK_CHARS
            and not (title_len_limit and len(text) > 20)
        ):
            return _marker(text, int(match.group(1)), "bare", None, "", rest.strip())
    return None


def unify_chapter_marker(marker: dict, *, num_style: str = "chinese") -> dict:
    """把可编号标记统一为 ``第X章 章名`` 形式。"""
    suffix = marker["suffix"] or "章"
    if num_style == "arabic":
        number_text, style = str(marker["num"]), "arabic"
    else:
        number_text, style = chapter_number_to_chinese(marker["num"]), "chinese"
    title = marker["title"].strip()
    raw = f"第{number_text}{suffix} {title}" if title else f"第{number_text}{suffix}"
    return {
        "raw": raw,
        "num": marker["num"],
        "style": style,
        "suffix": suffix,
        "sep": " " if title else "",
        "title": title,
    }

