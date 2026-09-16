"""文本后处理命令行参数与命令分发。"""

import argparse
import logging
import os
from pathlib import Path

from log_setup import configure_logging
from pixiv_novel_toolkit.chapters.splitter import VolumeSplitter
from pixiv_novel_toolkit.chapters.toc import TocManager
from pixiv_novel_toolkit.epub.builder import EpubBuilder
from pixiv_novel_toolkit.postprocess.assembly import DirectoryAssembler
from pixiv_novel_toolkit.postprocess.diffing import DirectoryDiffer, TxtFileComparator
from pixiv_novel_toolkit.postprocess.formatting import (
    BatchTxtFileFormatter,
    TxtFileFormatter,
    convert_punctuation,
)
from pixiv_novel_toolkit.postprocess.merging import TxtFileMerger
from pixiv_novel_toolkit.postprocess.revisions import RevisionsStore


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configure_postprocess_logging(base_dir):
    return configure_logging(
        base_dir,
        "pixiv_novel_toolkit.postprocess",
        "postprocess.log",
    )


def _resolve_path(path):
    """返回相对于脚本所在目录的绝对路径，便于在项目任意位置调用。"""
    if os.path.isabs(path):
        return path
    return str(PROJECT_ROOT / path)


def _cmd_merge(args):
    # 支持单个或多个输入目录；nargs='+' 时 args.input_folders 是 list
    input_folders = [_resolve_path(p) for p in args.input_folders]
    output_file = _resolve_path(args.output_file)
    volumes_file = _resolve_path(args.volumes) if args.volumes else None

    invalid = [p for p in input_folders if not os.path.isdir(p)]
    if invalid:
        logger.error(f"输入目录不存在: {invalid}")
        return 1

    TxtFileMerger(input_folders, output_file, update_info=args.info,
                  volumes_file=volumes_file, indent=args.indent,
                  maker=args.maker).merge_txt_files()
    return 0


def _cmd_split(args):
    """
    拆卷：把"一卷一个文件、卷内章节未划分"的原始下载内容（或外来整本 txt）
    拆成独立章节文件，导出到输出目录，并在其上级目录生成 volumes.json。
    """
    input_path = _resolve_path(args.input)
    output_dir = _resolve_path(args.output_dir)

    if not (os.path.isdir(input_path)
            or (os.path.isfile(input_path) and input_path.lower().endswith('.txt'))):
        logger.error(f"输入路径不存在（应为目录或整本 txt 文件）: {input_path}")
        return 1

    result = VolumeSplitter(input_path, output_dir, punct=args.punct,
                            name_only=args.name_only,
                            title_len_limit=args.title_len_limit,
                            unify_title=args.unify_title,
                            num_style=args.num_style,
                            renumber=not args.no_renumber,
                            max_gap=args.max_gap).split()
    return 0 if result else 1


def _cmd_toc(args):
    """章节目录导出、纯目录检查或标题回写。"""
    path = _resolve_path(args.path)
    if args.toc_action == 'export':
        output_file = _resolve_path(args.output_file) if args.output_file else None
        result = TocManager(path).export(output_file)
    elif args.toc_action == 'inspect':
        output_file = _resolve_path(args.output_file) if args.output_file else None
        result = TocManager(path).inspect(output_file)
    else:
        toc_file = _resolve_path(args.toc_file)
        result = TocManager(path).apply(toc_file)
    return 0 if result else 1


