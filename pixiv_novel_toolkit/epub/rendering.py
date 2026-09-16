"""EPUB 标题 HTML 与 CSS 的纯渲染逻辑。"""

from __future__ import annotations

import html
import re
from collections.abc import Callable


WarningCallback = Callable[[str], None] | None
COLOR_PATTERN = r"[#0-9a-zA-Z(),.%\s-]+"
SIZE_PATTERN = r"[0-9]+(\.[0-9]+)?\s*(em|px|pt|%|rem)"


def _warn(callback: WarningCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def validate_css_value(
    value: str,
    pattern: str,
    what: str,
    *,
    warning: WarningCallback = None,
):
    """限制 CSS 值的字符集合，非法时返回 ``None``。"""
    if value and not re.fullmatch(pattern, value.strip()):
        _warn(warning, f"章标题{what} {value!r} 不是合法的 CSS 值，已忽略该项设置")
        return None
    return value.strip() if value else value


def split_chapter_title(display_title: str) -> tuple[str | None, str]:
    """把章节标题拆成章节号和章节名；无法识别时保留完整标题。"""
    match = re.match(r"^番外[：:]\s*(.+)$", display_title)
    if match:
        return "番外", match.group(1).strip()
    match = re.match(r"^番外\s+(.+)$", display_title)
    if match:
        return "番外", match.group(1).strip()
    match = re.match(
        r"^((?:第)?[0-9一二三四五六七八九十百千万零两点.]+[章话回节])\s+(.+)$",
        display_title,
    )
    if match:
        return match.group(1), match.group(2).strip()
    return None, display_title


def build_chapter_title_html(display_title: str, style: dict) -> str:
    """根据 chapter 样式生成标题元素内部 HTML。"""
    if style.get("split", False):
        number, name = split_chapter_title(display_title)
        if number is not None:
            return (
                f'<div class="chapter-num">{html.escape(number)}</div>'
                f'<div class="chapter-name">{html.escape(name)}</div>'
            )
    return html.escape(display_title)


def split_volume_title(name: str) -> tuple[str | None, str]:
    """把卷标题拆成卷号和卷名；无法识别时保留完整标题。"""
    match = re.match(
        r"^(第[一二三四五六七八九十百千万零两0-9.]+[卷部篇集]|番外(?:篇)?)\s*(.*)$",
        name,
    )
    if match and match.group(2).strip():
        return match.group(1).strip(), match.group(2).strip()
    return None, name


def build_volume_title_html(name: str, style: dict) -> str:
    """根据 volume 样式生成卷标题 HTML。"""
    if style.get("vol_split", True):
        number, volume_name = split_volume_title(name)
        if number is not None:
            return (
                f'<div class="volume-num">{html.escape(number)}</div>'
                f'<div class="volume-name">{html.escape(volume_name)}</div>'
            )
    return f'<div class="volume-name">{html.escape(name)}</div>'


def build_book_info_body(
    info: dict,
    title: str,
    author: str,
    *,
    maker: str | None = None,
) -> str:
    """把书籍信息字段渲染成信息页正文 HTML。"""
    paragraphs = [
        f'<p class="book-info-name">{html.escape(title)}</p>',
        f'<p>{html.escape("作者：" + (author or "未填"))}</p>',
    ]
    if info.get("platform"):
        paragraphs.append(f'<p>{html.escape("连载平台：" + info["platform"])}</p>')
    if info.get("status"):
        paragraphs.append(f'<p>{html.escape("连载状态：" + info["status"])}</p>')
    if info.get("vol_count"):
        paragraphs.append(f'<p>{html.escape("卷/篇数：" + info["vol_count"])}</p>')
    if info.get("word_count"):
        paragraphs.append(f'<p>{html.escape("字数：" + info["word_count"])}</p>')
    effective_maker = maker or info.get("maker")
    if effective_maker:
        paragraphs.append(f'<p>{html.escape("EPUB制作：" + effective_maker)}</p>')
    description = (info.get("description") or "").strip()
    if description and description != "未填":
        paragraphs.append("<p>简介：</p>")
        paragraphs.extend(
            f"<p>{html.escape(line.strip())}</p>"
            for line in description.splitlines()
            if line.strip()
        )
    return "\n".join(paragraphs)


def build_volume_css(style: dict, *, warning: WarningCallback = None) -> str:
    """生成卷页标题 CSS。"""
    volume_color = validate_css_value(
        style.get("vol_color", "#8B0000"), COLOR_PATTERN, "卷名颜色", warning=warning
    )
    volume_size = validate_css_value(
        style.get("vol_size", "2.5em"), SIZE_PATTERN, "卷名字号", warning=warning
    )
    if volume_color is None:
        volume_color = "#8B0000"
    if volume_size is None:
        volume_size = "2.5em"

    rules = [
        ".volume-title {",
        "    display: block;",
        "    font-weight: bold;",
        "    text-align: center;",
        "    text-indent: 0;",
        "    border-bottom: none;",
        "    margin-top: 0;",
        "    padding-top: 35%;",
    ]
    if style.get("vol_split", True):
        rules.append("}")
        number_color = validate_css_value(
            style.get("vol_num_color", "#555555"),
            COLOR_PATTERN,
            "卷号颜色",
            warning=warning,
        )
        number_size = validate_css_value(
            style.get("vol_num_size", "1.2em"), SIZE_PATTERN, "卷号字号", warning=warning
        )
        gap = validate_css_value(
            style.get("vol_gap", "0.6em"), SIZE_PATTERN, "卷号间距", warning=warning
        )
        number_color = number_color if number_color is not None else "#555555"
        number_size = number_size if number_size is not None else "1.2em"
        gap = gap if gap is not None else "0.6em"
        rules.extend(
            [
                ".volume-title .volume-num {",
                "    display: block;",
                f"    font-size: {number_size};",
                f"    color: {number_color};",
                f"    margin-bottom: {gap};",
                "}",
                ".volume-title .volume-name {",
                "    display: block;",
                f"    font-size: {volume_size};",
                f"    color: {volume_color};",
                "}",
            ]
        )
    else:
        rules.extend([f"    font-size: {volume_size};", f"    color: {volume_color};", "}"])
    return "\n".join(rules) + "\n"


def build_chapter_title_css(style: dict, *, warning: WarningCallback = None) -> str:
    """生成章标题 CSS，包括可选的章节号/章名双行规则。"""
    align = style.get("align", "center")
    if align not in ("center", "left"):
        _warn(warning, f"章标题对齐方式 {align!r} 无效，仅支持 center/left，已回退 center")
        align = "center"

    color = validate_css_value(style.get("color", ""), COLOR_PATTERN, "颜色", warning=warning)
    size = validate_css_value(style.get("size", "1.5em"), SIZE_PATTERN, "字号", warning=warning)
    size = size if size is not None else "1.5em"
    rules = [
        f"    text-align: {align};",
        f"    font-size: {size};",
        "    font-weight: bold;",
        "    line-height: 1.5;",
        "    text-indent: 0;",
    ]
    if color:
        rules.append(f"    color: {color};")
    if style.get("underline", False):
        line_color = color or "#8B0000"
        rules.extend(
            [
                f"    border-bottom: {line_color} solid 2px;",
                "    padding-bottom: 0.5em;",
                "    margin: 0 0 0.8em;",
            ]
        )
    else:
        rules.append("    margin: 0 0 2em 0;")
    css = "\n".join(rules) + "\n}"

    if style.get("split", False):
        number_color = validate_css_value(
            style.get("num_color", ""), COLOR_PATTERN, "章节号颜色", warning=warning
        )
        number_size = validate_css_value(
            style.get("num_size", "1em"), SIZE_PATTERN, "章节号字号", warning=warning
        )
        number_color = number_color if number_color is not None else color or ""
        number_size = number_size if number_size is not None else "1em"
        span_rules = [
            "h1.chapter-title .chapter-num {",
            "    display: block;",
            f"    font-size: {number_size};",
            "    line-height: 1.4;",
            "    margin-bottom: 0.35em;",
        ]
        if number_color:
            span_rules.append(f"    color: {number_color};")
        span_rules.extend(
            [
                "}",
                "h1.chapter-title .chapter-name {",
                "    display: block;",
                "}",
            ]
        )
        css += "\n" + "\n".join(span_rules) + "\n"
    return css
