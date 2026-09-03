"""卷文件或整本 TXT 的章节拆分编排。"""

import logging
import os

from .markers import (
    BARE_HEAD_RE,
    BARE_SUFFIX_RE,
    FANWAI_RE,
    GLUED_BLOCK_CHARS,
    GLUED_QUANTITY_STARTERS,
    MARKER_RE,
    parse_chapter_marker,
    unify_chapter_marker,
)
from .numbering import (
    allocate_output_number,
    build_number_report,
    chapter_name,
    describe_number_gaps,
    normalize_title_key,
    renumber_segments,
)
from .scanning import scan_chapter_segments
from .split_config import load_split_config
from .splitting import (
    discover_split_inputs,
    find_volume_overlaps,
    sanitize_filename_part,
    scan_suspicious_markers,
    volume_name_from_filename,
    write_volumes_file,
)
from pixiv_novel_toolkit.common.textio import read_text, read_text_lines
from pixiv_novel_toolkit.postprocess.book_info_generator import BookInfoGenerator
from pixiv_novel_toolkit.postprocess.formatting import (
    convert_punctuation,
    interleave_blank_lines,
)


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


class VolumeSplitter:
    """把一卷一个文件或整本 TXT 拆成独立章节并生成编号诊断。"""

    MARKER_RE = MARKER_RE
    FANWAI_RE = FANWAI_RE
    BARE_SUFFIX_RE = BARE_SUFFIX_RE
    BARE_HEAD_RE = BARE_HEAD_RE
    GLUED_BLOCK_CHARS = GLUED_BLOCK_CHARS
    GLUED_QUANTITY_STARTERS = GLUED_QUANTITY_STARTERS

    def __init__(
        self,
        input_dir,
        output_dir,
        punct=False,
        name_only=False,
        title_len_limit=False,
        unify_title=False,
        num_style="chinese",
        renumber=True,
        max_gap=None,
        marker_max_len=None,
    ):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.punct = punct
        self.name_only = name_only
        self.title_len_limit = title_len_limit
        self.unify_title = unify_title
        self.num_style = num_style
        self.renumber = renumber
        config = load_split_config()
        self.gap_limit = (
            config["chapter_gap_limit"] if max_gap is None else max_gap
        )
        self.marker_max_len = (
            config["marker_max_len"] if marker_max_len is None else marker_max_len
        )
        self._rejected_markers = []

    def _parse_marker(self, line):
        return parse_chapter_marker(
            line,
            marker_max_len=self.marker_max_len,
            title_len_limit=self.title_len_limit,
        )

    def _unified_marker(self, marker):
        return unify_chapter_marker(marker, num_style=self.num_style)

    def _split_file(self, path):
        lines = read_text_lines(path, info=logger.info)
        result = scan_chapter_segments(
            lines,
            self._parse_marker,
            gap_limit=self.gap_limit,
            unify_marker=self._unified_marker if self.unify_title else None,
            info=logger.info,
            warn=logger.warning,
        )
        self._rejected_markers.extend(result.rejected_markers)
        return result.segments, result.preamble

    @staticmethod
    def _norm_title_key(title):
        return normalize_title_key(title)

    def _renumber_segments(self, segments):
        return renumber_segments(segments)

    @staticmethod
    def _chapter_name(title):
        return chapter_name(title)

    def _alloc_out_num(self, preferred):
        output_number, self._last_out = allocate_output_number(
            preferred,
            self._used_nums,
            self._last_out,
            warn=logger.warning,
        )
        return output_number

    def split(self):
        inputs = discover_split_inputs(self.input_dir)
        if inputs is None:
            logger.error(f"输入路径不存在（应为目录或整本 txt 文件）: {self.input_dir}")
            return None
        source_dir = inputs.source_dir
        text_files = inputs.filenames
        os.makedirs(self.output_dir, exist_ok=True)
        if not text_files:
            logger.error(f"输入目录 {self.input_dir} 中没有 txt 文件。")
            return None

        self._used_nums = set()
        self._last_out = 0
        self._export_log = []
        volumes = []
        total_fixed = total_preamble = 0
        logger.info(
            f"拆卷开始: {self.input_dir} -> {self.output_dir}"
            f"（{len(text_files)} 个文件"
            + ("，unify-title 统一标题" if self.unify_title else "")
            + ("，no-renumber 保留原编号" if not self.renumber else "")
            + "）"
        )
        for filename in text_files:
            path = os.path.join(source_dir, filename)
            segments, preamble = self._split_file(path)
            if preamble:
                total_preamble += 1
                logger.info(
                    f"  {filename}: 跳过卷标题/前言 {len(preamble)} 行"
                    f"（{' '.join(line[:20] for line in preamble[:2])}...）"
                )
            volume_name = volume_name_from_filename(filename)
            if not segments:
                content = read_text(path, info=logger.info)
                output_number = self._alloc_out_num(None)
                output_name = (
                    f"{output_number:03d} {sanitize_filename_part(volume_name)}.txt"
                )
                self._write_chapter(output_name, content)
                self._export_log.append(
                    {"orig": None, "out": output_number, "name": output_name}
                )
                logger.info(f"  [{output_number:03d}] {volume_name}（整文件无卷内标记）")
                continue

            fixed = 0
            if self.renumber:
                segments, fixed = self._renumber_segments(segments)
                total_fixed += fixed
            volume_outputs = []
            for segment in segments:
                original_number = segment["mk"]["num"]
                preferred = None if self.renumber else original_number
                output_number = self._alloc_out_num(preferred)
                volume_outputs.append(output_number)
                title = segment["title"].strip()
                name = self._chapter_name(title) if self.name_only else title
                output_name = f"{output_number:03d} {sanitize_filename_part(name)}.txt"
                self._export_log.append(
                    {
                        "orig": original_number,
                        "out": output_number,
                        "name": output_name,
                    }
                )
                self._write_chapter(output_name, "\n".join([title] + segment["lines"]))
                logger.info(f"  [{output_number:03d}] {title}")
            volumes.append(
                {
                    "name": volume_name,
                    "start": min(volume_outputs),
                    "end": max(volume_outputs),
                }
            )
            logger.info(
                f"  卷「{volume_name}」: 章节 {min(volume_outputs):03d}"
                f"~{max(volume_outputs):03d}"
                + (f"（编号修正 {fixed} 处）" if fixed else "")
            )

        self._suspicious = []
        if inputs.single_file:
            lines = read_text_lines(
                os.path.join(source_dir, text_files[0]), info=logger.info
            )
            self._suspicious = scan_suspicious_markers(
                lines,
                self._export_log,
                self._rejected_markers,
                self.GLUED_QUANTITY_STARTERS,
            )

        gaps = []
        if not self.renumber:
            gaps = describe_number_gaps(self._used_nums)
            for previous, current in find_volume_overlaps(volumes):
                logger.warning(
                    f"  卷范围重叠: 「{previous['name']}」{previous['start']:03d}"
                    f"~{previous['end']:03d} 与「{current['name']}」"
                    f"{current['start']:03d}~{current['end']:03d}，请人工核对"
                )
        if gaps:
            logger.warning(
                "编号缺口（原文缺号或有章节未被识别，可用 toc export 复查）: "
                + "；".join(gaps)
            )

        volumes_path = write_volumes_file(self.output_dir, volumes)
        try:
            BookInfoGenerator(source_dir).generate(self.output_dir)
        except Exception as error:
            logger.warning(f"生成 000 书籍信息.txt 失败: {error}")
        report_path = self._write_num_report()
        chapter_count = len(self._used_nums)
        logger.info(
            f"拆卷完成: 共导出 {chapter_count} 章（{len(volumes)} 卷"
            + (f"，编号修正 {total_fixed} 处" if total_fixed else "")
            + (f"，保留原编号（缺口 {len(gaps)} 处）" if not self.renumber else "")
            + (
                f"，连续性校验拒绝 {len(self._rejected_markers)} 行"
                if self._rejected_markers
                else ""
            )
            + f"，跳过前言 {total_preamble} 个文件）"
        )
        logger.info(f"卷配置已生成: {volumes_path}")
        logger.info(f"编号统计已生成: {report_path}")
        return {
            "chapters": chapter_count,
            "volumes": len(volumes),
            "fixed": total_fixed,
            "preamble_files": total_preamble,
            "volumes_file": volumes_path,
            "gaps": len(gaps),
            "report": report_path,
        }

    def _write_num_report(self):
        path = os.path.join(self.output_dir, "_编号统计.txt")
        with open(path, "w", encoding="utf-8") as file:
            file.write(
                build_number_report(
                    getattr(self, "_export_log", []),
                    rejected_markers=getattr(self, "_rejected_markers", []),
                    suspicious=getattr(self, "_suspicious", []),
                    gap_limit=getattr(self, "gap_limit", 0),
                )
            )
        return path

    def _write_chapter(self, output_name, content):
        if self.punct:
            content, _ = convert_punctuation(content)
        lines = [line.strip() for line in content.splitlines()]
        output_path = os.path.join(self.output_dir, output_name)
        with open(output_path, "w", encoding="utf-8") as file:
            file.write("\n".join(interleave_blank_lines(lines)) + "\n")