def _cmd_epub(args):
    """把章节目录打包为 EPUB 电子书（多目录按数字前缀配对，后列优先）。"""
    # 兼容 merge 式调用（epub a b out.epub）：argparse nargs='*' 会把位置参数全部吞进
    # input_folders，这里把最后一个挪给 output_file（--title-styles 列表模式除外）
    if not args.title_styles and args.output_file is None and len(args.input_folders) >= 2:
        args.output_file = args.input_folders[-1]
        args.input_folders = args.input_folders[:-1]

    input_folders = [_resolve_path(p) for p in args.input_folders]
    output_file = _resolve_path(args.output_file) if args.output_file else None
    volumes_file = _resolve_path(args.volumes) if args.volumes else None
    styles_file = _resolve_path(args.title_styles_file) if args.title_styles_file else None

    # 列出全部样式预设（不打包，位置参数可省略）
    if args.title_styles:
        presets = EpubBuilder.load_presets(styles_file)
        if not presets["chapter"] and not presets["volume"]:
            logger.info("暂无可用样式预设。")
        else:
            logger.info(f"章标题样式预设（chapter）: {len(presets['chapter'])} 个")
            for name, style in presets["chapter"].items():
                summary = (f"align={style['align']}, size={style['size']}"
                           + (f", color={style['color']}" if style['color'] else ", color=默认色")
                           + (", 下划线" if style['underline'] else ", 无下划线")
                           + (", 拆两行" if style['split'] else ""))
                logger.info(f"  {name}: {style['desc'] or summary}")
            logger.info(f"卷名样式预设（volume）: {len(presets['volume'])} 个")
            for name, style in presets["volume"].items():
                summary = (f"拆两行={style['vol_split']}, 卷号={style['vol_num_color']}/"
                           f"{style['vol_num_size']}, 卷名={style['vol_color']}/{style['vol_size']}, "
                           f"间距={style['vol_gap']}")
                logger.info(f"  {name}: {style['desc'] or summary}")
        return 0

    if not input_folders or not output_file:
        logger.error("缺少输入目录或输出文件（例：epub standardized/ corrected/ 全书.epub）")
        return 1

    invalid = [p for p in input_folders if not os.path.isdir(p)]
    if invalid:
        logger.error(f"输入目录不存在: {invalid}")
        return 1

    # 样式：预设为基底，显式 CLI 参数覆盖
    presets = None
    if args.title_style or args.vol_style:
        presets = EpubBuilder.load_presets(styles_file)

    title_style = {}
    if args.title_style:
        preset = presets["chapter"].get(args.title_style)
        if preset is None:
            logger.error(f"章节样式预设 {args.title_style!r} 不存在"
                         f"（可用 --title-styles 查看全部预设）")
            return 1
        title_style = dict(preset)
    overrides = {}
    if args.title_align is not None:
        overrides["align"] = args.title_align
    if args.title_color:
        overrides["color"] = args.title_color
    if args.title_size is not None:
        overrides["size"] = args.title_size
    if args.title_underline is not None:
        overrides["underline"] = args.title_underline
    title_style.update(overrides)

    vol_style = {}
    if args.vol_style:
        vol_preset = presets["volume"].get(args.vol_style)
        if vol_preset is None:
            logger.error(f"卷名样式预设 {args.vol_style!r} 不存在"
                         f"（可用 --title-styles 查看全部预设）")
            return 1
        vol_style = dict(vol_preset)

    # 插图压缩质量校验（1-100，越界忽略并告警）
    image_quality = None
    if args.image_quality is not None:
        if 1 <= args.image_quality <= 100:
            image_quality = args.image_quality
        else:
            logger.warning(f"--image-quality 应为 1-100，收到 {args.image_quality}，忽略该项")

    result = EpubBuilder(input_folders, output_file,
                         title=args.title, author=args.author,
                         maker=args.maker,
                         volumes_file=volumes_file,
                         title_style=title_style,
                         vol_style=vol_style,
                         cover=_resolve_path(args.cover) if args.cover else None,
                         illustrations_file=_resolve_path(args.illustrations)
                         if args.illustrations else None,
                         image_quality=image_quality).build()
    return 0 if result else 1


def _cmd_format_batch(args):
    input_folder = _resolve_path(args.input_folder)
    if args.output_folder:
        output_folder = _resolve_path(args.output_folder)
    else:
        # 未指定输出目录时，默认输出到输入目录同级的 standardized/
        output_folder = os.path.join(os.path.dirname(input_folder), "standardized")
        logger.info(f"未指定输出目录，默认使用: {output_folder}")
    if not os.path.isdir(input_folder):
        logger.error(f" 输入目录不存在: {input_folder}")
        return 1
    BatchTxtFileFormatter(input_folder, output_folder, punct=args.punct).format_all_files()
    corrected_folder = os.path.join(
        os.path.dirname(os.path.abspath(output_folder)), "corrected"
    )
    try:
        already_exists = os.path.isdir(corrected_folder)
        os.makedirs(corrected_folder, exist_ok=True)
    except OSError as exc:
        logger.error(f"标准化已完成，但无法创建校正目录 {corrected_folder}: {exc}")
        return 1
    if already_exists:
        logger.info(f"校正目录已存在，保留原有内容: {corrected_folder}")
    else:
        logger.info(f"已自动创建校正目录: {corrected_folder}")
    return 0


