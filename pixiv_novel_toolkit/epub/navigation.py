"""EPUB manifest、OPF 与两套目录导航的纯生成逻辑。"""

from __future__ import annotations

import html
import os
from datetime import datetime, timezone

from .templates import NAV_TEMPLATE, NCX_TEMPLATE


def image_mimetype(path: str) -> str:
    """根据扩展名返回 EPUB manifest 使用的图片 MIME 类型。"""
    extension = os.path.splitext(path)[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(extension, "image/jpeg")


def render_content_opf(
    title: str,
    author: str,
    info: dict,
    uid: str,
    spine_items: list[dict],
    *,
    cover_img_name: str | None = None,
    used_images: dict | None = None,
    modified: str | None = None,
) -> str:
    """生成 EPUB 3 ``content.opf``，同时保留 EPUB 2 封面兼容字段。"""
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    if cover_img_name:
        manifest_items.append(
            f'<item id="cover-img" href="{cover_img_name}" '
            f'media-type="{image_mimetype(cover_img_name)}" properties="cover-image"/>'
        )
    for image_name in sorted(used_images or {}):
        manifest_items.append(
            f'<item id="img-{len(manifest_items)}" href="img/{image_name}" '
            f'media-type="{image_mimetype(image_name)}"/>'
        )

    itemrefs = []
    for item in spine_items:
        manifest_items.append(
            f'<item id="{item["id"]}" href="{item["fname"]}" '
            'media-type="application/xhtml+xml"/>'
        )
        itemrefs.append(f'<itemref idref="{item["id"]}"/>')

    modified = modified or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = [
        f"<dc:title>{html.escape(title)}</dc:title>",
        f"<dc:creator>{html.escape(author)}</dc:creator>",
        "<dc:language>zh-CN</dc:language>",
        f'<meta property="dcterms:modified">{modified}</meta>',
    ]
    if cover_img_name:
        metadata.append('<meta name="cover" content="cover-img"/>')
    if info.get("description") and info["description"] != "未填":
        metadata.append(f'<dc:description>{html.escape(info["description"])}</dc:description>')
    if info.get("status"):
        metadata.append(f'<meta name="pixiv:status" content="{html.escape(info["status"])}"/>')
    if info.get("word_count"):
        metadata.append(
            f'<meta name="pixiv:word_count" content="{html.escape(info["word_count"])}"/>'
        )

    guide = ""
    if cover_img_name:
        guide = (
            "\n  <guide>\n"
            '    <reference type="cover" title="封面" href="cover.xhtml"/>\n'
            "  </guide>"
        )

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="zh-CN">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
{chr(10).join(metadata)}
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(itemrefs)}
  </spine>{guide}
</package>'''


def render_toc_ncx(
    title: str,
    uid: str,
    spine_items: list[dict],
    *,
    template: str = NCX_TEMPLATE,
) -> str:
    """生成 EPUB 2 NCX 目录，卷条目包含嵌套章节。"""
    points = []
    order = 0

    def open_point(filename, text):
        nonlocal order
        order += 1
        return (
            f'<navPoint id="np_{order}" playOrder="{order}">'
            f"<navLabel><text>{html.escape(text)}</text></navLabel>"
            f'<content src="{filename}"/>'
        )

    index = 0
    while index < len(spine_items):
        item = spine_items[index]
        if item["kind"] == "vol":
            volume_index = item["vol"]
            index += 1
            children = []
            while (
                index < len(spine_items)
                and spine_items[index]["kind"] == "chap"
                and spine_items[index].get("vol") == volume_index
            ):
                children.append(spine_items[index])
                index += 1
            parent = open_point(item["fname"], item["title"])
            inner = "".join(
                open_point(child["fname"], child["title"]) + "</navPoint>"
                for child in children
            )
            points.append(parent + inner + "</navPoint>")
        else:
            points.append(open_point(item["fname"], item["title"]) + "</navPoint>")
            index += 1
    return template.format(uid=uid, title=html.escape(title), points="\n".join(points))


def render_nav_xhtml(
    spine_items: list[dict],
    *,
    template: str = NAV_TEMPLATE,
) -> str:
    """生成 EPUB 3 XHTML 导航，卷条目包含嵌套章节。"""
    navigation_items = []
    index = 0
    while index < len(spine_items):
        item = spine_items[index]
        if item["kind"] == "vol":
            volume_index = item["vol"]
            index += 1
            children = []
            while (
                index < len(spine_items)
                and spine_items[index]["kind"] == "chap"
                and spine_items[index].get("vol") == volume_index
            ):
                children.append(spine_items[index])
                index += 1
            inner = "\n".join(
                f'<li><a href="{child["fname"]}">{html.escape(child["title"])}</a></li>'
                for child in children
            )
            navigation_items.append(
                f'<li><a href="{item["fname"]}">{html.escape(item["title"])}</a>\n'
                f"<ol>\n{inner}\n</ol>\n</li>"
            )
        else:
            navigation_items.append(
                f'<li><a href="{item["fname"]}">{html.escape(item["title"])}</a></li>'
            )
            index += 1
    return template.format(items="\n".join(navigation_items))

