"""章节目录导出与标题回写。"""

from datetime import datetime
import logging
import os
import re
import shutil

from .markers import parse_chapter_marker
from .overlay import build_prefix_index, file_prefix
from .scanning import scan_marker_lines
from .splitting import list_chapter_text_files, sanitize_filename_part
from pixiv_novel_toolkit.common.textio import read_text_lines


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


class TocManager:
    """导出章节标题清单，并把人工编辑后的标题回写到目录或整本 TXT。"""

    def __init__(self, path):
        self.path = path

    def export(self, output_file=None):
        if os.path.isdir(self.path):
            return self._export_dir(output_file)
        if os.path.isfile(self.path):
            return self._export_file(output_file)
        logger.error(f"路径不存在（应为章节目录或整本 txt）: {self.path}")
        return None

    def _header(self, kind):
        return [
            f"# {kind}",
            f"# 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# 格式: 每章一行 'NNN 标题'（NNN 为章节编号，用于定位，不可修改；# 注释与空行忽略）",
            "# 清理标题中的连载标注（如 +上架 / (4爆) / 爆更求月票）后运行回写:",
            "#   python txt_file_processing.py toc apply <章节目录或整本txt> <本文件>",
        ]

    def _export_dir(self, output_file):
        files = list_chapter_text_files(self.path)
        if not files:
            logger.error(f"目录 {self.path} 中没有 txt 文件。")
            return None
        if output_file is None:
            output_file = os.path.join(self.path, "_toc.txt")

        lines = self._header("章节目录（章节目录模式导出）")
        prefixes = []
        for filename in files:
            prefix = file_prefix(filename)
            if prefix is None:
                lines.append(f"# 无编号文件（apply 不处理）: {filename}")
                continue
            prefixes.append(int(prefix))
            stem = filename[:-4] if filename.lower().endswith(".txt") else filename
            title = re.sub(r"^\d+\s*", "", stem).strip()
            lines.append(f"{int(prefix):03d} {title}")
        lines.append("")
        comments = self._gap_comments(prefixes)
        lines.extend(comments)
        with open(output_file, "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")
        logger.info(
            f"章节目录已导出: {len(prefixes)} 章 -> {output_file}"
            + (f"（含 {len(comments)} 条编号提示）" if comments else "")
        )
        return {"mode": "dir", "chapters": len(prefixes), "output_file": output_file}

    def _export_file(self, output_file):
        if output_file is None:
            base = os.path.splitext(os.path.basename(self.path))[0]
            parent = os.path.dirname(os.path.abspath(self.path))
            output_file = os.path.join(parent, f"{base}_toc.txt")
        markers = [marker for _, marker in scan_marker_lines(read_text_lines(self.path))]
        if not markers:
            logger.error("整本 txt 中未识别到任何章节标记行（可检查标记格式后重试）。")
            return None

        lines = self._header("章节标记预览（整本 txt 模式：与 split 识别规则一致）")
        numbers = []
        pseudo = 0
        for marker in markers:
            if marker["num"] is None:
                pseudo = max(pseudo, numbers[-1] if numbers else 0) + 1
                lines.append(f"{pseudo:03d} {marker['raw']}")
            else:
                numbers.append(marker["num"])
                lines.append(f"{marker['num']:03d} {marker['raw']}")
        lines.append("")
        comments = self._gap_comments(numbers)
        lines.extend(comments)
        with open(output_file, "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")
        logger.info(
            f"章节标记预览已导出: {len(markers)} 个标记 -> {output_file}"
            + (f"（含 {len(comments)} 条编号提示）" if comments else "")
        )
        return {"mode": "file", "markers": len(markers), "output_file": output_file}

    @staticmethod
    def _gap_comments(numbers):
        comments = []
        sorted_numbers = sorted(numbers)
        for previous, current in zip(sorted_numbers, sorted_numbers[1:]):
            if current <= previous + 1:
                continue
            low, high = previous + 1, current - 1
            missing_range = f"{low:03d}~{high:03d}" if high > low else f"{low:03d}"
            comments.append(
                f"# 提示: {previous:03d} 之后跳到 {current:03d}"
                f"（缺 {missing_range}，可能是漏章或标记未被识别）"
            )
        seen = {}
        for number in numbers:
            seen[number] = seen.get(number, 0) + 1
        for number in sorted(seen):
            if seen[number] > 1:
                comments.append(
                    f"# 提示: 编号 {number:03d} 出现 {seen[number]} 次（作者标号错误）"
                )
        return comments

    def apply(self, toc_file):
        entries = self._read_toc(toc_file)
        if entries is None:
            return None
        if os.path.isdir(self.path):
            return self._apply_dir(entries)
        if os.path.isfile(self.path):
            return self._apply_file(entries)
        logger.error(f"路径不存在（应为章节目录或整本 txt）: {self.path}")
        return None

    def _read_toc(self, toc_file):
        if not os.path.isfile(toc_file):
            logger.error(f"目录文件不存在: {toc_file}")
            return None
        entries = []
        for line_number, line in enumerate(read_text_lines(toc_file), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"^(\d{1,4})\s+(.+)$", stripped)
            if not match:
                logger.warning(
                    f"目录文件第 {line_number} 行无法解析（应为 'NNN 标题'），"
                    f"跳过: {stripped}"
                )
                continue
            entries.append((int(match.group(1)), match.group(2).strip()))
        if not entries:
            logger.error("目录文件中没有可用的章节条目。")
            return None
        return entries

    def _apply_dir(self, entries):
        prefix_map, _ = build_prefix_index(self.path, warn=logger.warning)
        updated = missed = skipped_firstline = 0
        for number, title in entries:
            filename = prefix_map.get(f"{number:03d}") or prefix_map.get(str(number))
            if not filename:
                logger.warning(
                    f"[{number:03d}] 目录中没有该编号的章节文件，跳过: {title}"
                )
                missed += 1
                continue
            old_path = os.path.join(self.path, filename)
            stem = filename[:-4] if filename.lower().endswith(".txt") else filename
            old_title = re.sub(r"^\d+\s*", "", stem).strip()
            new_name = f"{number:03d} {sanitize_filename_part(title)}.txt"
            new_path = os.path.join(self.path, new_name)
            if new_path != old_path and os.path.exists(new_path):
                logger.error(
                    f"[{number:03d}] 目标文件名已存在，为防覆盖保留原名: {new_name}"
                )
                continue

            lines = read_text_lines(old_path)
            first_index = next(
                (index for index, line in enumerate(lines) if line.strip()), None
            )
            replaced = False
            if first_index is not None:
                first = lines[first_index].strip()
                if parse_chapter_marker(first) or first == old_title:
                    lines[first_index] = title
                    replaced = True
            if not replaced:
                logger.warning(
                    f"[{number:03d}] 首行不是标题行，仅重命名文件: {filename}"
                )
                skipped_firstline += 1
            with open(old_path, "w", encoding="utf-8") as file:
                file.write("\n".join(lines) + "\n")
            if new_path != old_path:
                os.replace(old_path, new_path)
            updated += 1
            logger.info(f"  [{number:03d}] {filename} -> {new_name}")
        logger.info(
            f"目录回写完成: 更新 {updated} 章"
            + (f"，未匹配 {missed} 条" if missed else "")
            + (f"，{skipped_firstline} 章仅重命名" if skipped_firstline else "")
        )
        return {
            "mode": "dir",
            "updated": updated,
            "missed": missed,
            "firstline_skipped": skipped_firstline,
        }

    def _apply_file(self, entries):
        lines = read_text_lines(self.path)
        marker_indexes = [index for index, _ in scan_marker_lines(lines)]
        if len(marker_indexes) != len(entries):
            logger.error(
                f"目录条目数（{len(entries)}）与文件中章节标记数"
                f"（{len(marker_indexes)}）不一致，中止回写"
                "（目录行不可增删，编号列仅作对照）"
            )
            return None
        backup = self.path + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(self.path, backup)
            logger.info(f"已备份原文件: {backup}（已存在时不重复覆盖）")
        for (number, title), index in zip(entries, marker_indexes):
            if lines[index].strip() != title:
                logger.info(f"  [{number:03d}] {lines[index].strip()} -> {title}")
            lines[index] = title
        with open(self.path, "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")
        logger.info(f"整本 txt 回写完成: 替换 {len(entries)} 个标记行 -> {self.path}")
        return {"mode": "file", "replaced": len(entries), "backup": backup}
