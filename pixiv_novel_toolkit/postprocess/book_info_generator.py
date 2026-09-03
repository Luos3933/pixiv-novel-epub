"""流水线书籍信息文件的发现、生成与刷新。"""

import logging
import os
import re

from pixiv_novel_toolkit.chapters.overlay import collect_text_overlay
from .book_info import (
    BLANK_BOOK_INFO_TEMPLATE,
    TEXT_BOOK_INFO_TEMPLATE,
    format_update_date,
    format_word_count,
    parse_pixiv_info_file,
    parse_pixiv_metadata_file,
    upsert_maker_line,
)


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


class BookInfoGenerator:
    """生成或刷新流水线中的 ``000 书籍信息.txt``。"""

    TEMPLATE = TEXT_BOOK_INFO_TEMPLATE
    BLANK_TEMPLATE = BLANK_BOOK_INFO_TEMPLATE

    def __init__(self, source_dir, template_file=None):
        self.source_dirs = [source_dir] if isinstance(source_dir, str) else list(source_dir)
        self.source_dir = self.source_dirs[0]
        self.template_file = template_file

    def _find_pixiv_info(self):
        candidates = [self.source_dir]
        parent = os.path.dirname(self.source_dir)
        if parent:
            candidates.append(parent)
            grandparent = os.path.dirname(parent)
            if grandparent:
                candidates.append(grandparent)
        for directory in candidates:
            if not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if filename.endswith("_info.txt") and filename.startswith("series_"):
                    return self._parse_info_txt(os.path.join(directory, filename))
                if filename == "_info.txt":
                    return self._parse_info_txt(os.path.join(directory, filename))
            for filename in os.listdir(directory):
                if filename.endswith("_metadata.json") and filename.startswith("series_"):
                    return self._parse_metadata(os.path.join(directory, filename), directory)
        return None

    def _parse_info_txt(self, info_path):
        return parse_pixiv_info_file(info_path)

    def _parse_metadata(self, meta_path, data_dir):
        return parse_pixiv_metadata_file(meta_path)

    def _scan_chapter_stats(self, output_dir):
        if not os.path.isdir(output_dir):
            return 0, 0
        main_count = extra_count = 0
        for filename in os.listdir(output_dir):
            if not filename.lower().endswith(".txt"):
                continue
            if filename.startswith(("000 ", "_")):
                continue
            if "番外" in filename:
                extra_count += 1
            else:
                main_count += 1
        return main_count, extra_count

    @staticmethod
    def _format_wan(word_count):
        return format_word_count(word_count)

    @staticmethod
    def _extract_date(update_time):
        return format_update_date(update_time)

    def generate(self, output_dir):
        info = self._find_pixiv_info()
        if info is None:
            content = self.BLANK_TEMPLATE
            logger.info("未能定位 pixiv 信息源，生成空白占位书籍信息模板（请手动填写）")
        else:
            main_count, extra_count = self._scan_chapter_stats(self.source_dir)
            if main_count + extra_count == 0:
                main_count = info.get("chapter_count", 0)
                extra_count = info.get("extra_count", 0)
            status_parts = []
            if main_count:
                status_parts.append(f"{main_count}章")
            if extra_count:
                status_parts.append(f"{extra_count}番外")
            status_base = "+".join(status_parts) if status_parts else "未知"
            update_date = self._extract_date(info.get("update_time", ""))
            status = (
                f"{status_base}（{update_date}）"
                if update_date != "未知日期"
                else status_base
            )
            content = self.TEMPLATE.format(
                title=info.get("title", "未填") or "未填",
                author=info.get("author", "未填") or "未填",
                platform=info.get("platform", "Pixiv"),
                status=status,
                word_count=self._format_wan(info.get("word_count", 0)),
                description=info.get("description", "未填") or "未填",
            )
        output_path = os.path.join(output_dir, "000 书籍信息.txt")
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(content + "\n")
        logger.info(f"已生成: {output_path}")
        return output_path

    @staticmethod
    def _count_chars_in_dir(directory):
        total = 0
        if not os.path.isdir(directory):
            return total
        for filename in os.listdir(directory):
            if not filename.lower().endswith(".txt"):
                continue
            if filename.startswith(("000 ", "_")):
                continue
            try:
                with open(os.path.join(directory, filename), "r", encoding="utf-8") as file:
                    total += sum(len(line.strip()) for line in file if line.strip())
            except OSError as error:
                logger.warning(f"  统计字数失败 {filename}: {error}")
        return total

    def _collect_chapters_for_merge(self):
        overlay = collect_text_overlay(self.source_dirs, exclude_book_info=True)

        def sort_key(item_key):
            if isinstance(item_key, str) and item_key.isdigit():
                return 0, int(item_key)
            return 1, item_key

        return [(key, overlay[key][1]) for key in sorted(overlay, key=sort_key)]

    def _count_chars_for_merge(self):
        total = 0
        for key, path in self._collect_chapters_for_merge():
            try:
                with open(path, "r", encoding="utf-8") as file:
                    total += sum(len(line.strip()) for line in file if line.strip())
            except OSError as error:
                logger.warning(f"  统计字数失败 {key}: {error}")
        return total

    def _count_chapters_for_merge(self):
        main_count = extra_count = 0
        for _, path in self._collect_chapters_for_merge():
            if "番外" in os.path.basename(path):
                extra_count += 1
            else:
                main_count += 1
        return main_count, extra_count

    @staticmethod
    def _find_existing_book_info(directory):
        candidates = [directory]
        parent = os.path.dirname(directory)
        if parent:
            candidates.extend((os.path.join(parent, "standardized"), parent))
        for candidate in candidates:
            if not candidate or not os.path.isdir(candidate):
                continue
            path = os.path.join(candidate, "000 书籍信息.txt")
            if os.path.isfile(path):
                return path
        return None

    def _find_newest_book_info(self):
        candidates = []
        for directory in self.source_dirs:
            path = self._find_existing_book_info(directory)
            if path and path not in candidates:
                candidates.append(path)
        return max(candidates, key=os.path.getmtime) if candidates else None

    def _find_book_info_direct(self):
        candidates = []
        for directory in self.source_dirs:
            path = os.path.join(directory, "000 书籍信息.txt")
            if os.path.isfile(path) and path not in candidates:
                candidates.append(path)
        return max(candidates, key=os.path.getmtime) if candidates else None

    def update_word_count_for_merge(
        self,
        output_dir=None,
        search_parent=True,
        volumes=None,
        maker=None,
    ):
        existing = (
            self._find_newest_book_info()
            if search_parent
            else self._find_book_info_direct()
        )
        if existing is None:
            logger.warning(
                "未找到现有 000 书籍信息.txt 作为模板来源（各源目录及其同级 "
                "standardized 目录均无）；跳过书籍信息刷新。"
            )
            return None
        with open(existing, "r", encoding="utf-8") as file:
            content = file.read()

        actual_word_count = self._count_chars_for_merge()
        word_count_text = self._format_wan(actual_word_count)
        new_content, replaced = re.subn(
            r"^字数[：:].*$",
            f"字数：{word_count_text}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if replaced == 0:
            logger.warning(f"未找到 '字数：...' 行，未能更新 {existing} 中的字数字段。")
            return None

        main_count, extra_count = self._count_chapters_for_merge()
        status_parts = []
        if main_count:
            status_parts.append(f"{main_count}章")
        if extra_count:
            status_parts.append(f"{extra_count}番外")
        status_base = "+".join(status_parts) if status_parts else "未知"
        old_status = re.search(r"^连载状态[：:].*$", new_content, flags=re.MULTILINE)
        date_suffix = ""
        if old_status:
            date_match = re.search(r"（([^）]*)）", old_status.group(0))
            if date_match:
                date_suffix = f"（{date_match.group(1)}）"
        new_content, status_replaced = re.subn(
            r"^连载状态[：:].*$",
            f"连载状态：{status_base}{date_suffix}",
            new_content,
            count=1,
            flags=re.MULTILINE,
        )
        if status_replaced == 0:
            logger.warning(f"未找到 '连载状态：...' 行，未能更新 {existing} 中的章节数字段。")

        new_content = re.sub(
            r"^卷/篇数[：:].*$\n?", "", new_content, flags=re.MULTILINE
        )
        if volumes:
            new_content, volume_replaced = re.subn(
                r"(^连载状态[：:].*$\n?)",
                rf"\g<1>卷/篇数：{len(volumes)}\n",
                new_content,
                count=1,
                flags=re.MULTILINE,
            )
            if volume_replaced:
                logger.info(f"已补充书籍信息卷/篇数: {len(volumes)}")
        new_content, _ = self._upsert_maker_line(new_content, maker)

        target = output_dir or self.source_dirs[-1]
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        output_path = os.path.join(target, "000 书籍信息.txt")
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(new_content)
        logger.info(
            f"已刷新书籍信息: {output_path} "
            f"(章节 {main_count}章+{extra_count}番外，字数 "
            f"{actual_word_count} → {word_count_text})"
        )
        return output_path

    def update_maker_for_merge(self, maker, output_dir=None, search_parent=True):
        if not maker:
            return None
        existing = (
            self._find_newest_book_info()
            if search_parent
            else self._find_book_info_direct()
        )
        if existing is None:
            logger.warning("未找到现有 000 书籍信息.txt，无法写入 TXT制作 行。")
            return None
        with open(existing, "r", encoding="utf-8") as file:
            content = file.read()
        new_content, replaced = self._upsert_maker_line(content, maker)
        if not replaced:
            logger.warning("未找到 '字数：...' 行，未能写入 TXT制作 行。")
            return None
        target = output_dir or self.source_dirs[-1]
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        output_path = os.path.join(target, "000 书籍信息.txt")
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(new_content)
        return output_path

    @staticmethod
    def _upsert_maker_line(content, maker):
        return upsert_maker_line(content, maker, info=logger.info)
