"""单文件段落差异与目录级校正版对比。"""

import logging
import os

from pixiv_novel_toolkit.chapters.overlay import build_prefix_index


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


def diff_paragraphs(file1, file2):
    """忽略空行比较两个 UTF-8 文本文件，返回结构化段落差异。"""
    with open(file1, "r", encoding="utf-8") as first, open(
        file2, "r", encoding="utf-8"
    ) as second:
        lines1 = [line.strip() for line in first.readlines() if line.strip()]
        lines2 = [line.strip() for line in second.readlines() if line.strip()]

    changed = []
    minimum_length = min(len(lines1), len(lines2))
    for index in range(minimum_length):
        if lines1[index] == lines2[index]:
            continue
        first_diff_index = None
        first_diff_char1 = None
        first_diff_char2 = None
        for char_index, (char1, char2) in enumerate(zip(lines1[index], lines2[index])):
            if char1 != char2:
                first_diff_index = char_index + 1
                first_diff_char1 = char1
                first_diff_char2 = char2
                break
        if first_diff_index is None:
            first_diff_index = min(len(lines1[index]), len(lines2[index])) + 1
            if len(lines1[index]) > len(lines2[index]):
                first_diff_char1 = lines1[index][len(lines2[index])]
                first_diff_char2 = "(无)"
            else:
                first_diff_char1 = "(无)"
                first_diff_char2 = lines2[index][len(lines1[index])]
        changed.append(
            {
                "line_no": index + 1,
                "first_diff_pos": first_diff_index,
                "char1": first_diff_char1,
                "char2": first_diff_char2,
                "text1": lines1[index],
                "text2": lines2[index],
            }
        )

    # 保留旧版行号口径，避免兼容入口的报告格式发生变化。
    only_in_1 = [
        (index + 1 + minimum_length, lines1[index])
        for index in range(minimum_length, len(lines1))
    ]
    only_in_2 = [
        (index + 1 + minimum_length, lines2[index])
        for index in range(minimum_length, len(lines2))
    ]
    return {
        "changed_paragraphs": changed,
        "only_in_1": only_in_1,
        "only_in_2": only_in_2,
        "total_diff": len(changed) + len(only_in_1) + len(only_in_2),
    }


class TxtFileComparator:
    """比较两个接近的文本文件，并输出首个不同字符及段落内容。"""

    def __init__(self, file1, file2, output_file="text_differences.txt"):
        self.file1 = file1
        self.file2 = file2
        self.output_file = output_file

    _diff_paragraphs = staticmethod(diff_paragraphs)

    def compare_file(self):
        result = self._diff_paragraphs(self.file1, self.file2)
        output_title = "文件1和文件2之间的差异：\n"
        print(output_title)
        with open(self.output_file, "w", encoding="utf-8") as file:
            file.write(output_title + "\n")
            number = 0
            for difference in result["changed_paragraphs"]:
                number += 1
                file.write(f"第 {number} 个错误：\n")
                file.write(
                    f"文件1第 {difference['line_no']} 行：\n{difference['text1']}\n"
                )
                file.write(
                    f"文件2第 {difference['line_no']} 行：\n{difference['text2']}\n"
                )
                file.write(
                    f"第一个不同的字符在位置 {difference['first_diff_pos']}，"
                    f"'{difference['char1']}' vs '{difference['char2']}'，"
                    "这段共有 1 个错误\n\n"
                )
                print(f"第 {number} 个错误：")
                print(
                    f"文件1第 {difference['line_no']} 行：'{difference['text1']}'"
                )
                print(
                    f"文件2第 {difference['line_no']} 行：'{difference['text2']}'"
                )
                print(
                    f"第一个不同的字符在位置 {difference['first_diff_pos']}，"
                    f"'{difference['char1']}' vs '{difference['char2']}'，"
                    "这段共有 1 个错误"
                )

            file.write(f"总共 {result['total_diff']} 处错误")
            print(f"总共 {result['total_diff']} 处错误")
            for line_number, text in result["only_in_1"]:
                file.write(f"文件1额外的行 {line_number}：'{text}'\n")
                print(f"文件1额外的行 {line_number}：'{text}'")
            for line_number, text in result["only_in_2"]:
                file.write(f"文件2额外的行 {line_number}：'{text}'\n")
                print(f"文件2额外的行 {line_number}：'{text}'")


