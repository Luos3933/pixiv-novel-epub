"""标准化目录与人工校正目录的覆盖合成。"""

import logging
import os
import shutil

from pixiv_novel_toolkit.chapters.overlay import build_prefix_index


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


class DirectoryAssembler:
    """按数字前缀配对，校正版优先合成最终章节目录。"""

    def __init__(self, baseline_dir, corrected_dir, output_dir):
        self.baseline_dir = baseline_dir
        self.corrected_dir = corrected_dir
        self.output_dir = output_dir

    @staticmethod
    def _copy(src_path, dst_path):
        shutil.copyfile(src_path, dst_path)

    def assemble(self):
        base_prefix, base_no = build_prefix_index(
            self.baseline_dir, warn=logger.warning
        )
        corrected_prefix, corrected_no = build_prefix_index(
            self.corrected_dir, warn=logger.warning
        )

        all_prefixes = sorted(
            set(base_prefix) | set(corrected_prefix), key=lambda value: int(value)
        )
        all_no_prefix = sorted(set(base_no) | set(corrected_no))

        if not all_prefixes and not all_no_prefix:
            logger.warning("两个源目录都没有 txt 文件，无内容可合成。")
            return {"baseline_count": 0, "corrected_count": 0, "total": 0}

        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(
            f"合成开始: {self.baseline_dir} + {self.corrected_dir} -> {self.output_dir}"
        )
        logger.info(
            f"待合成: 前缀配对 {len(all_prefixes)} 个 + "
            f"无前缀 {len(all_no_prefix)} 个"
        )

        from_corrected = 0
        from_baseline = 0
        renamed_count = 0
        mapping_lines = []

        for prefix in all_prefixes:
            in_corrected = prefix in corrected_prefix
            in_baseline = prefix in base_prefix
            if in_corrected:
                source_name = corrected_prefix[prefix]
                source = os.path.join(self.corrected_dir, source_name)
                source_label = "校正"
                from_corrected += 1
            elif in_baseline:
                source_name = base_prefix[prefix]
                source = os.path.join(self.baseline_dir, source_name)
                source_label = "标准化"
                from_baseline += 1
            else:  # pragma: no cover - 集合来源保证不可达
                continue

            destination = os.path.join(self.output_dir, source_name)
            self._copy(source, destination)
            rename_note = ""
            if (
                in_corrected
                and in_baseline
                and base_prefix[prefix] != corrected_prefix[prefix]
            ):
                renamed_count += 1
                rename_note = (
                    f"  (改名: {base_prefix[prefix]} -> {corrected_prefix[prefix]})"
                )

            line = f"  [{prefix}] {source_name}  <- {source_label}{rename_note}"
            logger.info(line)
            mapping_lines.append(line)

        for filename in all_no_prefix:
            if filename in corrected_no:
                source = os.path.join(self.corrected_dir, filename)
                source_label = "校正"
                from_corrected += 1
            elif filename in base_no:
                source = os.path.join(self.baseline_dir, filename)
                source_label = "标准化"
                from_baseline += 1
            else:  # pragma: no cover - 集合来源保证不可达
                continue
            destination = os.path.join(self.output_dir, filename)
            self._copy(source, destination)
            line = f"  {filename}  <- {source_label}"
            logger.info(line)
            mapping_lines.append(line)

        mapping_file = os.path.join(self.output_dir, "_source_map.txt")
        with open(mapping_file, "w", encoding="utf-8") as file:
            file.write("\n".join(mapping_lines) + "\n")

        total = len(all_prefixes) + len(all_no_prefix)
        logger.info(
            f"合成完成: 共 {total} 个文件 -> 校正版 {from_corrected} + "
            f"标准化 {from_baseline}"
            + (f"（含 {renamed_count} 个改名）" if renamed_count else "")
        )
        logger.info(f"来源映射: {mapping_file}")
        return {
            "total": total,
            "from_corrected": from_corrected,
            "from_baseline": from_baseline,
            "renamed": renamed_count,
        }