def _cmd_format_single(args):
    input_file = _resolve_path(args.input_file)
    output_file = _resolve_path(args.output_file)
    if not os.path.isfile(input_file):
        logger.error(f" 输入文件不存在: {input_file}")
        return 1
    TxtFileFormatter(input_file, output_file).add_blank_lines()
    return 0


def _cmd_compare(args):
    file1 = _resolve_path(args.file1)
    file2 = _resolve_path(args.file2)
    output_file = _resolve_path(args.output_file) if args.output_file else "text_differences.txt"
    if not os.path.isfile(file1):
        logger.error(f" 文件1不存在: {file1}")
        return 1
    if not os.path.isfile(file2):
        logger.error(f" 文件2不存在: {file2}")
        return 1
    TxtFileComparator(file1, file2, output_file).compare_file()
    return 0


def _cmd_diff(args):
    """目录级批量对比两个目录的 txt 文件。"""
    baseline = _resolve_path(args.baseline_dir)
    corrected = _resolve_path(args.corrected_dir)
    report_file = _resolve_path(args.report_file) if args.report_file else None

    if not os.path.isdir(baseline):
        logger.error(f"标准化目录不存在: {baseline}")
        return 1
    if not os.path.isdir(corrected):
        logger.error(f"校正目录不存在: {corrected}")
        return 1

    DirectoryDiffer(baseline, corrected, report_file=report_file,
                    console_preview=args.preview).diff()
    return 0


def _cmd_punct(args):
    """
    将单个 txt 中的英文标点 ! ? " 转为中文标点 ！！？“ ”。
    引号按全文奇偶配对，奇数个时打印警告。
    """
    input_file = _resolve_path(args.input_file)
    output_file = _resolve_path(args.output_file) if args.output_file else input_file
    if not os.path.isfile(input_file):
        logger.error(f"输入文件不存在: {input_file}")
        return 1
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content, stats = convert_punctuation(content)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(new_content)

    logger.info(f"标点转换: {input_file} -> {output_file}")
    logger.info(
        f"  英文双引号 \": {stats['original_quote']} 个 -> "
        f"中文 “ {stats['front_quote']} 个 + ” {stats['back_quote']} 个"
    )
    logger.info(
        f"  英文感叹号 !: {stats['original_exclamation']} 个 -> 中文 ！ 同数量"
    )
    logger.info(
        f"  英文问号   ?: {stats['original_question']} 个 -> 中文 ？ 同数量"
    )
    if stats["unpaired"]:
        logger.warning("检测到奇数个英文双引号，前/后引号可能未完整配对。")
    return 0


