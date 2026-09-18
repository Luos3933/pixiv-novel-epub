import logging
import sys

from log_setup import configure_logging
from pixiv_novel_toolkit.chapters.markers import (
    BARE_HEAD_RE as CHAPTER_BARE_HEAD_RE,
    BARE_SUFFIX_RE as CHAPTER_BARE_SUFFIX_RE,
    FANWAI_RE as CHAPTER_FANWAI_RE,
    GLUED_BLOCK_CHARS as CHAPTER_GLUED_BLOCK_CHARS,
    GLUED_QUANTITY_STARTERS as CHAPTER_GLUED_QUANTITY_STARTERS,
    MARKER_RE as CHAPTER_MARKER_RE,
    chapter_number_to_chinese,
    chinese_chapter_number_to_int,
    parse_chapter_marker,
    unify_chapter_marker,
)
from pixiv_novel_toolkit.chapters.numbering import (
    allocate_output_number,
    build_number_report,
    chapter_name,
    compress_ranges,
    describe_number_gaps,
    normalize_title_key,
    renumber_segments,
)
from pixiv_novel_toolkit.chapters.overlay import (
    build_prefix_index,
    collect_text_overlay,
    file_prefix,
    list_text_files,
)
from pixiv_novel_toolkit.chapters.scanning import scan_chapter_segments, scan_marker_lines
from pixiv_novel_toolkit.chapters.split_config import (
    SPLIT_CONFIG_DEFAULTS,
    SPLIT_CONFIG_SAMPLE,
    load_split_config as _load_split_config,
)
from pixiv_novel_toolkit.chapters.splitter import VolumeSplitter
from pixiv_novel_toolkit.chapters.splitting import (
    discover_split_inputs,
    find_volume_overlaps,
    list_chapter_text_files,
    sanitize_filename_part,
    scan_suspicious_markers,
    volume_name_from_filename,
    write_volumes_file,
)
from pixiv_novel_toolkit.chapters.volumes import load_volumes_file
from pixiv_novel_toolkit.chapters.toc import TocManager
from pixiv_novel_toolkit.common.textio import detect_encoding, read_text, read_text_lines
from pixiv_novel_toolkit.epub.builder import EpubBuilder
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
from pixiv_novel_toolkit.postprocess.book_info import (
    BLANK_BOOK_INFO_TEMPLATE,
    TEXT_BOOK_INFO_TEMPLATE,
    format_update_date,
    format_word_count,
    parse_book_info_file,
    parse_pixiv_info_file,
    parse_pixiv_metadata_file,
    upsert_maker_line,
)
from pixiv_novel_toolkit.postprocess.book_info_generator import BookInfoGenerator
from pixiv_novel_toolkit.postprocess.assembly import DirectoryAssembler
from pixiv_novel_toolkit.postprocess.auditing import TextAuditor, audit_lines
from pixiv_novel_toolkit.postprocess.cleaning import (
    TextCleaner,
    clean_text,
    is_suspected_hard_wrap,
)
from pixiv_novel_toolkit.postprocess.diffing import DirectoryDiffer, TxtFileComparator
from pixiv_novel_toolkit.postprocess.formatting import (
    BatchTxtFileFormatter,
    TxtFileFormatter,
    convert_punctuation,
    interleave_blank_lines,
)
from pixiv_novel_toolkit.postprocess.merging import TxtFileMerger
from pixiv_novel_toolkit.postprocess.processing_config import (
    TEXT_PROCESSING_DEFAULTS,
    TEXT_PROCESSING_SAMPLE,
    load_text_processing_config,
)
from pixiv_novel_toolkit.postprocess.revisions import RevisionsStore
from pixiv_novel_toolkit.postprocess_cli import (
    _cmd_audit,
    _cmd_assemble,
    _cmd_clean,
    _cmd_compare,
    _cmd_diff,
    _cmd_epub,
    _cmd_format_batch,
    _cmd_format_single,
    _cmd_merge,
    _cmd_note,
    _cmd_punct,
    _cmd_split,
    _cmd_toc,
    _resolve_path,
    build_arg_parser,
    main,
)


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