class DirectoryDiffer:
    """按数字前缀配对标准化与校正目录，生成差异摘要和可选报告。"""

    def __init__(self, baseline_dir, corrected_dir, report_file=None, console_preview=3):
        self.baseline_dir = baseline_dir
        self.corrected_dir = corrected_dir
        self.report_file = report_file
        self.console_preview = console_preview

    def diff(self):
        base_prefix, base_no = build_prefix_index(
            self.baseline_dir, warn=logger.warning
        )
        corrected_prefix, corrected_no = build_prefix_index(
            self.corrected_dir, warn=logger.warning
        )
        common_prefixes = sorted(
            set(base_prefix) & set(corrected_prefix), key=lambda value: int(value)
        )
        only_base_prefix = sorted(
            set(base_prefix) - set(corrected_prefix), key=lambda value: int(value)
        )
        only_corrected_prefix = sorted(
            set(corrected_prefix) - set(base_prefix), key=lambda value: int(value)
        )

        base_no_set, corrected_no_set = set(base_no), set(corrected_no)
        common_no = sorted(base_no_set & corrected_no_set)
        only_base_no = sorted(base_no_set - corrected_no_set)
        only_corrected_no = sorted(corrected_no_set - base_no_set)

        logger.info(f"目录对比开始: {self.baseline_dir} vs {self.corrected_dir}")
        logger.info(
            f"按前缀配对: 共同 {len(common_prefixes)} 个；"
            f"仅标准化 {len(only_base_prefix)} 个；"
            f"仅校正 {len(only_corrected_prefix)} 个"
        )
        if common_no or only_base_no or only_corrected_no:
            logger.info(
                f"无数字前缀文件（按完整名匹配）: 共同 {len(common_no)}；"
                f"仅标准化 {len(only_base_no)}；仅校正 {len(only_corrected_no)}"
            )

        report_lines = []

        def report(line):
            logger.info(line)
            report_lines.append(line)

        modified_files = []
        unchanged_files = []
        renamed_files = []
        for prefix in common_prefixes:
            baseline_name = base_prefix[prefix]
            corrected_name = corrected_prefix[prefix]
            result = diff_paragraphs(
                os.path.join(self.baseline_dir, baseline_name),
                os.path.join(self.corrected_dir, corrected_name),
            )
            if baseline_name != corrected_name and result["total_diff"] == 0:
                renamed_files.append((prefix, baseline_name, corrected_name))
                unchanged_files.append(prefix)
            elif result["total_diff"] == 0:
                unchanged_files.append(prefix)
            else:
                modified_files.append(
                    (prefix, baseline_name, corrected_name, result)
                )

        modified_no = []
        unchanged_no = []
        for filename in common_no:
            result = diff_paragraphs(
                os.path.join(self.baseline_dir, filename),
                os.path.join(self.corrected_dir, filename),
            )
            if result["total_diff"] == 0:
                unchanged_no.append(filename)
            else:
                modified_no.append((filename, result))

        if modified_files:
            report(f"\n{len(modified_files)} 个配对文件发现内容差异：")
            for prefix, baseline_name, corrected_name, result in modified_files:
                title = f"[{prefix}] {baseline_name}"
                if baseline_name != corrected_name:
                    title += f"  vs  {corrected_name}"
                report(f"\n===== {title} — {result['total_diff']} 处差异 =====")
                changed = result["changed_paragraphs"]
                for index, difference in enumerate(changed):
                    report(
                        f"  第 {difference['line_no']} 段 "
                        f"第 {difference['first_diff_pos']} 字: "
                        f"'{difference['char1']}' vs '{difference['char2']}'"
                    )
                    report(f"    标准化: {difference['text1']}")
                    report(f"    校正版: {difference['text2']}")
                    if (
                        index + 1 == self.console_preview
                        and len(changed) > self.console_preview
                    ):
                        remain = len(changed) - self.console_preview
                        report(f"    ... 剩余 {remain} 处段落差异见日志文件")
                        break
                if result["only_in_1"]:
                    report(f"  校正版删除了 {len(result['only_in_1'])} 段:")
                    for line_number, text in result["only_in_1"][: self.console_preview]:
                        report(f"    第 {line_number} 段 (标准化独有): {text}")
                    if len(result["only_in_1"]) > self.console_preview:
                        remain = len(result["only_in_1"]) - self.console_preview
                        report(f"    ... 剩余 {remain} 段删除见日志文件")
                if result["only_in_2"]:
                    report(f"  校正版新增了 {len(result['only_in_2'])} 段:")
                    for line_number, text in result["only_in_2"][: self.console_preview]:
                        report(f"    第 {line_number} 段 (校正独有): {text}")
                    if len(result["only_in_2"]) > self.console_preview:
                        remain = len(result["only_in_2"]) - self.console_preview
                        report(f"    ... 剩余 {remain} 段新增见日志文件")

        if renamed_files:
            report(f"\n{len(renamed_files)} 个文件仅改了文件名（内容一致）:")
            for prefix, baseline_name, corrected_name in renamed_files:
                report(f"  [{prefix}] {baseline_name}  ->  {corrected_name}")

        if modified_no:
            report(f"\n{len(modified_no)} 个无前缀文件发现差异:")
            for filename, result in modified_no:
                report(f"\n===== {filename} — {result['total_diff']} 处差异 =====")
                for difference in result["changed_paragraphs"][: self.console_preview]:
                    report(
                        f"  第 {difference['line_no']} 段 "
                        f"第 {difference['first_diff_pos']} 字: "
                        f"'{difference['char1']}' vs '{difference['char2']}'"
                    )
                    report(f"    标准化: {difference['text1']}")
                    report(f"    校正版: {difference['text2']}")

        if not modified_files and not modified_no and not renamed_files:
            report("\n所有配对文件内容完全一致，无差异。")

        if only_base_prefix or only_base_no:
            total = len(only_base_prefix) + len(only_base_no)
            report(f"\n仅标准化目录存在 {total} 个文件（未校正）:")
            for prefix in only_base_prefix:
                report(f"  [{prefix}] {base_prefix[prefix]}")
            for filename in only_base_no:
                report(f"  {filename}")

        if only_corrected_prefix or only_corrected_no:
            total = len(only_corrected_prefix) + len(only_corrected_no)
            report(f"\n仅校正目录存在 {total} 个文件（新增）:")
            for prefix in only_corrected_prefix:
                report(f"  [{prefix}] {corrected_prefix[prefix]}")
            for filename in only_corrected_no:
                report(f"  {filename}")

        total_changed = len(modified_files) + len(modified_no)
        total_unchanged = len(unchanged_files) + len(unchanged_no)
        total_only_base = len(only_base_prefix) + len(only_base_no)
        total_only_corrected = len(only_corrected_prefix) + len(only_corrected_no)
        report(
            f"\n对比完成: {total_changed} 篇改动，"
            f"{total_unchanged} 篇未改（其中 {len(renamed_files)} 篇仅改名），"
            f"{total_only_base} 篇未校正，{total_only_corrected} 篇新增"
        )

        if self.report_file:
            with open(self.report_file, "w", encoding="utf-8") as file:
                file.write("\n".join(report_lines) + "\n")
            logger.info(f"差异报告已保存: {self.report_file}")

        return {
            "common": len(common_prefixes) + len(common_no),
            "modified": total_changed,
            "unchanged": total_unchanged,
            "renamed_only": len(renamed_files),
            "only_baseline": total_only_base,
            "only_corrected": total_only_corrected,
        }
