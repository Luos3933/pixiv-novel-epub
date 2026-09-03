"""下载阶段可独立复用的文本与参数解析函数。"""

import re


def clean_filename(filename):
    """清理 Windows 不允许出现在文件名中的字符。"""
    return re.sub(r'[\/\\\:\*\?\"\<\>\|]', "_", filename)


def clean_html(raw_html):
    """将 Pixiv 简介中的简单 HTML 转换为纯文本。"""
    if not raw_html:
        return ""
    text = raw_html.replace("<br />", "\n").replace("<br>", "\n")
    clean_text = re.sub(r"<[^>]+>", "", text)
    return (
        clean_text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


def parse_chapter_selection(selection_text, total_chapters):
    """解析单章或闭区间章节选择；留空时返回全部章节位置。"""
    selection_text = (selection_text or "").strip()
    if not selection_text:
        return list(range(1, total_chapters + 1))

    match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", selection_text)
    if not match:
        raise ValueError("Invalid chapter selection format. Use '11' or '11-21'.")

    start_num = int(match.group(1))
    end_num = int(match.group(2) or start_num)
    if start_num > end_num:
        raise ValueError("The chapter range start cannot be greater than the end.")
    if start_num < 1 or end_num > total_chapters:
        raise ValueError(
            f"Chapter selection is out of range. Available chapters: 1-{total_chapters}."
        )
    return list(range(start_num, end_num + 1))


def extract_tag_names(tags_data):
    """将 Pixiv 的标签变体结构统一转换为保序去重的名称列表。"""
    tag_names = []
    if isinstance(tags_data, dict):
        candidates = tags_data.get("tags") or tags_data.get("items") or []
    else:
        candidates = tags_data or []

    for item in candidates:
        if isinstance(item, dict):
            tag_name = (
                item.get("tag")
                or item.get("name")
                or item.get("translation")
                or item.get("userTag")
            )
            if isinstance(tag_name, dict):
                tag_name = tag_name.get("en") or tag_name.get("romaji") or tag_name.get("name")
        else:
            tag_name = str(item).strip()

        if tag_name:
            tag_names.append(str(tag_name).strip())
    return list(dict.fromkeys(tag_names))