def _cmd_note(args):
    """
    管理校正目录的修订说明 _revisions.json。

    支持四种动作:
      add     给单文件追加/覆盖一条修订说明
      remove  删除单文件的修订记录
      list    列出所有修订记录
      clear   清空全部修订记录
    """
    action = args.action
    corrected_dir = _resolve_path(args.corrected_dir)
    if not os.path.isdir(corrected_dir):
        logger.error(f"校正目录不存在: {corrected_dir}")
        return 1

    store = RevisionsStore(corrected_dir)

    if action == "add":
        if not args.msg:
            logger.error("add 动作必须通过 --msg 提供修订说明")
            return 1
        if not args.filename:
            logger.error("add 动作需要文件标识（前缀编号如 '043' 或完整文件名）")
            return 1
        filename = args.filename
        # 规范：传入的 filename 是校正目录里的相对文件名或纯编号，不允许写绝对路径
        if os.path.isabs(filename):
            logger.error("filename 必须是相对文件名（不含路径），如 '043 xxx.txt' 或纯编号 '043'")
            return 1
        key = RevisionsStore._normalize_key(filename)
        store.set(filename, args.msg)
        logger.info(f"已记录修订 (key={key}): {filename}")
        logger.info(f"  说明: {args.msg}")
        return 0

    if action == "remove":
        if not args.filename:
            logger.error("remove 动作需要文件标识（前缀编号或完整文件名）")
            return 1
        if store.remove(args.filename):
            logger.info(f"已删除修订记录: {args.filename}")
        else:
            logger.warning(f"未找到该条目的修订记录: {args.filename}")
        return 0

    if action == "list":
        records = store.list_all()
        if not records:
            logger.info(f"{corrected_dir} 中暂无修订记录")
            return 0
        logger.info(f"校正目录 {corrected_dir} 共 {len(records)} 条修订记录:")
        # 按数字前缀排序输出，无数字前缀的排在最后
        def _sort_key(k):
            return int(k) if k.isdigit() else (10 ** 12, k)
        for key in sorted(records.keys(), key=_sort_key):
            rec = records[key]
            label = key
            actual = rec.get('filename', '')
            if actual and actual != key:
                label = f"{key}  ({actual})"
            logger.info(f"  {label}")
            logger.info(f"    说明: {rec.get('msg', '')}")
            logger.info(f"    文件 mtime: {rec.get('mtime', '未知')}")
            logger.info(f"    记录更新: {rec.get('updated_at', '未知')}")
        return 0

    if action == "clear":
        store.clear()
        logger.info(f"已清空 {corrected_dir} 的修订记录")
        return 0

    logger.error(f"未知动作: {action}")
    return 1