def configure_postprocess_logging(base_dir):
    """配置后处理日志：固定文件 logs/postprocess.log 追加，超 1MB 自动归档到 logs/archive/。"""
    return configure_logging(base_dir, "pixiv_novel_toolkit.postprocess", "postprocess.log")


def _file_prefix(filename):
    r"""
    返回文件名开头的数字前缀（如 '043'），无数字前缀返回 None。

    与 format / merge 内的 sort_key 一致：匹配规则是 ^(\d+)。
    """
    return file_prefix(filename)


def _list_txt_in(directory):
    """列出目录下所有 .txt 文件名（不保证排序，调用方自行决定）。
    跳过 "_" 开头的系统生成文件（_toc.txt / _编号统计.txt / _source_map.txt 等）。"""
    return list_text_files(directory)


def _build_prefix_index(directory):
    """
    把目录下所有 txt 按数字前缀索引起来（用作 diff/note/assemble 的配对键）。

    返回 (prefix_map, no_prefix):
      prefix_map: {'043': '043 xxx.txt', ...}  数字前缀 -> 完整文件名
      no_prefix:  ['附录.txt', ...]            无数字前缀的文件名（按完整名匹配）
    前缀在 format 输出里是唯一的；若出现重复会保留最后读到的一个并打 warning。
    """
    return build_prefix_index(directory, warn=logger.warning)


def _compress_ranges(nums):
    """把升序编号列表压缩为范围串："433、434" -> "433-434"；[1,2,3,7] -> "1-3、7"。"""
    return compress_ranges(nums)


def _int_to_chinese(num):
    """阿拉伯数字转中文数字（如 43 -> 四十三），10-19 写作 十X 而非 一十X。"""
    return chapter_number_to_chinese(num)


def _chinese_to_int(cn):
    """
    中文数字转阿拉伯数字（支持十/百/千/万，如 十九->19、一百零三->103）；失败返回 None。

    逐位风格：全部为数字字且不含单位（如 "一四四"）时按位解读为 144——
    外来网文常见作者把 144 写成"一四四"，旧逻辑会误算成 4。
    """
    return chinese_chapter_number_to_int(cn)


def _sanitize_filename_part(text):
    """清理章节标题中不能出现在 Windows 文件名里的字符。"""
    return sanitize_filename_part(text)


def _detect_encoding(path):
    """
    探测文本文件编码，供 split/toc 读取外来整本 txt 使用（项目输出统一 UTF-8，
    但外来下载源常见 GBK/GB2312/Big5）。

    策略：
    1. BOM 优先：utf-8 BOM -> utf-8-sig；FF FE / FE FF -> utf-16
    2. 严格 UTF-8 解码成功 -> utf-8
    3. 否则 gb18030 / big5 各解码一次，按「常见汉字占汉字总数比例」评分择优
       （gb18030 四字节区几乎不会解码失败，错编码时会产生大量生僻字，
       占比评分能有效区分简体 GBK 与繁体 Big5 来源）
    返回编码名（Python codec 别名）。
    """
    return detect_encoding(path)


def _read_text_lines(path):
    """
    按探测到的编码读取文本文件并按行拆分（\r\n/\n 统一 splitlines）。
    非 UTF-8 时打印日志告知（输出文件仍统一写 UTF-8，符合项目约定）。
    """
    return read_text_lines(path, info=logger.info)


def _read_text_auto(path):
    """按探测到的编码读取整个文本文件内容（str）。"""
    return read_text(path, info=logger.info)


def _load_volumes_file(volumes_file):
    """
    读取卷/篇配置文件（merge --volumes / epub --volumes 共用），JSON 列表格式：
        [
            {"name": "第一卷 示例卷名", "start": 1, "end": 17},
            {"name": "第二卷 示例卷名", "start": 18, "end": 35}
        ]
    - name: 卷/篇标题
    - start / end: 章节文件数字前缀范围（含端点）；只写 start 时视为单章
    返回按 start 排序的 [{name, start, end}] 列表；未配置或配置为空返回 []；
    文件不存在 / 解析失败返回 None（调用方决定中止或跳过）。
    """
    return load_volumes_file(
        volumes_file,
        error=logger.error,
        warning=logger.warning,
        info=logger.info,
    )


if __name__ == "__main__":
    sys.exit(main())
