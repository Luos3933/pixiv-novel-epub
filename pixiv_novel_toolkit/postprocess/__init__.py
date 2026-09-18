"""文本整理阶段的可复用组件。"""

from .assembly import DirectoryAssembler
from .auditing import TextAuditor, audit_lines
from .book_info import (
    format_update_date,
    format_word_count,
    parse_book_info_file,
    parse_pixiv_info_file,
    parse_pixiv_metadata_file,
    upsert_maker_line,
)
from .book_info_generator import BookInfoGenerator
from .cleaning import TextCleaner, clean_text, is_suspected_hard_wrap
from .diffing import DirectoryDiffer, TxtFileComparator, diff_paragraphs
from .formatting import (
    BatchTxtFileFormatter,
    TxtFileFormatter,
    convert_punctuation,
    interleave_blank_lines,
)
from .merging import TxtFileMerger
from .processing_config import (
    TEXT_PROCESSING_DEFAULTS,
    TEXT_PROCESSING_SAMPLE,
    load_text_processing_config,
)
from .revisions import RevisionsStore

__all__ = [
    "DirectoryAssembler",
    "TextAuditor",
    "TextCleaner",
    "BookInfoGenerator",
    "BatchTxtFileFormatter",
    "convert_punctuation",
    "clean_text",
    "audit_lines",
    "DirectoryDiffer",
    "diff_paragraphs",
    "format_update_date",
    "format_word_count",
    "interleave_blank_lines",
    "is_suspected_hard_wrap",
    "load_text_processing_config",
    "parse_book_info_file",
    "parse_pixiv_info_file",
    "parse_pixiv_metadata_file",
    "RevisionsStore",
    "TxtFileComparator",
    "TxtFileFormatter",
    "TxtFileMerger",
    "TEXT_PROCESSING_DEFAULTS",
    "TEXT_PROCESSING_SAMPLE",
    "upsert_maker_line",
]
