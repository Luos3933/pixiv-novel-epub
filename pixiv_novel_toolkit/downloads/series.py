"""Pixiv 系列分页响应解析、元数据聚合与章节任务规划。"""

from .parsing import clean_html, extract_tag_names


def initial_series_metadata(series_id):
    """生成系列信息的稳定初始结构。"""
    return {
        "title": f"series_{series_id}",
        "author": "",
        "description": "",
        "update_time": "",
        "word_count": 0,
        "chapter_count": 0,
        "tags": [],
    }


def parse_series_overview(overview, series_id):
    """把独立系列总览接口转换为内部统一字段。"""
    metadata = initial_series_metadata(series_id)
    metadata.update(
        {
            "title": (
                overview.get("title")
                or overview.get("seriesTitle")
                or overview.get("name")
                or metadata["title"]
            ),
            "author": (
                overview.get("userName")
                or overview.get("authorName")
                or overview.get("user", {}).get("name")
                or ""
            ),
            "description": clean_html(
                overview.get("caption")
                or overview.get("description")
                or overview.get("content")
                or ""
            ),
            "update_time": (
                overview.get("updateDate")
                or overview.get("createDate")
                or overview.get("publishedDate")
                or ""
            ),
            "tags": extract_tag_names(overview.get("tags")),
        }
    )
    return metadata


def merge_series_page_metadata(metadata, data, contents, series_id):
    """当总览信息缺失时，沿用旧规则从第一页章节响应补齐字段。"""
    merged = dict(metadata)
    fallback_title = f"series_{series_id}"
    if not contents or merged.get("title") != fallback_title:
        return merged

    body = data.get("body", {}) or {}
    first_item = contents[0]
    merged["title"] = (
        body.get("title")
        or body.get("seriesTitle")
        or body.get("name")
        or first_item.get("seriesTitle")
        or first_item.get("title")
        or fallback_title
    )
    merged["author"] = (
        merged.get("author")
        or first_item.get("userName")
        or first_item.get("authorName")
        or ""
    )
    if not merged.get("update_time"):
        merged["update_time"] = (
            first_item.get("updateDate") or first_item.get("createDate") or ""
        )
    if not merged.get("tags"):
        merged["tags"] = extract_tag_names(first_item.get("tags"))
    if not merged.get("description"):
        merged["description"] = clean_html(
            body.get("caption") or body.get("description") or ""
        )
    return merged


def collect_series_page(contents):
    """返回分页中的小说 ID 列表与接口口径字数合计。"""
    chapter_ids = []
    word_count = 0
    for item in contents:
        chapter_ids.append(item["id"])
        word_count += item.get("textCount") or item.get("wordCount") or 0
    return chapter_ids, word_count


def normalize_series_update_time(raw_time):
    """将 Pixiv ISO 风格时间截断为旧版 info.txt 使用的格式。"""
    return raw_time.replace("T", " ")[:19] if raw_time else raw_time


def render_series_info(series_id, series_info):
    """渲染系列说明文件内容。"""
    tags = series_info.get("tags") or []
    tags_text = "、".join(tags) if tags else "无"
    lines = [
        f"系列ID: {series_id}",
        f"系列名称: {series_info.get('title') or '未知系列'}",
        f"作者: {series_info.get('author') or '未知作者'}",
        f"更新时间: {series_info.get('update_time') or '未知时间'}",
        f"总字数: {series_info.get('word_count') or 0}",
        f"章节数: {series_info.get('chapter_count') or 0}",
        f"标签: {tags_text}",
        "",
        "简介:",
        series_info.get("description") or "（暂无简介）",
    ]
    return "\n".join(lines)


def extract_series_contents(data):
    """兼容 Pixiv 系列接口已出现过的两种章节列表结构。"""
    body = data.get("body", {}) or {}
    contents = body.get("seriesContents", [])
    if not contents:
        contents = (body.get("page", {}) or {}).get("seriesContents", [])
    return contents or []


def next_series_cursor(contents, current_cursor, page_limit):
    """依据末条真实 order 计算下一页游标，缺失时回退固定步长。"""
    if contents:
        last_order = contents[-1].get("order")
        if last_order is not None:
            return last_order
    return current_cursor + page_limit


def build_series_tasks(chapter_ids, selected_positions, start_chapter, preserve_positions=False):
    """把选中章节转换为 ``(三位章号, novel_id)`` 下载任务。"""
    current_num = int(start_chapter)
    tasks = []
    for offset, novel_id in enumerate(chapter_ids):
        actual_position = selected_positions[offset]
        save_num = actual_position if preserve_positions else current_num
        tasks.append((f"{save_num:03d}", novel_id))
        if not preserve_positions:
            current_num += 1
    return tasks