def _cmd_assemble(args):
    """从标准化目录和校正目录合成最终目录。"""
    baseline = _resolve_path(args.baseline_dir)
    corrected = _resolve_path(args.corrected_dir)
    output = _resolve_path(args.output_dir)

    if not os.path.isdir(baseline):
        logger.error(f"标准化目录不存在: {baseline}")
        return 1
    if not os.path.isdir(corrected):
        logger.error(f"校正目录不存在: {corrected}")
        return 1

    DirectoryAssembler(baseline, corrected, output).assemble()
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="txt_file_processing",
        description="pixiv-novel-epub：Pixiv 小说下载后的文本整理工具：合并、批量格式化、单文件格式化、两文件比对。",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p_merge = sub.add_parser(
        "merge",
        help="按章节顺序合并一个或多个目录下所有 txt 为单个文件；"
             "多目录时按数字前缀配对，后列的目录优先（如 corrected/ 覆盖 standardized/）"
    )
    p_merge.add_argument("input_folders", nargs="+",
                         help="一个或多个存放待合并 txt 的目录；"
                              "多目录时校正目录应写在后面（例：merge standardized/ corrected/ out.txt）")
    p_merge.add_argument("output_file", help="合并后输出文件路径")
    p_merge.add_argument("--info", dest="info", action="store_true",
                         help="合并前根据实际参与合并的章节字数刷新 000 书籍信息.txt "
                              "中的『字数』行（合并输出开头的书籍信息会随之更新）。默认开启。")
    p_merge.add_argument("--no-info", dest="info", action="store_false",
                         help="不更新 000 书籍信息.txt 中的字数，按现状合并。")
    p_merge.add_argument("--volumes", default=None,
                         help="卷/篇配置文件路径（JSON 列表，与 epub --volumes 同格式；"
                              "每卷的第一章前插入卷名行）")
    p_merge.add_argument("--indent", action="store_true",
                         help="正文段落加两个全角空格首行缩进"
                              "（000 书籍信息、章节标题行、卷名行不缩进）")
    p_merge.add_argument("--maker", default=None, metavar="名字",
                         help="制作人署名（如 Laffey）；合并时在 000 书籍信息.txt 的"
                              "'字数' 行后写入/更新 'TXT制作：<名字>' 行")
    p_merge.set_defaults(func=_cmd_merge, info=True)

    p_fmt_batch = sub.add_parser("format", help="批量重命名 + 顶部注入章节标题 + 段落空行")
    p_fmt_batch.add_argument("input_folder", help="原始章节 txt 所在目录")
    p_fmt_batch.add_argument("output_folder", nargs="?", default=None,
                             help="格式化后输出目录（缺省时输出到输入目录同级的 standardized/）")
    p_fmt_batch.add_argument("--punct", action="store_true",
                             help="同时把英文标点 (! ? \") 转为中文标点（！？“ ”），引号按奇偶配对")
    p_fmt_batch.set_defaults(func=_cmd_format_batch)

    p_fmt_one = sub.add_parser("format-single", help="为单个 txt 段落间加空行")
    p_fmt_one.add_argument("input_file", help="原始 txt 路径")
    p_fmt_one.add_argument("output_file", help="格式化后输出路径")
    p_fmt_one.set_defaults(func=_cmd_format_single)

    p_cmp = sub.add_parser("compare", help="逐段比对两个 txt 并输出差异")
    p_cmp.add_argument("file1", help="比对文件1")
    p_cmp.add_argument("file2", help="比对文件2")
    p_cmp.add_argument("output_file", nargs="?", default=None, help="差异输出文件（默认 text_differences.txt）")
    p_cmp.set_defaults(func=_cmd_compare)

    p_punct = sub.add_parser("punct", help="将单个 txt 中的英文标点 ! ? \" 转为中文标点 ！？“ ”（引号按奇偶配对）")
    p_punct.add_argument("input_file", help="原始 txt 路径")
    p_punct.add_argument("output_file", nargs="?", default=None,
                         help="转换后输出路径（默认原地覆盖输入文件）")
    p_punct.set_defaults(func=_cmd_punct)

    p_diff = sub.add_parser("diff", help="目录级批量对比标准化目录与校正目录")
    p_diff.add_argument("baseline_dir", help="标准化目录（format 输出）")
    p_diff.add_argument("corrected_dir", help="校正目录（人工修改后）")
    p_diff.add_argument("report_file", nargs="?", default=None,
                        help="差异报告输出文件（可选；不指定则只进日志）")
    p_diff.add_argument("--preview", type=int, default=3,
                        help="控制台每文件差异预览条数，日志/报告保留全部（默认: 3）")
    p_diff.set_defaults(func=_cmd_diff)

    p_note = sub.add_parser("note", help="管理校正目录的修订说明 _revisions.json")
    p_note.add_argument("action", choices=["add", "remove", "list", "clear"],
                        help="add=新增/覆盖一条；remove=删除；list=列出全部；clear=清空")
    p_note.add_argument("corrected_dir", help="校正目录路径")
    p_note.add_argument("filename", nargs="?", default=None,
                        help="目标文件名（相对名，不含路径，add/remove 必填）")
    p_note.add_argument("--msg", default=None,
                        help="修订说明（add 必填），如：删除作者 PS 与两处错字")
    p_note.set_defaults(func=_cmd_note)

    p_asm = sub.add_parser("assemble", help="从标准化目录+校正目录合成最终目录")
    p_asm.add_argument("baseline_dir", help="标准化目录（format 输出）")
    p_asm.add_argument("corrected_dir", help="校正目录（人工修改的子集或完整副本）")
    p_asm.add_argument("output_dir", help="最终合成输出目录")
    p_asm.set_defaults(func=_cmd_assemble)

    p_epub = sub.add_parser(
        "epub",
        help="把章节目录打包为 EPUB 电子书（多目录按数字前缀配对，后列目录优先；"
             "元数据自动取自 000 书籍信息.txt 或 pixiv 系列信息）"
    )
    p_epub.add_argument("input_folders", nargs="*",
                        help="一个或多个章节 txt 目录；多目录时校正目录应写在后面"
                             "（例：epub standardized/ corrected/ 全书.epub；"
                             "--title-styles 列表模式可省略）")
    p_epub.add_argument("output_file", nargs="?",
                        help="输出的 .epub 文件路径（--title-styles 列表模式可省略）")
    p_epub.add_argument("--title", default=None,
                        help="覆盖书名（默认从 000 书籍信息.txt 或 pixiv 信息读取）")
    p_epub.add_argument("--author", default=None,
                        help="覆盖作者（默认从 000 书籍信息.txt 或 pixiv 信息读取）")
    p_epub.add_argument("--maker", default=None, metavar="名字",
                        help="制作人署名（如 Laffey）；书籍信息页在 '字数' 行后渲染 "
                             "'EPUB制作：<名字>' 行；未指定时回退 000 书籍信息.txt "
                             "中的制作人行（TXT制作/EPUB制作/制作人）")
    p_epub.add_argument("--volumes", default=None,
                        help="卷/篇配置文件路径（JSON 列表："
                             "[{\"name\": \"第一卷 xxx\", \"start\": 1, \"end\": 17}, ...]；"
                             "每卷生成一个独立占页的卷页，并作为目录的上级嵌套）")
    p_epub.add_argument("--title-style", default=None,
                        help="章标题样式预设名（epub_styles.json 的 \"chapter\" 段，"
                             "可用 --title-styles 查看；显式传入的 --title-align 等参数会覆盖预设）")
    p_epub.add_argument("--vol-style", default=None,
                        help="卷名样式预设名（epub_styles.json 的 \"volume\" 段，"
                             "可用 --title-styles 查看；默认使用内置卷名样式）")
    p_epub.add_argument("--title-styles", action="store_true",
                        help="列出 epub_styles.json 中全部样式预设（chapter 章标题 + volume 卷名，不打包）")
    p_epub.add_argument("--title-styles-file", default=None,
                        help="样式预设文件路径（默认项目根目录 epub_styles.json）")
    p_epub.add_argument("--cover", default=None,
                        help="封面图片路径（jpg/png/gif/webp）；不指定时自动查找"
                             "输入目录及其父目录下的 cover.* / 封面.* 图片（如下载器保存的封面）")
    p_epub.add_argument("--illustrations", default=None,
                        help="插图信息文件路径（txt 或 JSON 两种格式，自动识别）；"
                             "不指定时自动查找输入目录中的 插图信息.txt / 插图信息.json"
                             "（条目按 ch<编号> 文件名或章节头归属章节，放到对应章节末尾）")
    p_epub.add_argument("--image-quality", type=int, default=None,
                        help="插图压缩质量（1-100，如 80）：把插图重编码为 JPEG 减小体积"
                             "（需安装 Pillow；PNG/JPEG 均可，压缩后未变小则保留原图）。"
                             "不指定则不压缩")
    p_epub.add_argument("--title-align", choices=["center", "left"], default=None,
                        help="章标题对齐方式（默认: center；优先级高于样式预设）")
    p_epub.add_argument("--title-color", default=None,
                        help="章标题颜色（CSS 颜色值，如 #8B0000 深红；默认继承正文黑色；"
                             "优先级高于样式预设）")
    p_epub.add_argument("--title-size", default=None,
                        help="章标题字号（CSS 字号，如 1.5em / 24px；默认: 1.5em；"
                             "优先级高于样式预设）")
    title_line = p_epub.add_mutually_exclusive_group()
    title_line.add_argument("--title-underline", dest="title_underline",
                            action="store_true", default=None,
                            help="章标题下加 2px 实线（颜色同标题色，未设色时默认 #8B0000）")
    title_line.add_argument("--no-title-underline", dest="title_underline",
                            action="store_false", default=None,
                            help="标题下不加线（关闭样式预设里的下划线）")
    p_epub.set_defaults(func=_cmd_epub)

    p_split = sub.add_parser(
        "split",
        help="拆卷：把一卷一个文件、卷内章节未划分的原始下载内容（或外来整本 txt）"
             "拆成独立章节文件（识别第X章/番外/纯数字编号标记行，按顺序修正作者"
             "编号错误，全局连续编号导出到输出目录，并在其上级目录生成 volumes.json）"
    )
    p_split.add_argument("input",
                         help="卷打包的原始章节 txt 目录（如 chapters/），"
                              "或外来整本 txt 文件（视为单卷）")
    p_split.add_argument("output_dir", help="拆分后章节输出目录（如 standardized/）")
    p_split.add_argument("--punct", action="store_true",
                         help="同时把英文标点 (! ? \") 转为中文标点（！？“ ”）")
    p_split.add_argument("--name-only", action="store_true",
                         help="文件名只保留章节名不带章节号（如 003 雪棠.txt；"
                              "完整标题仍保留在文件首行）。默认文件名含完整章节标题"
                              "（如 003 第3章 雪棠.txt）")
    p_split.add_argument("--title-len-limit", action="store_true",
                         help="严格模式：无空格的章节标记额外要求整行 <= 20 字符"
                              "（默认关闭，仅靠\"不含句号\"判定，兼容标题较长的网文；"
                              "开启可进一步防正文长句误判）")
    p_split.add_argument("--unify-title", action="store_true",
                         help="标题统一为 \"第X章 章名\"（编号转中文数字、冒号/粘连"
                              "归一为空格、纯数字编号 407：xxx / 588xxx 补第/章式）。"
                              "适合章节号类型混杂的外来整本 txt；默认保持各标记原格式")
    p_split.add_argument("--num-style", choices=["chinese", "arabic"],
                         default="chinese",
                         help="--unify-title 时的编号风格：chinese=第一章（默认），"
                              "arabic=第407章")
    p_split.add_argument("--no-renumber", action="store_true",
                         help="关闭章节编号重排：保留作者原编号，导出文件名前缀沿用"
                              "原编号（编号缺口即漏章线索，缺口/重复会在日志报告）；"
                              "默认按出现顺序重排为连续编号")
    p_split.add_argument("--max-gap", type=int, default=None, metavar="N",
                         help="章节编号连续性校验上限：新识别编号比最高编号回退超过 N 章"
                              "的标记行不视为章节（并入上一章正文并记入 _编号统计.txt；"
                              "同号同题的作者重发放行）；前向跳变不校验（缺号块属正常）；"
                              "0 关闭校验。默认取 split_config.json 的 chapter_gap_limit（10）")
    p_split.set_defaults(func=_cmd_split)

    p_toc = sub.add_parser(
        "toc",
        help="章节目录导出/检查/回写：可清理标题，或按真实编号查看缺号与重复号"
    )
    toc_sub = p_toc.add_subparsers(dest="toc_action", required=True)
    p_toc_export = toc_sub.add_parser(
        "export",
        help="导出章节目录（章节目录模式：NNN 标题；整本 txt 模式：预览标记识别+缺口分析）"
    )
    p_toc_export.add_argument("path",
                              help="章节目录（如 standardized/），或整本 txt 文件")
    p_toc_export.add_argument("output_file", nargs="?",
                              help="输出目录文件（缺省：目录模式 <目录>/_toc.txt；"
                                   "文件模式 <同名>_toc.txt）")
    p_toc_inspect = toc_sub.add_parser(
        "inspect",
        help="导出纯章节检查目录：按真实编号排序、保留重复号并插入缺号占位行"
    )
    p_toc_inspect.add_argument("path",
                               help="章节目录，或含章节标记的整本 txt 文件")
    p_toc_inspect.add_argument(
        "output_file", nargs="?",
        help="输出文件（缺省：目录模式 <目录>/_toc_inspect.txt；"
             "文件模式 <同名>_toc_inspect.txt）"
    )
    p_toc_apply = toc_sub.add_parser(
        "apply",
        help="回写人工编辑后的目录（目录模式：重命名+改首行；txt 模式：替换标记行）"
    )
    p_toc_apply.add_argument("path",
                             help="章节目录（按 NNN 重命名文件并替换首行标题），"
                                  "或整本 txt 文件（按顺序替换章节标记行，自动 .bak 备份）")
    p_toc_apply.add_argument("toc_file",
                             help="toc export 导出并人工编辑后的目录文件")
    p_toc.set_defaults(func=_cmd_toc)

    return parser


def main(argv=None):
    """后处理命令入口；``argv`` 便于统一 CLI 转发和自动化测试。"""
    configure_postprocess_logging(str(PROJECT_ROOT))
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)
