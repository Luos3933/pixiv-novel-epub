"""EPUB 构建器编排。"""

import html
import io
import json
import logging
import os
from pathlib import Path
import re
import uuid
import zipfile

from pixiv_novel_toolkit.chapters.markers import parse_chapter_marker
from pixiv_novel_toolkit.chapters.overlay import collect_text_overlay
from pixiv_novel_toolkit.chapters.volumes import load_volumes_file
from pixiv_novel_toolkit.epub.rendering import (
    build_book_info_body,
    build_chapter_title_css,
    build_chapter_title_html,
    build_volume_css,
    build_volume_title_html,
    split_chapter_title,
    split_volume_title,
    validate_css_value,
)
from pixiv_novel_toolkit.epub.illustrations import (
    ILLUSTRATION_MARKER_RE as EPUB_ILLUSTRATION_MARKER_RE,
    parse_illustrations_file,
    parse_illustrations_json,
    parse_illustrations_text,
)
from pixiv_novel_toolkit.epub.navigation import (
    image_mimetype,
    render_content_opf,
    render_nav_xhtml,
    render_toc_ncx,
)
from pixiv_novel_toolkit.epub.planning import plan_spine
from pixiv_novel_toolkit.epub.styles import load_style_presets, parse_style_section
from pixiv_novel_toolkit.epub.templates import (
    BOOK_INFO_TEMPLATE as EPUB_BOOK_INFO_TEMPLATE,
    CHAPTER_TEMPLATE as EPUB_CHAPTER_TEMPLATE,
    CONTAINER_XML as EPUB_CONTAINER_XML,
    COVER_TEMPLATE as EPUB_COVER_TEMPLATE,
    CSS as EPUB_CSS,
    DEFAULT_TITLE_STYLE as EPUB_DEFAULT_TITLE_STYLE,
    DEFAULT_VOLUME_STYLE as EPUB_DEFAULT_VOLUME_STYLE,
    NAV_TEMPLATE as EPUB_NAV_TEMPLATE,
    NCX_TEMPLATE as EPUB_NCX_TEMPLATE,
    STYLE_SAMPLE as EPUB_STYLE_SAMPLE,
    VOLUME_TEMPLATE as EPUB_VOLUME_TEMPLATE,
)
from pixiv_novel_toolkit.postprocess.book_info import parse_book_info_file
from pixiv_novel_toolkit.postprocess.book_info_generator import BookInfoGenerator


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


def _load_volumes_file(volumes_file):
    return load_volumes_file(
        volumes_file,
        error=logger.error,
        warning=logger.warning,
        info=logger.info,
    )


