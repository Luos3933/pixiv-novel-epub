"""章节命名、解析和多目录覆盖规则。"""

from .markers import (
    chapter_number_to_chinese,
    chinese_chapter_number_to_int,
    parse_chapter_marker,
    unify_chapter_marker,
)
from .numbering import (
    allocate_output_number,
    build_number_report,
    chapter_name,
    compress_ranges,
    describe_number_gaps,
    normalize_title_key,
    renumber_segments,
)
from .overlay import build_prefix_index, collect_text_overlay, file_prefix, list_text_files
from .scanning import ChapterScanResult, scan_chapter_segments, scan_marker_lines
from .splitting import (
    SplitInputs,
    discover_split_inputs,
    find_volume_overlaps,
    list_chapter_text_files,
    numeric_filename_sort_key,
    sanitize_filename_part,
    scan_suspicious_markers,
    volume_name_from_filename,
    write_volumes_file,
)
from .toc import TocManager
from .volumes import load_volumes_file

__all__ = [
    "build_prefix_index",
    "build_number_report",
    "allocate_output_number",
    "chapter_number_to_chinese",
    "chinese_chapter_number_to_int",
    "collect_text_overlay",
    "compress_ranges",
    "chapter_name",
    "ChapterScanResult",
    "describe_number_gaps",
    "file_prefix",
    "list_text_files",
    "load_volumes_file",
    "normalize_title_key",
    "parse_chapter_marker",
    "renumber_segments",
    "scan_chapter_segments",
    "scan_marker_lines",
    "SplitInputs",
    "TocManager",
    "discover_split_inputs",
    "find_volume_overlaps",
    "list_chapter_text_files",
    "numeric_filename_sort_key",
    "sanitize_filename_part",
    "scan_suspicious_markers",
    "unify_chapter_marker",
    "volume_name_from_filename",
    "write_volumes_file",
]
