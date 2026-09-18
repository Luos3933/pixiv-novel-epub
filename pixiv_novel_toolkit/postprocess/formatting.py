"""TXT 段落、标点与章节文件格式化。"""

import logging
import os
import re

from pixiv_novel_toolkit.chapters.markers import chapter_number_to_chinese
from pixiv_novel_toolkit.chapters.overlay import collect_text_overlay
from .book_info_generator import BookInfoGenerator


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


def interleave_blank_lines(lines):
    """去除空白行，并在每个非空段落后插入一个空行。"""
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            result.extend((stripped, ""))
    return result


def convert_punctuation(text):
    """把 ``! ? \"`` 转为中文标点，并返回转换统计。"""
    characters = []
    front_quotes = back_quotes = 0
    quote_open = True
    for character in text:
        if character == '"':
            if quote_open:
                characters.append("“")
                front_quotes += 1
            else:
                characters.append("”")
                back_quotes += 1
            quote_open = not quote_open
        elif character == "!":
            characters.append("！")
        elif character == "?":
            characters.append("？")
        else:
            characters.append(character)
    original_quotes = text.count('"')
    return "".join(characters), {
        "original_quote": original_quotes,
        "front_quote": front_quotes,
        "back_quote": back_quotes,
        "original_exclamation": text.count("!"),
        "original_question": text.count("?"),
        "unpaired": original_quotes % 2,
    }


class BatchTxtFileFormatter:
    """批量规范章节文件名、段落空行、标题行与可选中文标点。"""

    def __init__(
        self,
        input_folder,
        output_folder,
        punct=False,
        overlay_folders=None,
    ):
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.punct = punct
        self.overlay_folders = list(overlay_folders or [])

    def _number_to_chinese(self, number):
        return chapter_number_to_chinese(number)

    def format_all_files(self):
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)
        input_folders = [self.input_folder, *self.overlay_folders]
        collected = collect_text_overlay(input_folders, warn_missing=logger.warning)
        files = list(collected.values())

        def sort_key(entry):
            filename = entry[0]
            match = re.search(r"^(\d+)", filename)
            return int(match.group(1)) if match else 0

        text_files = sorted(files, key=sort_key)
        source_summary = " + ".join(input_folders)
        logger.info(f"批量格式化开始：{source_summary} -> {self.output_folder}")
        if self.overlay_folders:
            logger.info(
                "人工复核覆盖已启用：后列 reviewed 目录中的同编号文件优先"
            )
        logger.info(f"共发现 {len(text_files)} 个 txt 文件；punct={self.punct}")

        main_chapter_count = 1
        stats_main = stats_extra = stats_skipped = stats_unpaired = 0
        for index, (text_file, input_path) in enumerate(text_files, start=1):
            match = re.search(r"^(\d+)\s+(.*?)(?:\.txt)$", text_file)
            if not match:
                logger.warning(f"[{index:03d}] 跳过不符合命名规则的文件: {text_file}")
                stats_skipped += 1
                continue
            prefix, raw_title = match.group(1), match.group(2)
            kind = "正文"
            if int(prefix) == 0:
                logger.warning(
                    f"[{index:03d}] 跳过编号为 0 的文件: {text_file} "
                    "(书籍信息已改为脚本末尾自动生成 000 书籍信息.txt)"
                )
                stats_skipped += 1
                continue

            clean_title = re.sub(
                r"^第[一二三四五六七八九十百千万零\d]+章\s*", "", raw_title
            ).strip()
            if "番外" in clean_title:
                clean_title = clean_title.replace("番外：", "").replace("番外", "").strip()
                display_title = f"番外：{clean_title}" if clean_title else "番外"
                kind = "番外"
                stats_extra += 1
            else:
                display_title = (
                    f"第{self._number_to_chinese(main_chapter_count)}章 {clean_title}"
                )
                main_chapter_count += 1
                stats_main += 1
            new_filename = f"{prefix} {display_title}.txt"
            output_path = os.path.join(self.output_folder, new_filename)
            with open(input_path, "r", encoding="utf-8") as input_file:
                new_lines = interleave_blank_lines(input_file.readlines())

            punctuation_stats = None
            if self.punct:
                converted, stats = convert_punctuation("\n".join(new_lines))
                new_lines = converted.split("\n")
                punctuation_stats = {
                    "front": stats["front_quote"],
                    "back": stats["back_quote"],
                    "excl": stats["original_exclamation"],
                    "ques": stats["original_question"],
                    "unpaired": stats["unpaired"],
                }
                if stats["unpaired"]:
                    logger.warning(
                        f"[{index:03d}] {text_file}: 奇数个英文双引号 "
                        f"({stats['front_quote']} “ + {stats['back_quote']} ”)，"
                        "前/后引号可能未完整配对。"
                    )
                    stats_unpaired += 1

            with open(output_path, "w", encoding="utf-8") as output_file:
                output_file.write(f"{display_title}\n\n")
                output_file.write("\n".join(new_lines))
            log_message = (
                f"[{index:03d}] {text_file}  ->  {new_filename}  ({kind})"
            )
            if punctuation_stats is not None:
                log_message += (
                    f" | 标点: “{punctuation_stats['front']} ”{punctuation_stats['back']} "
                    f"！{punctuation_stats['excl']} ？{punctuation_stats['ques']}"
                )
            logger.info(log_message)

        BookInfoGenerator(self.input_folder).generate(self.output_folder)
        logger.info(
            f"批量格式化完成：正文 {stats_main} 章，番外 {stats_extra} 篇，"
            f"跳过 {stats_skipped} 个"
            + (f"，含标点未配对警告文件 {stats_unpaired} 个" if self.punct else "")
        )
        logger.info(f"输出目录: {self.output_folder}")


class TxtFileFormatter:
    """为单个 TXT 的非空段落之间添加一个空行。"""

    def __init__(self, input_file, output_file):
        self.input_file = input_file
        self.output_file = output_file

    def add_blank_lines(self):
        with open(self.input_file, "r", encoding="utf-8") as input_file:
            lines = input_file.readlines()
        with open(self.output_file, "w", encoding="utf-8") as output_file:
            output_file.write("\n".join(interleave_blank_lines(lines)))