class EpubBuilder:
    """
    把章节目录打包为 EPUB 电子书（纯标准库实现，零第三方依赖）。

    打包结构（参照 FanFicFare / lncrawl 的手写方案，仅用 zipfile 与字符串模板）：
        <输出>.epub
        ├── mimetype                 # 固定 application/epub+zip，必须第一个写入且不压缩 (ZIP_STORED)
        ├── META-INF/container.xml   # 指向 OEBPS/content.opf
        └── OEBPS/
            ├── content.opf          # 元数据 + 文件清单 manifest + 阅读顺序 spine
            ├── toc.ncx              # EPUB2 目录（兼容老阅读器）
            ├── nav.xhtml            # EPUB3 目录导航
            ├── style.css            # 中文排版样式
            ├── vol_001.xhtml ...    # 卷/篇页（可选，独立占页，每卷一个）
            └── chap_001.xhtml ...   # 每章一个 XHTML

    章节收集：与 merge 相同的多目录配对语义（按数字前缀，后列目录优先，
    校正版覆盖标准化版）；"000 书籍信息.txt" 视为元数据不进入章节。

    卷/篇（可选）：通过 --volumes 传入 JSON 配置文件（见 _load_volumes 的格式说明），
    每卷生成一个独立占页的 vol_<n>.xhtml（卷名垂直居中），并在 toc.ncx / nav.xhtml
    目录中作为章节的上级嵌套；未配置卷时行为与旧版完全一致。

    元数据：优先解析输入目录里的 000 书籍信息.txt（从优先级最高的目录往前找），
    其次回退 pixiv 系列 info.txt / metadata.json（复用 BookInfoGenerator），
    最后用占位值；--title / --author 可显式覆盖。
    """

    # ---- 模板（参照 lncrawl 的 assets/epub 模板文件思路，此处内置为类常量） ----
    CHAPTER_TEMPLATE = EPUB_CHAPTER_TEMPLATE

    # 卷/篇页：独立占页，卷名垂直居中（CSS 见 .volume-page / .volume-title；可拆两行）
    VOLUME_TEMPLATE = EPUB_VOLUME_TEMPLATE

    # 书籍信息页：按 000 书籍信息.txt 的段落格式渲染（有真实信息来源才生成）
    BOOK_INFO_TEMPLATE = EPUB_BOOK_INFO_TEMPLATE

    # 封面页：图片自适应占满一页（有封面文件时生成，spine 第一位）
    COVER_TEMPLATE = EPUB_COVER_TEMPLATE

    NAV_TEMPLATE = EPUB_NAV_TEMPLATE

    NCX_TEMPLATE = EPUB_NCX_TEMPLATE

    CONTAINER_XML = EPUB_CONTAINER_XML

    # 中文排版：首行缩进 2em、1.8 倍行距、两端对齐
    # 卷/篇页：独立占页（前后强制分页）+ 卷名垂直居中（padding-top 35% 兼容性最好）
    # 章标题样式由 _build_title_css 生成（对齐/颜色/字号/下划线均可配置）
    CSS = EPUB_CSS

    # 章标题默认样式：居中、1.5em、无颜色、无下划线（与 v0.7.x 旧版行为一致）
    # split=True 时章节号与章名拆两行显示（第一行 .chapter-num，第二行 .chapter-name），
    # num_color / num_size 控制章节号行，color / size 控制章名行
    DEFAULT_TITLE_STYLE = EPUB_DEFAULT_TITLE_STYLE

    # 卷名默认样式：拆两行（卷号小灰 + 卷名大号深红，中间留间距）
    DEFAULT_VOLUME_STYLE = EPUB_DEFAULT_VOLUME_STYLE

    # 样式预设示例模板（首次运行时若无 epub_styles.json 会自动生成此内容）
    # 分两段：chapter = 章标题样式，volume = 卷名样式，分别由 --title-style / --vol-style 调用
    STYLE_SAMPLE = EPUB_STYLE_SAMPLE

    @classmethod
    def load_presets(cls, styles_file=None):
        """
        读取样式预设文件（默认项目根目录 epub_styles.json），分两段：
            {
                "chapter": { 样式名 -> {align, color, size, underline, split, num_color, num_size, desc} },
                "volume":  { 样式名 -> {vol_split, vol_num_color, vol_num_size, vol_color, vol_size, vol_gap, desc} }
            }
        "chapter" 段由 --title-style 调用，"volume" 段由 --vol-style 调用。

        文件不存在时自动生成示例模板文件（chapter 含 default / split_title，
        volume 含 default）。旧版扁平格式（顶层直接是样式名）按章节预设兼容读取。

        返回 {"chapter": {...}, "volume": {...}}；解析失败返回空两段 dict。
        """
        if styles_file is None:
            styles_file = str(Path(__file__).resolve().parents[2] / "epub_styles.json")
        return load_style_presets(
            styles_file,
            sample=cls.STYLE_SAMPLE,
            warning=logger.warning,
            info=logger.info,
        )

    @staticmethod
    def _parse_styles(styles, volume=False):
        """解析一段样式预设（volume=False 为章节样式，True 为卷名样式）。"""
        return parse_style_section(styles, volume=volume, warning=logger.warning)

    def __init__(self, input_folders, output_file, title=None, author=None,
                 volumes_file=None, title_style=None, vol_style=None, cover=None,
                 illustrations_file=None, image_quality=None, maker=None):
        """
        参数:
        - input_folders: 章节 txt 目录，可传单个字符串或列表；
                         列表时后面的目录优先级高（同名/同前缀章节取后者的版本）。
        - output_file: 输出的 .epub 文件路径
        - title / author: 可选，显式覆盖元数据中的书名/作者
        - maker: 可选，制作人署名（如 Laffey）；书籍信息页在"字数"行后渲染
                 "EPUB制作：<maker>" 行；未指定时回退 000 书籍信息.txt 中的
                 制作人行（TXT制作/EPUB制作/制作人）
        - volumes_file: 可选，卷/篇配置文件路径（JSON，见 _load_volumes）
        - title_style: 可选 dict，章标题样式：
            align: 'center' 或 'left'（对齐方式）
            color: CSS 颜色（如 '#8B0000'），空串表示继承正文黑色
            size: CSS 字号（如 '1.5em'）
            underline: True 时标题下加与 color 同色的 2px 实线
        - vol_style: 可选 dict，卷名样式：
            vol_split: 是否拆两行（默认 True）
            vol_num_color / vol_num_size: 卷号行颜色/字号
            vol_color / vol_size: 卷名行颜色/字号
            vol_gap: 两行之间的间距
        - cover: 可选，显式指定封面图片路径；不指定时自动查找输入目录
                 及其父目录下的 cover.* / 封面.* 图片
        - illustrations_file: 可选，插图信息文件路径（见 _parse_illustrations_file）；
                 不指定时自动查找输入目录中的 插图信息.txt
        - image_quality: 可选，1-100 的 JPEG 压缩质量；设置后插图用 Pillow 重编码
                 为 JPEG（PNG/JPEG 均可，压缩后未变小则保留原图），未设置不压缩
        """
        if isinstance(input_folders, str):
            input_folders = [input_folders]
        self.input_folders = input_folders
        self.output_file = output_file
        self.overrides = {"title": title, "author": author}
        self.maker = maker
        self.volumes_file = volumes_file
        self.cover = cover
        self.illustrations_file = illustrations_file
        self.image_quality = image_quality
        # 合并默认样式，用户只覆盖提供的项
        self.title_style = dict(self.DEFAULT_TITLE_STYLE)
        if title_style:
            self.title_style.update(title_style)
        self.vol_style = dict(self.DEFAULT_VOLUME_STYLE)
        if vol_style:
            self.vol_style.update(vol_style)

    # ---- 插图 ----

    ILLUSTRATION_MARKER_RE = EPUB_ILLUSTRATION_MARKER_RE

    def _find_illustration_dirs(self):
        """收集插图库候选目录（输入目录及其父目录下的 插图库/ 或 illustrations/）。"""
        dirs = []
        seen = set()
        for d in reversed(self.input_folders):
            for base in (d, os.path.dirname(os.path.abspath(d))):
                for sub in ("插图库", "illustrations"):
                    c = os.path.join(base, sub)
                    if os.path.isdir(c) and c not in seen:
                        seen.add(c)
                        dirs.append(c)
        return dirs

    def _find_image(self, img_name):
        """在插图库候选目录中查找图片文件，返回路径；找不到返回 None。"""
        for d in self._find_illustration_dirs():
            path = os.path.join(d, img_name)
            if os.path.isfile(path):
                return path
        return None

    def _maybe_compress_image(self, img_name, path):
        """
        按 self.image_quality 压缩插图（Pillow 重编码为 JPEG）。
        返回 (zip_name, data_or_path)：
          - 未启用压缩 / 无 Pillow / 压缩失败 / 压缩后未变小 -> (img_name, path) 原样
          - 压缩成功 -> (新文件名 <原名>_q<质量>.jpg, bytes)
        """
        if not self.image_quality:
            return img_name, path
        try:
            from PIL import Image
        except ImportError:
            logger.warning("未安装 Pillow，跳过插图压缩（可执行 pip install Pillow 启用）")
            self.image_quality = None  # 本次会话不再尝试
            return img_name, path
        try:
            with Image.open(path) as im:
                rgb = im.convert('RGB')
                buf = io.BytesIO()
                rgb.save(buf, format='JPEG', quality=self.image_quality, optimize=True)
                data = buf.getvalue()
        except Exception as e:
            logger.warning(f"插图压缩失败，使用原图 {img_name}: {e}")
            return img_name, path
        if len(data) >= os.path.getsize(path):
            logger.info(f"  插图 {img_name} 压缩后未变小，保留原图")
            return img_name, path
        stem, _ = os.path.splitext(img_name)
        new_name = f"{stem}_q{self.image_quality}.jpg"
        logger.info(f"  插图压缩: {img_name} -> {new_name} "
                    f"({os.path.getsize(path) // 1024}KB -> {len(data) // 1024}KB)")
        return new_name, data

    def _image_html(self, img_name, desc=None):
        """
        生成插图 HTML（居中图片 + 可选描述）。
        找不到图片文件时返回 None（调用方保留原文标记并告警）。
        启用压缩时先压缩（见 _maybe_compress_image），src 与 manifest 使用压缩后的文件名。
        """
        path = self._find_image(img_name)
        if not path:
            logger.warning(f"插图文件未找到，保留原文标记: {img_name}")
            return None
        zip_name, data = self._maybe_compress_image(img_name, path)
        self._used_images[zip_name] = data
        html = f'<div class="illustration"><img src="img/{zip_name}" alt="插图"/>'
        if desc:
            desc_text = '<br/>'.join(self._escape(line) for line in desc)
            html += f'<div class="illustration-desc">{desc_text}</div>'
        html += '</div>'
        return html

    def _render_inline_illustrations(self, text):
        """
        把段落中的【插图: xxx】标记替换为插图 HTML：
          - 整段只有一个标记 -> 插图（文本为空）
          - 标记与文字混排 -> 文字与插图依次输出
        找不到图片时保留标记原文（含告警，见 _image_html）。
        返回 HTML 片段列表（<p> 或插图 <div>）。
        """
        out = []
        pos = 0
        text_buf = []

        def flush_text():
            if text_buf:
                out.append(f"<p>{self._escape(''.join(text_buf).strip())}</p>")
                text_buf.clear()

        for m in self.ILLUSTRATION_MARKER_RE.finditer(text):
            before = text[pos:m.start()]
            if before.strip():
                text_buf.append(before)
            html = self._image_html(m.group(1).strip())
            if html is None:
                text_buf.append(m.group(0))
            else:
                flush_text()
                out.append(html)
            pos = m.end()
        rest = text[pos:]
        if rest.strip():
            text_buf.append(rest)
        flush_text()
        return out

    def _parse_illustrations_file(self, path):
        """
        解析插图信息文件（--illustrations 指定或自动识别插图信息.txt / 插图信息.json）。
        按文件内容自动识别两种格式：

        A. txt 格式：
            043 xxx                    （可选章节头：3 位数字开头（可单独成行或后跟内容），
                                        设定当前章节，后面的条目默认归属该章）
            【插图: ch041_up_22901790.jpg】
            描述插画的信息（可多行，直到下一个标记/章节头）
        B. JSON 格式（数组，结构严格）：
            [
                {"chapter": 41, "img": "ch041_up_22901790.jpg", "desc": "描述插画的信息"},
                {"chapter": "002", "img": "up_12345.png", "desc": "描述"}
            ]

        插图归属章节：txt 优先取文件名中的 ch<编号>（pixiv 命名），否则用章节头；
        JSON 用 chapter 字段（数字或 3 位字符串，缺省时回退文件名 ch<编号>）；
        都没有则跳过并警告。
        返回 {章节key: [{"img": 文件名, "desc": [描述行...]}, ...]}。
        """
        return parse_illustrations_file(path, warning=logger.warning, info=logger.info)

    def _parse_illustrations_txt(self, content):
        """解析 txt 格式的插图信息。"""
        return parse_illustrations_text(content, warning=logger.warning)

    @staticmethod
    def _parse_illustrations_json(data):
        """解析 JSON 格式的插图信息（数组）。"""
        return parse_illustrations_json(data, warning=logger.warning)

    def _find_illustrations_info(self):
        """自动查找输入目录中的 插图信息.txt / 插图信息.json。"""
        for d in reversed(self.input_folders):
            for name in ("插图信息.txt", "插图信息.json", "illustrations.json"):
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    return path
        return None

    # ---- 封面 ----

    @staticmethod
    def _image_mimetype(path):
        """按扩展名返回图片 MIME 类型。"""
        return image_mimetype(path)

    def _find_cover(self):
        """
        确定封面图片路径：
          1. --cover 显式指定（文件不存在则报错并返回 None）
          2. 自动查找：输入目录（后列优先级高在前）及其父目录下的 cover.* / 封面.*
        返回图片文件路径，找不到返回 None。
        """
        if self.cover:
            if not os.path.isfile(self.cover):
                logger.error(f"指定的封面文件不存在: {self.cover}")
                return None
            logger.info(f"封面图片（--cover 指定）: {self.cover}")
            return self.cover

        exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        candidates = []
        seen = set()
        for d in reversed(self.input_folders):
            for c in (d, os.path.dirname(os.path.abspath(d))):
                if c and os.path.isdir(c) and c not in seen:
                    seen.add(c)
                    candidates.append(c)
        for d in candidates:
            for fname in sorted(os.listdir(d)):
                stem, ext = os.path.splitext(fname.lower())
                if ext in exts and stem in ("cover", "封面"):
                    path = os.path.join(d, fname)
                    logger.info(f"封面图片（自动识别）: {path}")
                    return path
        return None

    # ---- 章节收集（复用 merge 的多目录配对语义） ----

    def _collect_chapters(self):
        """
        从多个输入目录按数字前缀（或无前缀的完整文件名）收集章节。
        后面的目录优先级高；"000 书籍信息.txt" 是元数据不是章节，跳过。
        返回按前缀排序的 [(key, display_title, file_path)] 列表。
        """
        collected = collect_text_overlay(
            self.input_folders,
            exclude_book_info=True,
            warn_missing=logger.warning,
        )

        # 排序：数字前缀按整数升序；无前缀文件排在最后
        def sort_key(item_key):
            if isinstance(item_key, str) and item_key.isdigit():
                return (0, int(item_key))
            return (1, item_key)

        result = []
        for key in sorted(collected.keys(), key=sort_key):
            fname, path = collected[key]
            result.append((key, self._chapter_title(fname), path))
        return result

    @staticmethod
    def _chapter_title(fname):
        """从 '<编号> <标题>.txt' 提取章节标题（去掉数字前缀与扩展名）。"""
        title = re.sub(r'^\d+\s*', '', fname)
        if title.lower().endswith('.txt'):
            title = title[:-4]
        return title.strip()

    @staticmethod
    def _escape(text):
        """转义 XML/HTML 特殊字符（& < > " '）。"""
        return html.escape(text)

    def _resolve_chapter_title(self, path, fname_title):
        """
        决定章节展示标题：
          - 文件首行若是章节标记行（第X章/番外，如 split 拆卷输出），
            用它作标题并标记首行需从正文剔除；
          - 否则用文件名推导的标题（format 输出首行与之相同，由 _chapter_body 去重）。
        返回 (display_title, skip_first)。
        """
        with open(path, 'r', encoding='utf-8') as f:
            first = None
            for line in f:
                s = line.strip()
                if s:
                    first = s
                    break
        if first and parse_chapter_marker(first):
            return first, True
        return fname_title, False

    def _chapter_body(self, path, display_title, skip_first=False,
                      chapter_key=None, illu_map=None):
        """
        读章节正文，返回 XHTML 片段（<p> 段落 + 插图 <div>）。
        skip_first=True 时丢弃首行（该行是章节标记行，已作为标题渲染）；
        否则若正文首段与展示标题一致（format 注入的标题行），丢弃该段避免与 h1 重复。
        正文中的【插图: xxx】标记在对应位置内嵌图片；illu_map 中该章节的插图
        （来自插图信息文件）追加在章节末尾。
        """
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        paras = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if skip_first:
                skip_first = False
                continue
            if not paras and stripped == display_title:
                continue
            if self.ILLUSTRATION_MARKER_RE.search(stripped):
                paras.extend(self._render_inline_illustrations(stripped))
            else:
                paras.append(f"<p>{self._escape(stripped)}</p>")
        # 章节末尾：追加插图信息文件中属于本章的插图（人工校正删掉正文标记后的方案）
        if chapter_key and illu_map and chapter_key in illu_map:
            for entry in illu_map[chapter_key]:
                html = self._image_html(entry["img"], entry["desc"] or None)
                if html:
                    paras.append(html)
        return '\n'.join(paras)

    # ---- 元数据 ----

    def _find_book_info(self):
        """
        解析书籍元数据：
          1. 输入目录中的 000 书籍信息.txt（多个输入目录都存在时取 mtime 最新——
             重新 format 后的新字段优先，用户手改过的同样优先；只搜输入目录本身，
             避免误命中父目录里其他系列/无关的 000）
          2. pixiv 系列 info.txt / metadata.json（复用 BookInfoGenerator）
          3. 占位默认值
        返回 (info_dict, found)：
          info: title/author/platform/status/word_count/description
          found: True 表示有真实书籍信息来源（000 文件或 pixiv 信息），
                 False 表示纯占位（此时不生成书籍信息页）
        """
        candidates = []
        for d in reversed(self.input_folders):
            path = os.path.join(d, '000 书籍信息.txt')
            if os.path.isfile(path) and path not in candidates:
                candidates.append(path)
        if candidates:
            path = max(candidates, key=os.path.getmtime)
            logger.info(f"书籍信息来源: {path}")
            return self._parse_book_info_file(path), True

        info = BookInfoGenerator(self.input_folders[0])._find_pixiv_info()
        if info:
            logger.info("未找到 000 书籍信息.txt，回退到 pixiv 系列 info/metadata")
            return {
                "title": info.get("title") or "未填",
                "author": info.get("author") or "未填",
                "platform": info.get("platform") or "Pixiv",
                "status": "",
                "word_count": BookInfoGenerator._format_wan(info.get("word_count", 0)),
                "maker": "",
                "description": info.get("description") or "未填",
            }, True

        logger.warning("未找到任何书籍信息源，使用占位元数据（可用 --title/--author 覆盖）")
        return {
            "title": "未填", "author": "未填", "platform": "",
            "status": "", "word_count": "", "maker": "",
            "description": "未填",
        }, False

    @staticmethod
    def _parse_book_info_file(path):
        """
        解析 000 书籍信息.txt（段落间空行格式）：
            书籍信息
            <书名>
            作者：xxx
            连载平台：xxx
            连载状态：xxx
            字数：xxx
            简介：
            <简介...>
        """
        return parse_book_info_file(path)

    # ---- 三个 XML 骨架文件 ----

    def _content_opf(self, title, author, info, uid, spine_items,
                     cover_img_name=None, used_images=None):
        """
        生成 content.opf：元数据 + manifest + spine。
        spine_items 为 build 阶段规划好的阅读顺序列表（封面 + 书籍信息 + 卷页 + 章节）。
        cover_img_name 非空时加入封面图（EPUB3 properties="cover-image"）与
        EPUB2 兼容的 <meta name="cover"> / <guide> 封面引用。
        used_images 为已嵌入的插图 {文件名: 路径}，加入 manifest。
        """
        return render_content_opf(
            title,
            author,
            info,
            uid,
            spine_items,
            cover_img_name=cover_img_name,
            used_images=used_images,
        )

    def _toc_ncx(self, title, uid, spine_items):
        """
        生成 toc.ncx：EPUB2 目录（老阅读器兼容）。
        卷页为一层 navPoint，其所属章节（按 vol 标记）为嵌套的子 navPoint；
        playOrder 按阅读顺序（父卷先于其子章）。
        """
        return render_toc_ncx(title, uid, spine_items, template=self.NCX_TEMPLATE)

    def _nav_xhtml(self, spine_items):
        """
        生成 nav.xhtml：EPUB3 目录导航。
        卷为一级 li，其所属章节（按 vol 标记）为嵌套的 <ol> 子列表；
        游离章节（不属于任何卷）保持一级。
        """
        return render_nav_xhtml(spine_items, template=self.NAV_TEMPLATE)

    # ---- 卷/篇配置与阅读顺序规划 ----

    @staticmethod
    def _validate_css_value(value, pattern, what):
        """校验用户传入的 CSS 值是否安全（只含合法字符），非法时警告并返回 None。"""
        return validate_css_value(value, pattern, what, warning=logger.warning)

    @staticmethod
    def _split_title(display_title):
        """
        把章标题拆成「章节号 + 章节名」两行显示的两部分。

        支持形态：
          - "第一章 xxx" / "第2.5章 xxx" / "第38话 xxx"  -> ("第一章", "xxx")
          - "番外：xxx" / "番外 xxx"                      -> ("番外", "xxx")
        无法识别时返回 (None, 完整标题)，由调用方决定是否拆行。
        """
        return split_chapter_title(display_title)

    def _build_title_html(self, display_title):
        """
        根据标题样式生成 h1 内部 HTML：
          - split 开启且能识别章节号时：<div class="chapter-num">第一章</div>
                                          <div class="chapter-name">章名</div>
          - 否则：直接标题文本（与旧版一致）

        用 div 而非 span：div 是原生块级元素，即使阅读器（如微信读书）剥掉
        display:block 布局 CSS，div 也天然换行；span 被剥掉后会退回行内导致并成一行。
        """
        return build_chapter_title_html(display_title, self.title_style)

    def _build_book_info_body(self, info, title, author):
        """
        生成书籍信息页正文（按 000 书籍信息.txt 的段落格式渲染）：
            书籍信息        （页面标题，模板已含）
            <书名>          （大号加粗）
            作者：xxx
            连载平台：xxx
            连载状态：xxx
            卷/篇数：N
            字数：xxx
            EPUB制作：xxx    （--maker 显式指定优先，否则取 000 的制作人行）
            简介：
            <简介每段一个 p>
        书名/作者优先取 --title/--author 覆盖值。
        """
        return build_book_info_body(info, title, author, maker=self.maker)

    @staticmethod
    def _split_volume_title(name):
        """
        把卷名拆成「卷号 + 卷名」两行显示的两部分：
          "第一卷 示例卷名"        -> ("第一卷", "示例卷名")
          "第三卷 示例卷名"  -> ("第三卷", "示例卷名")
          "番外篇 往事"           -> ("番外篇", "往事")
        无法识别时返回 (None, 完整卷名)，由调用方决定是否拆行。
        """
        return split_volume_title(name)

    def _build_volume_html(self, name):
        """
        根据样式生成卷页标题 HTML：
          - vol_split 开启且能识别卷号时：<div class="volume-num">第一卷</div>
                                           <div class="volume-name">示例卷名</div>
          - 否则：单行 <div class="volume-name">卷名</div>
            （始终套 .volume-name，避免无卷号的卷名掉回正文默认字号/颜色）

        用 div 而非 span：div 是原生块级元素，即使阅读器（如微信读书）剥掉
        display:block 布局 CSS 也天然换行（span 会退回行内并成一行）。
        """
        return build_volume_title_html(name, self.vol_style)

    def _build_volume_css(self):
        """
        生成 .volume-title 的 CSS 规则（拆两行时卷号/卷名各自可调颜色、字号与间距）：
          - 基础规则：加粗、居中、无缩进、padding-top 35% 垂直居中
          - vol_split 开启：.volume-num（vol_num_color/vol_num_size + vol_gap 下间距）
                            与 .volume-name（vol_color/vol_size）
          - 关闭：字号/颜色直接作用于 .volume-title
        """
        return build_volume_css(self.vol_style, warning=logger.warning)

    def _build_title_css(self):
        """
        根据 title_style 生成 h1.chapter-title 的 CSS 规则字符串。

        参考样式（左对齐 + 深红 + 下划线）：
            text-align: left; color: #8B0000; font-size: 1.2em;
            padding-bottom: 0.5em; border-bottom: #8B0000 solid 2px;
        """
        return build_chapter_title_css(self.title_style, warning=logger.warning)

    def _load_volumes(self):
        """
        读取卷/篇配置文件（--volumes 指定），JSON 列表格式：
            [
                {"name": "第一卷 示例卷名", "start": 1, "end": 17},
                {"name": "第二卷 示例卷名", "start": 18, "end": 35}
            ]
        - name: 卷/篇标题（显示在独立卷页与目录里）
        - start / end: 章节文件数字前缀范围（含端点）；只写 start 时视为单章
        返回按 start 排序的 [{name, start, end}] 列表；未配置或配置为空返回 []；
        文件不存在 / 解析失败返回 None（build 将中止）。
        """
        return _load_volumes_file(self.volumes_file)

    def _plan_spine(self, chapters, volumes):
        """
        规划阅读顺序：卷页插入其范围内首章之前，其余章节保持原顺序。

        返回 (spine_items, vol_chapter_map):
          spine_items: 按阅读顺序的条目列表
            {"kind": "vol",  "fname": "vol_1.xhtml", "id": "vol_1", "title": "第一卷 xxx"}
            {"kind": "chap", "key": "001", "fname": "chap_001.xhtml", "id": "chap_001",
             "title": "第一章 xxx", "path": "..."}
          vol_chapter_map: {卷序号: [该卷包含的章节 key 列表]}
        """
        return plan_spine(chapters, volumes, warning=logger.warning, info=logger.info)

    # ---- 主流程 ----

    def build(self):
        """
        收集章节并打包为 EPUB 文件。返回输出文件路径，失败返回 None。
        """
        chapters = self._collect_chapters()
        if not chapters:
            logger.error("所有输入目录中都没有章节 txt，无法生成 EPUB。")
            return None

        volumes = self._load_volumes()
        if volumes is None:
            logger.error("卷/篇配置读取失败，中止打包（可去掉 --volumes 参数重试）。")
            return None

        spine_items, vol_chapter_map = self._plan_spine(chapters, volumes)
        if not spine_items:
            logger.error("没有可打包的内容。")
            return None

        # 每次打包前刷新书籍信息：按实际打包章节重新统计章节数与字数，
        # 更新 000 书籍信息.txt（写回优先级最高的输入目录，通常是 corrected/；
        # 只搜输入目录本身，避免误命中父目录里其他系列的 000）
        try:
            BookInfoGenerator(self.input_folders).update_word_count_for_merge(
                search_parent=False, volumes=volumes)
        except Exception as e:
            logger.warning(f"书籍信息刷新失败（继续打包）: {e}")

        info, info_found = self._find_book_info()
        title = self.overrides["title"] or info["title"]
        author = self.overrides["author"] or info["author"]
        uid = f"urn:uuid:{uuid.uuid4()}"

        # 有真实书籍信息来源时，在书的最前面生成书籍信息页（并进入目录）
        if info_found:
            spine_items.insert(0, {
                "kind": "info",
                "fname": "book_info.xhtml",
                "id": "book_info",
                "title": "书籍信息",
            })

        # 封面：有封面图片时生成封面页并放在全书最前（spine 第一位）
        cover_file = self._find_cover()
        if self.cover and not cover_file:
            logger.error("指定的封面文件不存在，中止打包（可去掉 --cover 参数重试）。")
            return None
        cover_img_name = None
        if cover_file:
            ext = os.path.splitext(cover_file)[1].lower() or ".jpg"
            cover_img_name = f"cover{ext}"
            spine_items.insert(0, {
                "kind": "cover",
                "fname": "cover.xhtml",
                "id": "cover",
                "title": "封面",
                "img": cover_img_name,
            })

        # 插图信息文件（--illustrations 显式指定或自动识别 插图信息.txt）
        illu_file = self.illustrations_file or self._find_illustrations_info()
        illu_map = {}
        if illu_file:
            if os.path.isfile(illu_file):
                illu_map = self._parse_illustrations_file(illu_file)
                total = sum(len(v) for v in illu_map.values())
                logger.info(f"插图信息文件: {illu_file}（{total} 条）")
            else:
                logger.error(f"指定的插图信息文件不存在: {illu_file}")
                return None
        self._used_images = {}

        out_dir = os.path.dirname(os.path.abspath(self.output_file))
        os.makedirs(out_dir, exist_ok=True)

        logger.info(f"EPUB 打包开始: {len(chapters)} 章"
                    + (f" + {len(vol_chapter_map)} 卷页" if vol_chapter_map else "")
                    + (f" + 1 书籍信息页" if info_found else "")
                    + f" -> {self.output_file}")
        logger.info(f"  书名: {title} | 作者: {author}")

        # mimetype 必须第一个写入且不压缩（ZIP_STORED），否则阅读器不认
        with zipfile.ZipFile(self.output_file, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr('mimetype', 'application/epub+zip')

        # 其余内容用 DEFLATED 压缩追加写入
        with zipfile.ZipFile(self.output_file, 'a', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('META-INF/container.xml', self.CONTAINER_XML)
            zf.writestr('OEBPS/style.css',
                        self.CSS.format(chapter_title_css=self._build_title_css(),
                                        volume_title_css=self._build_volume_css()))

            for item in spine_items:
                if item["kind"] == "cover":
                    zf.write(cover_file, f'OEBPS/{cover_img_name}')
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.COVER_TEMPLATE.format(img=item["img"]),
                    )
                    logger.info(f"  [封面] {os.path.basename(cover_file)}")
                elif item["kind"] == "info":
                    body = self._build_book_info_body(info, title, author)
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.BOOK_INFO_TEMPLATE.format(title=self._escape(item["title"]),
                                                       body=body),
                    )
                    logger.info(f"  [书籍信息] {item['title']}")
                elif item["kind"] == "vol":
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.VOLUME_TEMPLATE.format(name=self._escape(item["title"]),
                                                    content=self._build_volume_html(item["title"])),
                    )
                    logger.info(f"  [卷] {item['title']}")
                else:
                    resolved_title, skip_first = self._resolve_chapter_title(
                        item["path"], item["title"])
                    body = self._chapter_body(item["path"], resolved_title,
                                              skip_first=skip_first,
                                              chapter_key=item.get("key"),
                                              illu_map=illu_map)
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.CHAPTER_TEMPLATE.format(title=self._escape(resolved_title),
                                                     title_html=self._build_title_html(resolved_title),
                                                     body=body),
                    )
                    item["title"] = resolved_title  # 目录/日志用解析后的标题
                    logger.info(f"  [{item['key']}] {resolved_title}")

            # 插图图片文件写进包（OEBPS/img/ 下；压缩过的为 bytes，其余为原路径）
            for img_name, img_data in sorted(self._used_images.items()):
                if isinstance(img_data, bytes):
                    zf.writestr(f'OEBPS/img/{img_name}', img_data)
                else:
                    zf.write(img_data, f'OEBPS/img/{img_name}')
            if self._used_images:
                logger.info(f"  已嵌入插图 {len(self._used_images)} 张")

            zf.writestr('OEBPS/content.opf',
                        self._content_opf(title, author, info, uid, spine_items,
                                          cover_img_name=cover_img_name,
                                          used_images=self._used_images))
            zf.writestr('OEBPS/toc.ncx', self._toc_ncx(title, uid, spine_items))
            zf.writestr('OEBPS/nav.xhtml', self._nav_xhtml(spine_items))

        logger.info(f"EPUB 生成完成: {self.output_file}"
                    f"（{len(spine_items) - len(vol_chapter_map) - (1 if info_found else 0)} 章"
                    + (f" + {len(vol_chapter_map)} 卷页" if vol_chapter_map else "")
                    + (f" + 1 书籍信息页" if info_found else "") + "）")
        return self.output_file
