"""面向新用户的一键下载、整理与成书流水线。"""

from dataclasses import dataclass
import logging
import os
import re

from pixiv_novel_toolkit.chapters.splitting import (
    list_chapter_text_files,
    sanitize_filename_part,
)
from pixiv_novel_toolkit.downloads.parsing import parse_pixiv_series_id
from pixiv_novel_toolkit.epub.builder import EpubBuilder
from pixiv_novel_toolkit.postprocess.book_info import parse_book_info_file
from pixiv_novel_toolkit.postprocess.formatting import BatchTxtFileFormatter
from pixiv_novel_toolkit.postprocess.merging import TxtFileMerger


logger = logging.getLogger("pixiv_novel_toolkit")

_WINDOWS_RESERVED_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _book_output_stem(standardized_dir):
    """从书籍信息取得安全的成书文件名；无有效书名时回退为“全书”。"""
    info_path = os.path.join(standardized_dir, "000 书籍信息.txt")
    if not os.path.isfile(info_path):
        return "全书"

    try:
        title = str(parse_book_info_file(info_path).get("title") or "").strip()
    except (OSError, UnicodeError) as exc:
        logger.warning(f"读取书籍名称失败，将使用默认文件名“全书”: {exc}")
        return "全书"

    if not title or title == "未填":
        return "全书"

    stem = sanitize_filename_part(title)
    stem = re.sub(r"\s+", " ", stem).rstrip(" .")[:120].rstrip(" .")
    if not stem:
        return "全书"
    if stem.upper() in _WINDOWS_RESERVED_STEMS:
        stem = f"_{stem}"
    return stem


def _resolve_epub_styles(
    *,
    title_style_name=None,
    vol_style_name=None,
    styles_file=None,
    title_align=None,
    title_color=None,
    title_size=None,
    title_underline=None,
):
    """加载 quick 指定的 EPUB 预设，并叠加显式章标题样式。"""
    presets = None
    if title_style_name or vol_style_name:
        presets = EpubBuilder.load_presets(styles_file)

    title_style = {}
    if title_style_name:
        preset = presets["chapter"].get(title_style_name)
        if preset is None:
            logger.error(
                f"章节样式预设 {title_style_name!r} 不存在"
                "（可用 epub --title-styles 查看全部预设）"
            )
            return None
        title_style.update(preset)

    if title_align is not None:
        title_style["align"] = title_align
    if title_color:
        title_style["color"] = title_color
    if title_size is not None:
        title_style["size"] = title_size
    if title_underline is not None:
        title_style["underline"] = title_underline

    vol_style = {}
    if vol_style_name:
        preset = presets["volume"].get(vol_style_name)
        if preset is None:
            logger.error(
                f"卷名样式预设 {vol_style_name!r} 不存在"
                "（可用 epub --title-styles 查看全部预设）"
            )
            return None
        vol_style.update(preset)
    return title_style, vol_style


@dataclass(frozen=True)
class QuickBuildResult:
    """一键流水线成功后的主要输出路径。"""

    series_id: str
    work_dir: str
    standardized_dir: str
    corrected_dir: str
    txt_file: str
    epub_file: str


def build_series_book(
    scraper,
    series_target,
    *,
    force=False,
    workers=1,
    punct=False,
    volumes_file=None,
    indent=False,
    maker=None,
    title=None,
    author=None,
    title_style_name=None,
    vol_style_name=None,
    styles_file=None,
    title_align=None,
    title_color=None,
    title_size=None,
    title_underline=None,
    cover=None,
    illustrations_file=None,
    image_quality=None,
):
    """完成系列下载、标准化、TXT 合并与 EPUB 打包，可覆盖常用成书参数。"""
    series_id = parse_pixiv_series_id(series_target)
    styles = _resolve_epub_styles(
        title_style_name=title_style_name,
        vol_style_name=vol_style_name,
        styles_file=styles_file,
        title_align=title_align,
        title_color=title_color,
        title_size=title_size,
        title_underline=title_underline,
    )
    if styles is None:
        return None
    title_style, vol_style = styles

    if image_quality is not None and not 1 <= image_quality <= 100:
        logger.warning(f"--image-quality 应为 1-100，收到 {image_quality}，忽略该项")
        image_quality = None

    work_dir = scraper.build_series_output_dir(series_id)
    chapters_dir = scraper.build_chapters_dir(work_dir)
    standardized_dir = os.path.join(work_dir, "standardized")
    corrected_dir = os.path.join(work_dir, "corrected")

    logger.info("===== 一键成书开始 =====")
    logger.info(f"系列 ID: {series_id}")

    logger.info("[1/4] 下载系列正文、封面与插图")
    downloaded = scraper.download_series(
        series_id,
        force=force,
        workers=workers,
    )
    if not downloaded:
        logger.error("系列下载失败，一键成书已中止。")
        return None
    if not os.path.isdir(chapters_dir) or not list_chapter_text_files(chapters_dir):
        logger.error("下载完成后未找到章节 TXT，一键成书已中止。")
        return None

    logger.info("[2/4] 按默认配置标准化章节")
    BatchTxtFileFormatter(
        chapters_dir,
        standardized_dir,
        punct=punct,
    ).format_all_files()
    if not list_chapter_text_files(standardized_dir):
        logger.error("标准化目录中没有有效章节，一键成书已中止。")
        return None
    os.makedirs(corrected_dir, exist_ok=True)
    logger.info(f"校正目录已准备: {corrected_dir}")

    output_stem = _book_output_stem(standardized_dir)
    txt_file = os.path.join(work_dir, f"{output_stem}.txt")
    epub_file = os.path.join(work_dir, f"{output_stem}.epub")
    logger.info(f"成书文件名: {output_stem}")

    source_dirs = [standardized_dir, corrected_dir]
    logger.info("[3/4] 合并全书 TXT")
    merged = TxtFileMerger(
        source_dirs,
        txt_file,
        update_info=True,
        volumes_file=volumes_file,
        indent=indent,
        maker=maker,
    ).merge_txt_files()
    if not merged:
        logger.error("TXT 合并失败，一键成书已中止。")
        return None

    logger.info("[4/4] 使用默认样式打包 EPUB")
    built_epub = EpubBuilder(
        source_dirs,
        epub_file,
        title=title,
        author=author,
        maker=maker,
        volumes_file=volumes_file,
        title_style=title_style,
        vol_style=vol_style,
        cover=cover,
        illustrations_file=illustrations_file,
        image_quality=image_quality,
    ).build()
    if not built_epub:
        logger.error("EPUB 打包失败，一键成书已中止。")
        return None

    result = QuickBuildResult(
        series_id=series_id,
        work_dir=work_dir,
        standardized_dir=standardized_dir,
        corrected_dir=corrected_dir,
        txt_file=txt_file,
        epub_file=epub_file,
    )
    logger.info("===== 一键成书完成 =====")
    logger.info(f"TXT: {txt_file}")
    logger.info(f"EPUB: {epub_file}")
    return result
