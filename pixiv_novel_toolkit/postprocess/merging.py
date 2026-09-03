"""多目录章节覆盖与整本 TXT 合并。"""

import logging
import os

from pixiv_novel_toolkit.chapters.overlay import collect_text_overlay
from pixiv_novel_toolkit.chapters.volumes import load_volumes_file
from .book_info_generator import BookInfoGenerator
from .formatting import interleave_blank_lines


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


class TxtFileMerger:
    """以后列目录优先覆盖同前缀章节，并合并为单个 TXT。"""

    def __init__(
        self,
        input_folders,
        output_file,
        update_info=False,
        volumes_file=None,
        indent=False,
        maker=None,
    ):
        self.input_folders = (
            [input_folders] if isinstance(input_folders, str) else input_folders
        )
        self.output_file = output_file
        self.update_info = update_info
        self.volumes_file = volumes_file
        self.indent = indent
        self.maker = maker

    def _collect_files(self):
        return collect_text_overlay(
            self.input_folders,
            warn_missing=logger.warning,
        )

    def merge_txt_files(self):
        collected = self._collect_files()
        if not collected:
            logger.error("所有输入目录中都没有 txt 文件，无法合并。")
            return

        volumes = (
            load_volumes_file(
                self.volumes_file,
                error=logger.error,
                warning=logger.warning,
                info=logger.info,
            )
            if self.volumes_file
            else []
        )
        if volumes is None:
            logger.error("卷/篇配置读取失败，中止合并（可去掉 --volumes 参数重试）。")
            return

        if self.update_info:
            info_path = BookInfoGenerator(
                self.input_folders
            ).update_word_count_for_merge(volumes=volumes, maker=self.maker)
            if info_path:
                logger.info("已基于实际章节字数刷新 000 书籍信息.txt，将作为合并输出开头。")
                collected = self._collect_files()
            else:
                logger.warning("未能更新 000 书籍信息字数；将按现状合并。")
        elif self.maker:
            info_path = BookInfoGenerator(
                self.input_folders
            ).update_maker_for_merge(self.maker)
            if info_path:
                logger.info(f"已写入书籍信息 TXT制作: {self.maker}")
                collected = self._collect_files()
            else:
                logger.warning("未能写入 TXT制作 行；将按现状合并。")

        def sort_key(item_key):
            if isinstance(item_key, str) and item_key.isdigit():
                return 0, int(item_key)
            return 1, item_key

        sorted_keys = sorted(collected, key=sort_key)
        volume_first_chapters = {}
        for volume in volumes:
            for key in sorted_keys:
                if (
                    key.isdigit()
                    and volume["start"] <= int(key) <= volume["end"]
                ):
                    volume_first_chapters[key] = volume["name"]
                    break

        logger.info(
            f"正在合并 {len(sorted_keys)} 个文件"
            f"（来自 {len(self.input_folders)} 个目录）："
        )
        with open(self.output_file, "w", encoding="utf-8") as output_file:
            for key in sorted_keys:
                filename, file_path = collected[key]
                if key in volume_first_chapters:
                    logger.info(f"  [卷] {volume_first_chapters[key]}")
                    output_file.write(f"\n{volume_first_chapters[key]}\n\n")
                logger.info(
                    f"  [{key}] {filename}  <-  "
                    f"{os.path.basename(os.path.dirname(file_path))}/"
                )
                with open(file_path, "r", encoding="utf-8") as input_file:
                    stripped_lines = [
                        line.strip() for line in input_file.readlines() if line.strip()
                    ]
                if self.indent and key != "000":
                    indented = [stripped_lines[0]] if stripped_lines else []
                    indented.extend("\u3000\u3000" + line for line in stripped_lines[1:])
                    stripped_lines = indented
                if stripped_lines:
                    output_file.write("\n\n".join(stripped_lines))
                    output_file.write("\n\n")
        logger.info(f"合并完成，输出文件为: {self.output_file}")

    def add_blank_lines(self, input_file, output_file):
        with open(input_file, "r", encoding="utf-8") as source:
            lines = source.readlines()
        with open(output_file, "w", encoding="utf-8") as destination:
            destination.write("\n".join(interleave_blank_lines(lines)))
