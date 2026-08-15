import argparse
import html
import io
import json
import logging
import os
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone

from log_setup import configure_logging


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


def configure_postprocess_logging(base_dir):
    """配置后处理日志：固定文件 logs/postprocess.log 追加，超 1MB 自动归档到 logs/archive/。"""
    return configure_logging(base_dir, "pixiv_novel_toolkit.postprocess", "postprocess.log")


def interleave_blank_lines(lines):
    """
    读取原始行列表，去除空白行后，在每个非空段落后插入一个空行。

    返回处理后的新行列表（调用方负责 join 与文件写入）。
    """
    new_lines = []
    for line in lines:
        stripped_line = line.strip()
        if stripped_line:
            new_lines.append(stripped_line)
            new_lines.append('')  # 添加一个空行
    return new_lines


def _file_prefix(filename):
    r"""
    返回文件名开头的数字前缀（如 '043'），无数字前缀返回 None。

    与 format / merge 内的 sort_key 一致：匹配规则是 ^(\d+)。
    """
    match = re.match(r'^(\d+)', filename)
    return match.group(1) if match else None


def _list_txt_in(directory):
    """列出目录下所有 .txt 文件名（不保证排序，调用方自行决定）。"""
    if not os.path.isdir(directory):
        return []
    return [f for f in os.listdir(directory) if f.lower().endswith('.txt')]


def _build_prefix_index(directory):
    """
    把目录下所有 txt 按数字前缀索引起来（用作 diff/note/assemble 的配对键）。

    返回 (prefix_map, no_prefix):
      prefix_map: {'043': '043 xxx.txt', ...}  数字前缀 -> 完整文件名
      no_prefix:  ['附录.txt', ...]            无数字前缀的文件名（按完整名匹配）
    前缀在 format 输出里是唯一的；若出现重复会保留最后读到的一个并打 warning。
    """
    prefix_map = {}
    no_prefix = []
    for fname in _list_txt_in(directory):
        p = _file_prefix(fname)
        if p is None:
            no_prefix.append(fname)
            continue
        if p in prefix_map:
            logger.warning(
                f"前缀冲突: 目录 {directory} 下 {prefix_map[p]!r} 与 {fname!r} 共用前缀 {p!r}，"
                f"配对时将取后者"
            )
        prefix_map[p] = fname
    return prefix_map, no_prefix


def _int_to_chinese(num):
    """阿拉伯数字转中文数字（如 43 -> 四十三），10-19 写作 十X 而非 一十X。"""
    zh_num = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
    zh_unit = ['', '十', '百', '千', '万']
    if num == 0:
        return zh_num[0]
    res = ''
    num_str = str(num)
    length = len(num_str)
    for i, char in enumerate(num_str):
        n = int(char)
        if n != 0:
            res += zh_num[n] + zh_unit[length - i - 1]
        else:
            if not res.endswith('零'):
                res += '零'
    res = res.rstrip('零')
    if res.startswith('一十'):
        res = res[1:]
    return res


def _chinese_to_int(cn):
    """中文数字转阿拉伯数字（支持十/百/千/万，如 十九->19、一百零三->103）；失败返回 None。"""
    digits = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
              '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    units = {'十': 10, '百': 100, '千': 1000, '万': 10000}
    total = 0
    section = 0
    number = 0
    for ch in cn:
        if ch in digits:
            number = digits[ch]
        elif ch in units:
            unit = units[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
            if unit == 10000:
                total = (total + section) * unit
                section = 0
        else:
            return None
    total += section + number
    return total if total > 0 else None


def _sanitize_filename_part(text):
    """清理章节标题中不能出现在 Windows 文件名里的字符。"""
    return re.sub(r'[\\/:*?"<>|]', ' ', text).strip()


def _load_volumes_file(volumes_file):
    """
    读取卷/篇配置文件（merge --volumes / epub --volumes 共用），JSON 列表格式：
        [
            {"name": "第一卷 示例卷名", "start": 1, "end": 17},
            {"name": "第二卷 示例卷名", "start": 18, "end": 35}
        ]
    - name: 卷/篇标题
    - start / end: 章节文件数字前缀范围（含端点）；只写 start 时视为单章
    返回按 start 排序的 [{name, start, end}] 列表；未配置或配置为空返回 []；
    文件不存在 / 解析失败返回 None（调用方决定中止或跳过）。
    """
    if not volumes_file:
        return []
    if not os.path.isfile(volumes_file):
        logger.error(f"卷/篇配置文件不存在: {volumes_file}")
        return None
    try:
        with open(volumes_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"卷/篇配置文件解析失败: {e}")
        return None
    if not isinstance(data, list):
        logger.error('卷/篇配置文件应为 JSON 列表，如 [{"name": "第一卷", "start": 1, "end": 17}]')
        return None

    volumes = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not item.get("name"):
            logger.warning(f"第 {i} 条卷配置无效（缺少 name），已跳过: {item}")
            continue
        try:
            start = int(item.get("start"))
            end = int(item.get("end", start))
        except (TypeError, ValueError):
            logger.warning(f"第 {i} 条卷配置 {item.get('name')!r} 的 start/end 不是数字，已跳过")
            continue
        if start < 0 or end < start:
            logger.warning(f"第 {i} 条卷配置 {item.get('name')!r} 范围无效"
                           f"（start={start}, end={end}），已跳过")
            continue
        volumes.append({"name": item["name"], "start": start, "end": end})

    volumes.sort(key=lambda v: v["start"])
    if volumes:
        logger.info(f"已读取卷/篇配置: {len(volumes)} 卷")
    return volumes


def convert_punctuation(text):
    """
    将文本中的英文标点转换为中文标点：

    - !  → ！
    - ?  → ？
    - "  → 按全文"奇前偶后"配对依次替换为 " 与 "
      （第 1 个 " 替换为前引号，第 2 个替换为后引号，循环切换）

    单引号 ' 不做处理，避免与英文撇号（如 don't）产生冲突。

    返回 (new_text, stats)：
      new_text  转换后的字符串
      stats     dict，包含：
                  original_quote       原文 " 总数
                  front_quote / back_quote   转换后 " / " 个数
                  original_exclamation 原文 ! 总数
                  original_question    原文 ? 总数
                  unpaired             1 表示原文 " 为奇数个、最后一对未闭合
    """
    chars = []
    front_quote_count = 0
    back_quote_count = 0
    quote_open = True  # 下一个 " 取前引号 “
    for ch in text:
        if ch == '"':
            if quote_open:
                chars.append('“')
                front_quote_count += 1
            else:
                chars.append('”')
                back_quote_count += 1
            quote_open = not quote_open
        elif ch == '!':
            chars.append('！')
        elif ch == '?':
            chars.append('？')
        else:
            chars.append(ch)
    original_quote = text.count('"')
    stats = {
        "original_quote": original_quote,
        "front_quote": front_quote_count,
        "back_quote": back_quote_count,
        "original_exclamation": text.count('!'),
        "original_question": text.count('?'),
        "unpaired": original_quote % 2,
    }
    return ''.join(chars), stats


class TxtFileMerger:
    """
    将含有数字顺序排列的 txt 文件合并成一个文件，且段落间存在一个换行符

    支持多输入目录：传入 list 时按"校正优先于标准化"的语义合并。
    例如 merge([standardized/, corrected/], out.txt)：
      - 校正目录里有的章节取校正版
      - 校正目录没有的章节取标准化版
      - 两侧都没的不合并
    配合 --info 可以让合并开头的 000 书籍信息.txt 反映实际字数。
    """

    def __init__(self, input_folders, output_file, update_info=False, volumes_file=None,
                 indent=False):
        """
        初始化TxtFileMerger类。

        参数:
        - input_folders: 存放待合并 txt 的目录路径，可传单个字符串或列表；
                         列表时后面的目录优先级高（同名章节取后者的版本）。
        - output_file: 合并后输出的文件路径
        - update_info: 合并前是否根据实际参与合并的章节字数
                       刷新 000 书籍信息.txt 中的"字数"字段
        - volumes_file: 可选，卷/篇配置文件路径（JSON，见 _load_volumes_file）；
                        传入时每卷的第一章前插入卷名行
        - indent: True 时正文段落加两个全角空格首行缩进（000 书籍信息、
                  章节标题行、卷名行不缩进）；默认 False 保持原样
        """
        # 统一规整为列表
        if isinstance(input_folders, str):
            input_folders = [input_folders]
        self.input_folders = input_folders
        self.output_file = output_file
        self.update_info = update_info
        self.volumes_file = volumes_file
        self.indent = indent

    def _collect_files(self):
        """
        从多个输入目录按数字前缀（或无前缀的完整文件名）收集并合并章节。

        后面的目录优先级高：同名/同前缀的章节会覆盖前者。
        返回 OrderedDict: { sort_key:(prefix_or_name, filename) -> file_path }
        """
        from collections import OrderedDict
        collected = OrderedDict()

        # 按优先级从低到高遍历（最后出现的覆盖前面）
        for d in self.input_folders:
            if not os.path.isdir(d):
                logger.warning(f"输入目录不存在，已跳过: {d}")
                continue
            for fname in os.listdir(d):
                if not fname.lower().endswith('.txt'):
                    continue
                prefix = _file_prefix(fname)
                # 用前缀（或完整名）作为合并键；000 书籍信息统一归到 "000" 键
                key = prefix if prefix is not None else fname
                collected[key] = (fname, os.path.join(d, fname))

        return collected

    def merge_txt_files(self):
        """
        将含有数字顺序排列的 txt 文件合并成一个文件，且段落间存在一个换行符。
        若 update_info=True，合并前先刷新 000 书籍信息.txt 的字数。
        """
        collected = self._collect_files()
        if not collected:
            logger.error("所有输入目录中都没有 txt 文件，无法合并。")
            return

        # 卷配置：每卷范围 -> 卷名（用于在卷首章前插入卷名行，并写入 000 卷/篇数）
        volumes = _load_volumes_file(self.volumes_file) if self.volumes_file else []
        if volumes is None:
            logger.error("卷/篇配置读取失败，中止合并（可去掉 --volumes 参数重试）。")
            return

        # 合并前刷新书籍信息字数：把所有输入目录都传给 BookInfoGenerator，
        # 让它按优先级（最后目录最高）统计实际合并字数并把更新版写到优先级最高的目录。
        if self.update_info:
            info_path = BookInfoGenerator(self.input_folders).update_word_count_for_merge(
                volumes=volumes)
            if info_path:
                logger.info("已基于实际章节字数刷新 000 书籍信息.txt，将作为合并输出开头。")
                # 重新收集一次，确保刷新后的 000 被纳入
                collected = self._collect_files()
            else:
                logger.warning("未能更新 000 书籍信息字数；将按现状合并。")

        # 排序：数字前缀按整数升序；无前缀文件排在最后
        def sort_key(item_key):
            if isinstance(item_key, str) and item_key.isdigit():
                return (0, int(item_key))
            return (1, item_key)

        sorted_keys = sorted(collected.keys(), key=sort_key)

        # 卷配置：每卷范围 -> 卷名（用于在卷首章前插入卷名行）
        vol_first = {}
        for v in volumes:
            for k in sorted_keys:
                if k.isdigit() and v["start"] <= int(k) <= v["end"]:
                    vol_first[k] = v["name"]
                    break

        logger.info(f"正在合并 {len(sorted_keys)} 个文件（来自 {len(self.input_folders)} 个目录）：")
        with open(self.output_file, 'w', encoding='utf-8') as outfile:
            for key in sorted_keys:
                fname, file_path = collected[key]
                # 卷首章前插入卷名行（空行 + 卷名 + 空行）
                if key in vol_first:
                    logger.info(f"  [卷] {vol_first[key]}")
                    outfile.write(f"\n{vol_first[key]}\n\n")
                logger.info(f"  [{key}] {fname}  <-  {os.path.basename(os.path.dirname(file_path))}/")
                with open(file_path, 'r', encoding='utf-8') as infile:
                    lines = infile.readlines()
                    stripped_lines = [line.strip() for line in lines if line.strip()]
                    # 首行缩进（--indent）：正文段落加两个全角空格；
                    # 000 书籍信息整段不缩进；章节标题（每个文件首行）不缩进
                    if self.indent and key != '000':
                        indented = [stripped_lines[0]] if stripped_lines else []
                        for line in stripped_lines[1:]:
                            indented.append('\u3000\u3000' + line)
                        stripped_lines = indented
                    if stripped_lines:
                        outfile.write('\n\n'.join(stripped_lines))
                        outfile.write('\n\n')

        logger.info(f"合并完成，输出文件为: {self.output_file}")

    def add_blank_lines(self, input_file, output_file):
        """
        在指定文件的每一行后添加一个空行，并将结果写入另一个文件。
        """
        with open(input_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        with open(output_file, 'w', encoding='utf-8') as file:
            file.write('\n'.join(interleave_blank_lines(lines)))


class BookInfoGenerator:
    """
    生成 "000 书籍信息.txt"：从模板套用 pixiv info.txt 自动填充，或输出空白占位模板。

    模板格式（与 format 命令一致，段落间空行）：
        书籍信息

        {书名}

        作者：{作者}

        连载状态：{N}章+{M}番外（{更新日期}）

        字数：{万字, 1 位小数}万字

        简介：

        {简介}

    数据来源优先级：
      1) 系列目录下 series_<ID>_info.txt（pixiv 下载产物）
      2) series_<ID>_metadata.json（pixiv 备选）
      3) 都没有 -> 空白占位模板，由用户手动填写
    """

    # 模板：使用占位符，下面用 .format 来填充
    # 段落之间留一个空行，沿用 interleave_blank_lines 的格式风格
    TEMPLATE = """书籍信息

{title}

作者：{author}

连载平台：{platform}

连载状态：{status}

字数：{word_count}

简介：

{description}"""

    # 空白占位模板（无 pixiv 源时使用）
    BLANK_TEMPLATE = """书籍信息

未填

作者：未填

连载于：未填

连载状态：未填

字数：未填

简介：

未填"""

    def __init__(self, source_dir, template_file=None):
        """
        source_dir: 章节所在目录（标准化输出目录或 chapters 目录）；
                    会向上查找同级是否有 series_<ID>_info.txt。
                    也支持传入目录列表（多目录合并时用），统计与查找会作用于全部目录。
        template_file: 可选自定义模板路径，默认使用内置 TEMPLATE
        """
        # 兼容字符串入参，统一规整为列表
        if isinstance(source_dir, str):
            source_dirs = [source_dir]
        else:
            source_dirs = list(source_dir)
        self.source_dirs = source_dirs
        self.source_dir = source_dirs[0]  # 保留 single 字段供 _find_pixiv_info 向上查找使用
        self.template_file = template_file

    def _find_pixiv_info(self):
        """
        在 source_dir 及其父目录中查找 series_<ID>_info.txt / metadata.json。
        返回解析后的字段 dict，找不到返回 None。
        """
        # 候选目录：source_dir 本身、其父目录（chapters -> series_xxx -> series）
        candidates = [self.source_dir]
        parent = os.path.dirname(self.source_dir)
        if parent:
            candidates.append(parent)
            grand = os.path.dirname(parent)
            if grand:
                candidates.append(grand)

        for d in candidates:
            if not os.path.isdir(d):
                continue
            # 找 series_*_info.txt
            for fname in os.listdir(d):
                if fname.endswith('_info.txt') and fname.startswith('series_'):
                    info_path = os.path.join(d, fname)
                    return self._parse_info_txt(info_path)
                # 也支持直接命名为 _info.txt
                if fname == '_info.txt':
                    info_path = os.path.join(d, fname)
                    return self._parse_info_txt(info_path)
            # 找 metadata.json
            for fname in os.listdir(d):
                if fname.endswith('_metadata.json') and fname.startswith('series_'):
                    meta_path = os.path.join(d, fname)
                    return self._parse_metadata(meta_path, d)

        return None

    def _parse_info_txt(self, info_path):
        """解析 series_<ID>_info.txt 的键值对格式。"""
        info = {
            "title": "未填", "author": "未填", "platform": "Pixiv",
            "update_time": "", "word_count": 0, "chapter_count": 0,
            "tags": [], "description": "",
        }
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError:
            return None

        # 简介"标签:"以后的所有内容都视为简介
        in_description = False
        desc_lines = []
        for line in content.splitlines():
            if in_description:
                if line.strip():
                    desc_lines.append(line.strip())
                continue
            if ':' in line or '：' in line:
                # 兼容中英文冒号
                key, _, value = line.partition(':' if ':' in line else '：')
                key = key.strip()
                value = value.strip()
                if key == '系列名称' or key == '系列名称':
                    info['title'] = value
                elif key == '作者':
                    info['author'] = value
                elif key == '更新时间':
                    info['update_time'] = value
                elif key == '总字数':
                    try:
                        info['word_count'] = int(''.join(c for c in value if c.isdigit()))
                    except ValueError:
                        info['word_count'] = 0
                elif key == '章节数':
                    try:
                        info['chapter_count'] = int(''.join(c for c in value if c.isdigit()))
                    except ValueError:
                        info['chapter_count'] = 0
                elif key == '标签':
                    info['tags'] = [t.strip() for t in value.replace('、', ',').split(',') if t.strip()]
                elif key == '简介':
                    in_description = True
                    if value:
                        desc_lines.append(value)

        info['description'] = '\n\n'.join(desc_lines) if desc_lines else "未填"
        return info

    def _parse_metadata(self, meta_path, data_dir):
        """从 metadata.json 提取字数与章节列表（推断番外数）。"""
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        total_word = sum(v.get('word_count', 0) for v in records.values() if isinstance(v, dict))
        extra_count = sum(1 for v in records.values()
                          if isinstance(v, dict) and '番外' in v.get('title', ''))
        chapter_count = len(records)
        return {
            "title": "未填",
            "author": "未填",
            "platform": "Pixiv",
            "update_time": "",
            "word_count": total_word,
            "chapter_count": chapter_count,
            "extra_count": extra_count,
            "tags": [],
            "description": "未填",
        }

    def _scan_chapter_stats(self, output_dir):
        """
        从输出目录已有的标准化 txt 文件名统计正文/番外数（与 format_all_files 内一致）。
        扫描文件名含"番外"关键字的算 Apiary，其余算正文。
        """
        if not os.path.isdir(output_dir):
            return 0, 0
        main_count = 0
        extra_count = 0
        for fname in os.listdir(output_dir):
            if not fname.lower().endswith('.txt'):
                continue
            # 跳过我们自己生成的 000
            if fname.startswith('000 '):
                continue
            if '番外' in fname:
                extra_count += 1
            else:
                main_count += 1
        return main_count, extra_count

    @staticmethod
    def _format_wan(word_count):
        """把字数整数转为"x.x万字"格式（1 位小数）。"""
        try:
            value = float(word_count) / 10000.0
        except (TypeError, ValueError):
            return "未填"
        return f"{value:.1f}万字"

    @staticmethod
    def _extract_date(update_time):
        """从 "2026-08-05 20:16:19" 这类字符串取 "2026年8月5日" 这种格式。"""
        if not update_time:
            return "未知日期"
        # 提取 YYYY-MM-DD 前缀
        match = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', update_time)
        if not match:
            return update_time[:10] if update_time else "未知日期"
        y, m, d = match.groups()
        return f"{int(y)}年{int(m)}月{int(d)}日"

    def generate(self, output_dir):
        """
        在 output_dir 顶部生成 "000 书籍信息.txt"。
        返回生成路径；如有 pixiv 源则用源数据填充，否则用空白占位模板。
        """
        info = self._find_pixiv_info()

        if info is None:
            content = self.BLANK_TEMPLATE
            logger.info("未能定位 pixiv 信息源，生成空白占位书籍信息模板（请手动填写）")
        else:
            # 优先用扫目录得到的具体正文/番外数（更准确，metadata 可能没有 extra_count）
            main_count, extra_count = self._scan_chapter_stats(self.source_dir)
            if main_count + extra_count == 0:
                main_count = info.get("chapter_count", 0)
                extra_count = info.get("extra_count", 0)

            # 拼接 "73章+1番外（2026年8月5日）"
            status_parts = []
            if main_count:
                status_parts.append(f"{main_count}章")
            if extra_count:
                status_parts.append(f"{extra_count}番外")
            status_base = "+".join(status_parts) if status_parts else "未知"
            update_date = self._extract_date(info.get("update_time", ""))
            status = f"{status_base}（{update_date}）" if update_date != "未知日期" else status_base

            word_count_text = self._format_wan(info.get("word_count", 0))

            content = self.TEMPLATE.format(
                title=info.get("title", "未填") or "未填",
                author=info.get("author", "未填") or "未填",
                platform=info.get("platform", "Pixiv"),
                status=status,
                word_count=word_count_text,
                description=info.get("description", "未填") or "未填",
            )

        out_path = os.path.join(output_dir, "000 书籍信息.txt")
        with open(out_path, 'w', encoding='utf-8') as f:
            # 末尾保留一个换行，便于 cat / 阅读器显示
            f.write(content + '\n')
        logger.info(f"已生成: {out_path}")
        return out_path

    @staticmethod
    def _count_chars_in_dir(directory):
        """
        统计 directory 下所有非 000 的 txt 文件总字数。

        字数定义：过滤空白行后的有效字符总数（含中文标点）。
        与 metadata 里的 textCount 统计口径接近，修订后的真实内容会反映到这个数值。
        """
        total = 0
        if not os.path.isdir(directory):
            return total
        for fname in os.listdir(directory):
            if not fname.lower().endswith('.txt'):
                continue
            if fname.startswith('000 '):
                continue
            try:
                with open(os.path.join(directory, fname), 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped:
                            total += len(stripped)
            except OSError as e:
                logger.warning(f"  统计字数失败 {fname}: {e}")
        return total

    def _collect_chapters_for_merge(self):
        """
        多目录合并场景下的章节收集（去重配对）：
          - 按数字前缀（或无前缀完整名）配对，后面目录优先级高（校正版覆盖标准化版）
          - 000 书籍信息文件不计入
        返回 [(key, file_path), ...]（按前缀排序），供字数/章节数/番外数统计共用。
        """
        from collections import OrderedDict
        collected = OrderedDict()
        for d in self.source_dirs:
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if not fname.lower().endswith('.txt'):
                    continue
                if fname.startswith('000 '):
                    continue
                prefix = _file_prefix(fname)
                key = prefix if prefix is not None else fname
                collected[key] = os.path.join(d, fname)

        def sort_key(item_key):
            if isinstance(item_key, str) and item_key.isdigit():
                return (0, int(item_key))
            return (1, item_key)

        return [(k, collected[k]) for k in sorted(collected.keys(), key=sort_key)]

    def _count_chars_for_merge(self):
        """
        多目录合并场景下的字数统计：
          - 按数字前缀（或无前缀完整名）配对
          - 后面目录优先级高（校正版覆盖标准化版），实际参与合并的章节才计入字数
          - 000 书籍信息文件不计入字数
        返回实际合并章节的总字符数（过滤空白行后）。
        """
        total = 0
        for key, path in self._collect_chapters_for_merge():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped:
                            total += len(stripped)
            except OSError as e:
                logger.warning(f"  统计字数失败 {key}: {e}")
        return total

    def _count_chapters_for_merge(self):
        """
        多目录合并场景下的章节数统计（与 _count_chars_for_merge 同一配对口径）：
        返回 (main_count, extra_count)：正文章数、番外数（文件名含"番外"算番外）。
        """
        main_count = 0
        extra_count = 0
        for key, path in self._collect_chapters_for_merge():
            fname = os.path.basename(path)
            if '番外' in fname:
                extra_count += 1
            else:
                main_count += 1
        return main_count, extra_count

    @staticmethod
    def _find_existing_book_info(directory):
        """
        在 directory 本身或同级 standardized 目录里找现有的 000 书籍信息.txt。
        返回文件路径，找不到返回 None。
        """
        candidates = [directory]
        parent = os.path.dirname(directory)
        if parent:
            candidates.append(os.path.join(parent, 'standardized'))
            candidates.append(parent)
        for d in candidates:
            if not d or not os.path.isdir(d):
                continue
            path = os.path.join(d, '000 书籍信息.txt')
            if os.path.isfile(path):
                return path
        return None

    def _find_newest_book_info(self):
        """
        在所有源目录（及其同级 standardized / 父目录）中收集 000 书籍信息.txt，
        返回 mtime 最新的那个路径（重新 format 生成的 000 通常比旧的 corrected 版新，
        应作为刷新基底；用户手改过的 000 时间更新，也会优先保留其内容）。
        找不到返回 None。
        """
        candidates = []
        for d in self.source_dirs:
            p = self._find_existing_book_info(d)
            if p and p not in candidates:
                candidates.append(p)
        if not candidates:
            return None
        return max(candidates, key=lambda p: os.path.getmtime(p))

    def _find_book_info_direct(self):
        """
        只在输入目录本身收集 000 书籍信息.txt，返回 mtime 最新的那个。
        （epub 场景用：输入目录通常就是 standardized/corrected，000 就在里面；
        不搜父目录，避免误命中父目录下其他系列的 000。）
        找不到返回 None。
        """
        candidates = []
        for d in self.source_dirs:
            p = os.path.join(d, '000 书籍信息.txt')
            if os.path.isfile(p) and p not in candidates:
                candidates.append(p)
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    def update_word_count_for_merge(self, output_dir=None, search_parent=True, volumes=None):
        """
        生成前的辅助：根据实际参与合并/打包的章节重新统计章节数与总字数，
        更新 000 书籍信息.txt 的「连载状态」（N章+M番外）、「字数」两行，
        并在传入卷配置（volumes 参数）时补充「卷/篇数：N」行（连载状态行之后）；
        其余内容（书名/作者/简介/日期等）取自 mtime 最新的 000 基底。

        - 统计范围：self.source_dirs 里所有目录按前缀配对去重后实际参与合并的章节（不含 000）。
        - 基底选择：各源目录中 mtime 最新的 000（重新 format 生成的新字段优先，
          用户手改过的 000 时间更新同样优先保留）。search_parent=False 时只搜
          输入目录本身（epub 场景，避免误命中父目录里其他系列的 000）。
        - 输出位置：若指定 output_dir 则写到那里；否则写回优先级最高的源目录（最后一个，
          通常是 corrected/），保证后续合并/打包时优先取到刷新版。
        返回最终落地的 000 路径（找不到来源则返回 None）。
        """
        # 取 mtime 最新的 000 作为基底
        existing = self._find_newest_book_info() if search_parent else self._find_book_info_direct()
        if existing is None:
            logger.warning(
                "未找到现有 000 书籍信息.txt 作为模板来源（各源目录及其同级 standardized 目录均无）；"
                "跳过书籍信息刷新。"
            )
            return None

        with open(existing, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1) 刷新字数：按实际参与合并的章节总字符数
        actual_word_count = self._count_chars_for_merge()
        wan_text = self._format_wan(actual_word_count)
        new_content, replaced = re.subn(
            r'^字数[：:].*$',
            f'字数：{wan_text}',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if replaced == 0:
            logger.warning(
                f"未找到 '字数：...' 行，未能更新 {existing} 中的字数字段。"
            )
            return None

        # 2) 刷新连载状态：N章+M番外 按实际章节重新统计，保留原日期（YYYY年M月D日）
        main_count, extra_count = self._count_chapters_for_merge()
        status_parts = []
        if main_count:
            status_parts.append(f"{main_count}章")
        if extra_count:
            status_parts.append(f"{extra_count}番外")
        status_base = "+".join(status_parts) if status_parts else "未知"
        old_status_m = re.search(r'^连载状态[：:].*$', new_content, flags=re.MULTILINE)
        date_suffix = ""
        if old_status_m:
            date_m = re.search(r'（([^）]*)）', old_status_m.group(0))
            if date_m:
                date_suffix = f"（{date_m.group(1)}）"
        new_status = f"连载状态：{status_base}{date_suffix}"
        new_content, replaced2 = re.subn(
            r'^连载状态[：:].*$', new_status, new_content, count=1, flags=re.MULTILINE)
        if replaced2 == 0:
            logger.warning(
                f"未找到 '连载状态：...' 行，未能更新 {existing} 中的章节数字段。"
            )

        # 3) 卷/篇数：传入卷配置时在连载状态行后插入/更新 "卷/篇数：N" 行；
        #    未传入（不带 --volumes）时删除已有的卷/篇数行（用户取消分卷）
        new_content = re.sub(r'^卷/篇数[：:].*$\n?', '', new_content, flags=re.MULTILINE)
        if volumes:
            vol_line = f"卷/篇数：{len(volumes)}"
            # 在连载状态行后插入
            new_content, replaced3 = re.subn(
                r'(^连载状态[：:].*$\n?)',
                rf'\g<1>{vol_line}\n',
                new_content,
                count=1,
                flags=re.MULTILINE,
            )
            if replaced3:
                logger.info(f"已补充书籍信息卷/篇数: {len(volumes)}")

        # 更新版写到优先级最高的源目录（列表最后一个，通常是 corrected/）
        target = output_dir or self.source_dirs[-1]
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        out_path = os.path.join(target, '000 书籍信息.txt')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        logger.info(
            f"已刷新书籍信息: {out_path} "
            f"(章节 {main_count}章+{extra_count}番外，字数 {actual_word_count} → {wan_text})"
        )
        return out_path


class BatchTxtFileFormatter:
    """
    批量处理 txt 文件：
    1. 净化格式（添加段落空行）
    2. 智能重命名（独立计算正文章节，跳过番外）
    3. 在正文顶部自动注入章节标题
    """

    def __init__(self, input_folder, output_folder, punct=False):
        self.input_folder = input_folder
        self.output_folder = output_folder
        # 是否在写入前对正文做英文标点 → 中文标点的转换（引号自动配对）。
        self.punct = punct

    def _number_to_chinese(self, num):
        """将阿拉伯数字转换为中文数字 (如 43 -> 四十三)。委托到模块级 _int_to_chinese。"""
        return _int_to_chinese(num)

    def format_all_files(self):
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)

        # 获取所有 .txt 文件
        files = [f for f in os.listdir(self.input_folder) if f.endswith('.txt')]

        # 必须先按前面的数字编号排序，保证章节顺序不乱
        def sort_key(filename):
            match = re.search(r'^(\d+)', filename)
            return int(match.group(1)) if match else 0

        txt_files = sorted(files, key=sort_key)

        logger.info(f"批量格式化开始：{self.input_folder} -> {self.output_folder}")
        logger.info(f"共发现 {len(txt_files)} 个 txt 文件；punct={self.punct}")

        main_chapter_count = 1          # 真正的"正文"章节计数器
        stats_main = 0                  # 已处理正文章节数
        stats_extra = 0                 # 已处理番外数
        stats_skipped = 0               # 因命名规则不符或编号 0 跳过的文件数
        stats_unpaired = 0              # punct 模式下累计未配对引号文件数

        for idx, txt_file in enumerate(txt_files, start=1):
            # 解析原始文件名：匹配 "043 xxxx.txt"
            match = re.search(r'^(\d+)\s+(.*?)(?:\.txt)$', txt_file)
            if not match:
                logger.warning(f"[{idx:03d}] 跳过不符合命名规则的文件: {txt_file}")
                stats_skipped += 1
                continue

            prefix = match.group(1)     # 文件前面的编号，如 "043"
            raw_title = match.group(2)  # 原始标题
            kind = "正文"               # 正文 / 番外 / 信息

            # 旧机制已废除：编号为 0 的 "0 书籍信息.txt" 不再原样拷贝。
            # 书籍信息统一由 BookInfoGenerator 在末尾自动生成 "000 书籍信息.txt"。
            # 这里若仍见到 0 开头文件则提示并跳过，避免被当成章节注入中文章号。
            if int(prefix) == 0:
                logger.warning(
                    f"[{idx:03d}] 跳过编号为 0 的文件: {txt_file} "
                    f"(书籍信息已改为脚本末尾自动生成 000 书籍信息.txt)"
                )
                stats_skipped += 1
                continue

            # 清洗原标题自带的繁杂章节号（防重复，比如原名叫 "第43章 某某"，清洗成 "某某"）
            clean_title = re.sub(r'^第[一二三四五六七八九十百千万零\d]+章\s*', '', raw_title).strip()

            # 判断是不是番外
            if '番外' in clean_title:
                # 规范番外的命名，并且 **不增加** 正文计数器
                clean_title = clean_title.replace('番外：', '').replace('番外', '').strip()
                display_title = f"番外：{clean_title}" if clean_title else "番外"
                kind = "番外"
            else:
                # 正常的正文章节，转换中文数字并拼接
                zh_num = self._number_to_chinese(main_chapter_count)
                display_title = f"第{zh_num}章 {clean_title}"
                main_chapter_count += 1  # 只有正文才增加计数器
                stats_main += 1

            if kind == "番外":
                stats_extra += 1
            # 组装新的文件名
            new_filename = f"{prefix} {display_title}.txt"

            # ---------------- 读取与注入处理 ----------------
            input_path = os.path.join(self.input_folder, txt_file)
            output_path = os.path.join(self.output_folder, new_filename)

            with open(input_path, 'r', encoding='utf-8') as infile:
                lines = infile.readlines()

            new_lines = interleave_blank_lines(lines)

            # 可选：做英文标点 → 中文标点转换（引号按奇偶自动配对为 “ ”）
            punct_stats = None
            if self.punct:
                converted = []
                agg_front = agg_back = 0
                agg_excl = agg_ques = 0
                unpaired_total = 0
                for line in new_lines:
                    new_line, st = convert_punctuation(line)
                    converted.append(new_line)
                    agg_front += st["front_quote"]
                    agg_back += st["back_quote"]
                    agg_excl += st["original_exclamation"]
                    agg_ques += st["original_question"]
                    unpaired_total += st["unpaired"]
                new_lines = converted
                punct_stats = {
                    "front": agg_front, "back": agg_back,
                    "excl": agg_excl, "ques": agg_ques,
                    "unpaired": unpaired_total,
                }
                if unpaired_total:
                    logger.warning(
                        f"[{idx:03d}] {txt_file}: 奇数个英文双引号 "
                        f"({punct_stats['front']} “ + {punct_stats['back']} ”)，"
                        f"前/后引号可能未完整配对。"
                    )
                    stats_unpaired += 1

            # 写入新文件：把我们做好的中文标题/番外标题直接顶在第一行！
            with open(output_path, 'w', encoding='utf-8') as outfile:
                outfile.write(f"{display_title}\n\n")  # 注入顶部标题
                outfile.write('\n'.join(new_lines))

            # 单文件日志：原文件名 -> 新文件名 + 类型 + 可选标点统计
            log_msg = f"[{idx:03d}] {txt_file}  ->  {new_filename}  ({kind})"
            if punct_stats is not None:
                log_msg += (f" | 标点: “{punct_stats['front']} ”{punct_stats['back']} "
                            f"！{punct_stats['excl']} ？{punct_stats['ques']}")
            logger.info(log_msg)

        # ---- 末尾自动生成 000 书籍信息.txt ----
        BookInfoGenerator(self.input_folder).generate(self.output_folder)

        logger.info(
            f"批量格式化完成：正文 {stats_main} 章，番外 {stats_extra} 篇，"
            f"跳过 {stats_skipped} 个"
            + (f"，含标点未配对警告文件 {stats_unpaired} 个" if self.punct else "")
        )
        logger.info(f"输出目录: {self.output_folder}")


class TxtFileFormatter:
    """
    修改单一 txt 文件格式，使段落间存在一个换行符
    """

    def __init__(self, input_file, output_file):
        """
        初始化TxtFileFormatter类。

        参数:
        - input_file: 需要添加空行的原始文件路径
        - output_file: 添加空行后的输出文件路径
        """
        self.input_file = input_file
        self.output_file = output_file

    def add_blank_lines(self):
        """
        在指定文件的每一行后添加一个空行，并将结果写入另一个文件。
        """
        with open(self.input_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        with open(self.output_file, 'w', encoding='utf-8') as file:
            file.write('\n'.join(interleave_blank_lines(lines)))


class TxtFileComparator:
    """
    比较两个非常接近的文本文件并找出它们之间的差异。
    在每段中报告第一个不同的字符，并输出该段落的原文。
    忽略空行的影响，并统计每段中总共有多少个错误。
    """

    def __init__(self, file1, file2, output_file="text_differences.txt"):
        """
        初始化TxtFileComparator类。

        参数:
        - file1: 比较的文件1
        - file2: 比较的文件2
        - output_file: 输出差异的文件，默认为"text_differences.txt"
        """
        self.file1 = file1
        self.file2 = file2
        self.output_file = output_file

    @staticmethod
    def _diff_paragraphs(file1, file2):
        """
        比较两个文本文件，返回结构化差异，便于批量调用与日志记录。

        返回 dict:
          changed_paragraphs: list[dict] 每处段落差异
             {line_no, first_diff_pos, char1, char2, text1, text2}
          only_in_1: list[(int, str)]  仅文件1有的段落 (line_no, text)
          only_in_2: list[(int, str)]  仅文件2有的段落 (line_no, text)
          total_diff: int              总差异段落数
        """
        with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
            lines1 = [line.strip() for line in f1.readlines() if line.strip()]
            lines2 = [line.strip() for line in f2.readlines() if line.strip()]

        changed = []
        len_min = min(len(lines1), len(lines2))
        for i in range(len_min):
            if lines1[i] != lines2[i]:
                first_diff_index = None
                first_diff_char1 = None
                first_diff_char2 = None
                for j, (char1, char2) in enumerate(zip(lines1[i], lines2[i])):
                    if char1 != char2:
                        first_diff_index = j + 1
                        first_diff_char1 = char1
                        first_diff_char2 = char2
                        break
                # 段落长度不同时，可能 zen zip 完才发现差异；保留这一兜底
                if first_diff_index is None:
                    first_diff_index = min(len(lines1[i]), len(lines2[i])) + 1
                    if len(lines1[i]) > len(lines2[i]):
                        first_diff_char1 = lines1[i][len(lines2[i])]
                        first_diff_char2 = '(无)'
                    else:
                        first_diff_char1 = '(无)'
                        first_diff_char2 = lines2[i][len(lines1[i])]
                changed.append({
                    "line_no": i + 1,
                    "first_diff_pos": first_diff_index,
                    "char1": first_diff_char1,
                    "char2": first_diff_char2,
                    "text1": lines1[i],
                    "text2": lines2[i],
                })

        only_in_1 = [(i + 1 + len_min, lines1[i]) for i in range(len_min, len(lines1))]
        only_in_2 = [(i + 1 + len_min, lines2[i]) for i in range(len_min, len(lines2))]

        return {
            "changed_paragraphs": changed,
            "only_in_1": only_in_1,
            "only_in_2": only_in_2,
            "total_diff": len(changed) + len(only_in_1) + len(only_in_2),
        }

    def compare_file(self):
        """
        比较两个文本文件并找出它们之间的差异。
        """
        result = self._diff_paragraphs(self.file1, self.file2)

        # 报告差异
        out_title = "文件1和文件2之间的差异：\n"
        print(out_title)
        with open(self.output_file, 'w', encoding='utf-8') as file:
            file.write(out_title + '\n')

            n = 0
            for d in result["changed_paragraphs"]:
                n += 1
                file.write(f"第 {n} 个错误：\n")
                file.write(f"文件1第 {d['line_no']} 行：\n{d['text1']}\n")
                file.write(f"文件2第 {d['line_no']} 行：\n{d['text2']}\n")
                file.write(
                    f"第一个不同的字符在位置 {d['first_diff_pos']}，"
                    f"'{d['char1']}' vs '{d['char2']}'，这段共有 1 个错误\n\n"
                )
                print(f"第 {n} 个错误：")
                print(f"文件1第 {d['line_no']} 行：'{d['text1']}'")
                print(f"文件2第 {d['line_no']} 行：'{d['text2']}'")
                print(
                    f"第一个不同的字符在位置 {d['first_diff_pos']}，"
                    f"'{d['char1']}' vs '{d['char2']}'，这段共有 1 个错误"
                )

            file.write(f"总共 {result['total_diff']} 处错误")
            print(f"总共 {result['total_diff']} 处错误")

            # 检查是否有额外的行
            for line_no, text in result["only_in_1"]:
                file.write(f"文件1额外的行 {line_no}：'{text}'\n")
                print(f"文件1额外的行 {line_no}：'{text}'")
            for line_no, text in result["only_in_2"]:
                file.write(f"文件2额外的行 {line_no}：'{text}'\n")
                print(f"文件2额外的行 {line_no}：'{text}'")


def _resolve_path(path):
    """返回相对于脚本所在目录的绝对路径，便于在项目任意位置调用。"""
    if os.path.isabs(path):
        return path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, path)


class DirectoryDiffer:
    """
    目录级批量对比：标准化目录 vs 校正目录。

    配对规则（默认按数字前缀）：
      - 文件名开头数字编号相同的两文件视为同一章节，比对内容；
        允许校正目录里改了标题（如 "043 旧名.txt" -> "043 新名.txt"）。
      - 没有数字前缀的文件（如人工放进来的"附录.txt"）回退到完整文件名匹配。

    输出五类信息：
      - modified:  配对成功但内容不同（逐段列出差异）
      - unchanged: 配对成功且内容一致；若文件名不同会单独提一句"改名"
      - renamed:   仅文件名不同但内容一致
      - only_in_baseline / only_in_corrected
    所有信息同时写入 logger 与可选的差异报告文件。
    """

    def __init__(self, baseline_dir, corrected_dir, report_file=None, console_preview=3):
        self.baseline_dir = baseline_dir
        self.corrected_dir = corrected_dir
        self.report_file = report_file
        # 控制台每文件差异预览条数（日志/报告中保留全部，避免控制台刷屏）。
        self.console_preview = console_preview

    def diff(self):
        """执行对比，返回统计字典。"""
        base_prefix, base_no = _build_prefix_index(self.baseline_dir)
        cor_prefix, cor_no = _build_prefix_index(self.corrected_dir)

        common_prefixes = sorted(set(base_prefix) & set(cor_prefix), key=lambda s: int(s))
        only_base_prefix = sorted(set(base_prefix) - set(cor_prefix), key=lambda s: int(s))
        only_cor_prefix = sorted(set(cor_prefix) - set(base_prefix), key=lambda s: int(s))

        # 无数字前缀的文件按完整文件名匹配（兼容人工放进来的"附录.txt"等）
        base_no_set, cor_no_set = set(base_no), set(cor_no)
        common_no = sorted(base_no_set & cor_no_set)
        only_base_no = sorted(base_no_set - cor_no_set)
        only_cor_no = sorted(cor_no_set - base_no_set)

        logger.info(f"目录对比开始: {self.baseline_dir} vs {self.corrected_dir}")
        logger.info(
            f"按前缀配对: 共同 {len(common_prefixes)} 个；"
            f"仅标准化 {len(only_base_prefix)} 个；仅校正 {len(only_cor_prefix)} 个"
        )
        if common_no or only_base_no or only_cor_no:
            logger.info(
                f"无数字前缀文件（按完整名匹配）: 共同 {len(common_no)}；"
                f"仅标准化 {len(only_base_no)}；仅校正 {len(only_cor_no)}"
            )

        report_lines = []

        def report(line):
            logger.info(line)
            report_lines.append(line)

        modified_files = []
        unchanged_files = []
        renamed_files = []

        # —— 前缀配对部分 ——
        for prefix in common_prefixes:
            bf = base_prefix[prefix]
            cf = cor_prefix[prefix]
            path1 = os.path.join(self.baseline_dir, bf)
            path2 = os.path.join(self.corrected_dir, cf)
            result = TxtFileComparator._diff_paragraphs(path1, path2)

            if bf != cf and result["total_diff"] == 0:
                # 内容一致仅改了名 -- 标记为 renamed，归类到 unchanged 但单独提示
                renamed_files.append((prefix, bf, cf))
                unchanged_files.append(prefix)
                continue

            if result["total_diff"] == 0:
                unchanged_files.append(prefix)
                continue
            modified_files.append((prefix, bf, cf, result))

        # —— 无前缀文件按完整名配对部分 ——
        modified_no = []
        unchanged_no = []
        for fname in common_no:
            path1 = os.path.join(self.baseline_dir, fname)
            path2 = os.path.join(self.corrected_dir, fname)
            result = TxtFileComparator._diff_paragraphs(path1, path2)
            if result["total_diff"] == 0:
                unchanged_no.append(fname)
            else:
                modified_no.append((fname, result))

        # 1) 内容差异（前缀配对）
        if modified_files:
            report(f"\n{len(modified_files)} 个配对文件发现内容差异：")
            for prefix, bf, cf, result in modified_files:
                title = f"[{prefix}] {bf}"
                if bf != cf:
                    title += f"  vs  {cf}"
                report(f"\n===== {title} — {result['total_diff']} 处差异 =====")
                changed = result["changed_paragraphs"]
                for idx, d in enumerate(changed):
                    report(
                        f"  第 {d['line_no']} 段 第 {d['first_diff_pos']} 字: "
                        f"'{d['char1']}' vs '{d['char2']}'"
                    )
                    report(f"    标准化: {d['text1']}")
                    report(f"    校正版: {d['text2']}")
                    if idx + 1 == self.console_preview and len(changed) > self.console_preview:
                        remain = len(changed) - self.console_preview
                        report(f"    ... 剩余 {remain} 处段落差异见日志文件")
                        break
                if result["only_in_1"]:
                    report(f"  校正版删除了 {len(result['only_in_1'])} 段:")
                    for line_no, text in result["only_in_1"][:self.console_preview]:
                        report(f"    第 {line_no} 段 (标准化独有): {text}")
                    if len(result["only_in_1"]) > self.console_preview:
                        remain = len(result["only_in_1"]) - self.console_preview
                        report(f"    ... 剩余 {remain} 段删除见日志文件")
                if result["only_in_2"]:
                    report(f"  校正版新增了 {len(result['only_in_2'])} 段:")
                    for line_no, text in result["only_in_2"][:self.console_preview]:
                        report(f"    第 {line_no} 段 (校正独有): {text}")
                    if len(result["only_in_2"]) > self.console_preview:
                        remain = len(result["only_in_2"]) - self.console_preview
                        report(f"    ... 剩余 {remain} 段新增见日志文件")

        # 1b) 仅文件名不同、内容一致
        if renamed_files:
            report(f"\n{len(renamed_files)} 个文件仅改了文件名（内容一致）:")
            for prefix, bf, cf in renamed_files:
                report(f"  [{prefix}] {bf}  ->  {cf}")

        # 1c) 无前缀配对但内容不同
        if modified_no:
            report(f"\n{len(modified_no)} 个无前缀文件发现差异:")
            for fname, result in modified_no:
                report(f"\n===== {fname} — {result['total_diff']} 处差异 =====")
                for d in result["changed_paragraphs"][:self.console_preview]:
                    report(
                        f"  第 {d['line_no']} 段 第 {d['first_diff_pos']} 字: "
                        f"'{d['char1']}' vs '{d['char2']}'"
                    )
                    report(f"    标准化: {d['text1']}")
                    report(f"    校正版: {d['text2']}")

        if not modified_files and not modified_no and not renamed_files:
            report("\n所有配对文件内容完全一致，无差异。")

        # 2) 仅一侧存在
        if only_base_prefix or only_base_no:
            total = len(only_base_prefix) + len(only_base_no)
            report(f"\n仅标准化目录存在 {total} 个文件（未校正）:")
            for prefix in only_base_prefix:
                report(f"  [{prefix}] {base_prefix[prefix]}")
            for fname in only_base_no:
                report(f"  {fname}")

        if only_cor_prefix or only_cor_no:
            total = len(only_cor_prefix) + len(only_cor_no)
            report(f"\n仅校正目录存在 {total} 个文件（新增）:")
            for prefix in only_cor_prefix:
                report(f"  [{prefix}] {cor_prefix[prefix]}")
            for fname in only_cor_no:
                report(f"  {fname}")

        # 3) 最终摘要
        total_changed = len(modified_files) + len(modified_no)
        total_unchanged = len(unchanged_files) + len(unchanged_no)
        total_only_base = len(only_base_prefix) + len(only_base_no)
        total_only_cor = len(only_cor_prefix) + len(only_cor_no)
        report(
            f"\n对比完成: {total_changed} 篇改动，"
            f"{total_unchanged} 篇未改（其中 {len(renamed_files)} 篇仅改名），"
            f"{total_only_base} 篇未校正，{total_only_cor} 篇新增"
        )

        if self.report_file:
            with open(self.report_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_lines) + '\n')
            logger.info(f"差异报告已保存: {self.report_file}")

        return {
            "common": len(common_prefixes) + len(common_no),
            "modified": total_changed,
            "unchanged": total_unchanged,
            "renamed_only": len(renamed_files),
            "only_baseline": total_only_base,
            "only_corrected": total_only_cor,
        }


class RevisionsStore:
    """
    维护校正目录下的 _revisions.json：记录人工对每个章节的修订说明。

    key 使用文件名开头的数字前缀（如 "043"），这样校正阶段即使改了文件名（标题）
    也不会丢失修订记录。无数字前缀的文件退化为完整文件名作为 key。

    JSON 结构:
    {
      "043": {
        "msg": "删除作者 PS 与两处错字",
        "filename": "043 第一章 xxx.txt",   // 当前实际文件名（便于回看）
        "mtime": "2026-08-06T21:30:00",
        "updated_at": "2026-08-06T21:35:00"
      },
      ...
    }
    """

    FILENAME = "_revisions.json"

    def __init__(self, corrected_dir):
        self.corrected_dir = corrected_dir
        self.path = os.path.join(corrected_dir, self.FILENAME)
        self.data = self._load()

    def _load(self):
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"读取修订记录失败，将重置: {self.path} ({e})")
            return {}

    def _save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _now():
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    @staticmethod
    def _normalize_key(filename):
        """
        把传入参数规范化为 _revisions.json 的 key。

        传入可以是完整文件名 '043 xxx.txt'、纯编号 '043'、或无前缀的 '附录.txt'。
        - 有数字前缀的就用前缀作为 key（与 diff / assemble 配对一致）
        - 无前缀的退化为完整文件名作为 key，仍能工作
        """
        if filename is None:
            return None
        prefix = _file_prefix(filename)
        return prefix if prefix is not None else filename

    def set(self, filename, msg):
        """新增或覆盖单条修订记录。filename 可以是完整名或纯编号。"""
        key = self._normalize_key(filename)
        if key is None:
            raise ValueError("note add 必须提供 filename 或前缀编号")

        existing = self.data.get(key, {})
        record = {
            "msg": msg,
            # 保留上次记录里写入的 filename 字段，便于对照
            "filename": existing.get("filename", filename if filename != key else ""),
            "mtime": existing.get("mtime", ""),
            "updated_at": self._now(),
        }

        # 如果传入的是完整文件名（跟 key 不同），记下当前实际文件名
        if filename and filename != key:
            record["filename"] = filename
            file_path = os.path.join(self.corrected_dir, filename)
        else:
            # 只有编号时，扫一遍目录找出当前对应文件名
            prefix_map, _ = _build_prefix_index(self.corrected_dir)
            actual_name = prefix_map.get(key)
            record["filename"] = actual_name or ""
            file_path = os.path.join(self.corrected_dir, actual_name) if actual_name else None

        if file_path and os.path.isfile(file_path):
            ts = os.path.getmtime(file_path)
            from datetime import datetime
            record["mtime"] = datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S')

        self.data[key] = record
        self._save()

    def remove(self, filename):
        """删除一条修订记录。filename 可以是完整名或纯编号。"""
        key = self._normalize_key(filename)
        if key is None:
            return False
        if key in self.data:
            del self.data[key]
            self._save()
            return True
        # 兼容老版 _revisions.json（key 是完整文件名）
        if filename in self.data:
            del self.data[filename]
            self._save()
            return True
        return False

    def list_all(self):
        """返回 dict 副本。"""
        return dict(self.data)

    def clear(self):
        self.data = {}
        self._save()


class DirectoryAssembler:
    """
    合成最终目录：标准化目录 + 校正目录 -> final 目录。

    配对规则（默认按数字前缀，与 diff / note 一致）：
      - 校正目录里有该前缀 -> 取校正版（输出文件名也用校正版命名）
      - 校正目录里没有、标准化目录有 -> 取标准化版（未改）
      - 校正目录独有 -> 取校正版（新增）
      - 无数字前缀的文件按完整文件名匹配（兼容"附录.txt"等）
      - 跳过 _revisions.json，它本身不进入最终目录
    每个文件的来源（校正 / 标准化）记录到 _source_map.txt，便于追溯。
    """

    def __init__(self, baseline_dir, corrected_dir, output_dir):
        self.baseline_dir = baseline_dir
        self.corrected_dir = corrected_dir
        self.output_dir = output_dir

    @staticmethod
    def _copy(src_path, dst_path):
        import shutil
        shutil.copyfile(src_path, dst_path)

    def assemble(self):
        base_prefix, base_no = _build_prefix_index(self.baseline_dir)
        cor_prefix, cor_no = _build_prefix_index(self.corrected_dir)

        all_prefixes = sorted(set(base_prefix) | set(cor_prefix), key=lambda s: int(s))
        all_no = sorted(set(base_no) | set(cor_no))

        if not all_prefixes and not all_no:
            logger.warning("两个源目录都没有 txt 文件，无内容可合成。")
            return {"baseline_count": 0, "corrected_count": 0, "total": 0}

        os.makedirs(self.output_dir, exist_ok=True)

        logger.info(f"合成开始: {self.baseline_dir} + {self.corrected_dir} -> {self.output_dir}")
        logger.info(
            f"待合成: 前缀配对 {len(all_prefixes)} 个 + 无前缀 {len(all_no)} 个"
        )

        from_corrected = 0
        from_baseline = 0
        renamed_count = 0
        mapping_lines = []

        # —— 前缀配对部分 ——
        for prefix in all_prefixes:
            in_cor = prefix in cor_prefix
            in_base = prefix in base_prefix
            if in_cor:
                src_name = cor_prefix[prefix]
                src = os.path.join(self.corrected_dir, src_name)
                src_label = "校正"
                from_corrected += 1
            elif in_base:
                src_name = base_prefix[prefix]
                src = os.path.join(self.baseline_dir, src_name)
                src_label = "标准化"
                from_baseline += 1
            else:
                continue
            dst = os.path.join(self.output_dir, src_name)
            self._copy(src, dst)

            # 标记是否发生改名（同前缀但两侧文件名不同）
            rename_note = ""
            if in_cor and in_base and base_prefix[prefix] != cor_prefix[prefix]:
                renamed_count += 1
                rename_note = (f"  (改名: {base_prefix[prefix]} -> {cor_prefix[prefix]})")

            line = f"  [{prefix}] {src_name}  <- {src_label}{rename_note}"
            logger.info(line)
            mapping_lines.append(line)

        # —— 无数字前缀文件按完整名配对 ——
        for fname in all_no:
            in_cor = fname in cor_no
            in_base = fname in base_no
            if in_cor:
                src = os.path.join(self.corrected_dir, fname)
                src_label = "校正"
                from_corrected += 1
            elif in_base:
                src = os.path.join(self.baseline_dir, fname)
                src_label = "标准化"
                from_baseline += 1
            else:
                continue
            dst = os.path.join(self.output_dir, fname)
            self._copy(src, dst)
            line = f"  {fname}  <- {src_label}"
            logger.info(line)
            mapping_lines.append(line)

        # 把来源映射单独写入 final 目录，便于事后查证
        mapping_file = os.path.join(self.output_dir, "_source_map.txt")
        with open(mapping_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(mapping_lines) + '\n')
        total = len(all_prefixes) + len(all_no)
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


class VolumeSplitter:
    """
    拆分卷打包的原始下载文件为独立章节（用于 pixiv 系列中"一卷一个文件、
    卷内全部章节未划分"的情况）。

    处理流程（按输入目录文件数字前缀顺序，一个文件视为一卷）：
      1. 识别卷内的章节标记行（独立成行、整行长度 <= 40）：
           - "第一章 xxx" / "第11章 xxx" / "第一章：xxx"（中文或阿拉伯数字）
           - "番外：xxx" / "番外 xxx"
      2. 按标记行拆出各章内容；第一个标记之前的内容视为卷标题/前言，跳过
      3. 修正作者标号错误：按出现顺序重排章节编号（以首个可解析标记的编号为起点，
         例如原文 第二十章/第十九章/第二十章 -> 第十九章/第二十章/第二十一章；
         中文数字风格保持中文、阿拉伯数字风格保持阿拉伯）
      4. 按全局顺序导出 "<3位编号> <章节标题>.txt" 到输出目录（standardized）；
         --name-only 时文件名只含章节名不带章节号（如 "003 雪棠.txt"，完整标题
         保留在文件首行），默认文件名含完整标题（如 "003 第3章 雪棠.txt"）
      5. 在输出目录的上级目录（series_xxx）生成 volumes.json，锚定每卷的全局
         章节范围，供 epub --volumes 直接使用
    """

    # 章节标记：第X章/第X话/第X节/第X回（含小数点容忍，但重排仅支持整数编号）
    MARKER_RE = re.compile(r'^第([一二三四五六七八九十百千万零两0-9.]+)([章话节回])')
    # 番外标记：仅"番外"单独成行或"番外：xxx"（避免把"番外内容"等正文行误识别为标记）
    FANWAI_RE = re.compile(r'^番外([：:].*)?$')

    def __init__(self, input_dir, output_dir, punct=False, name_only=False,
                 title_len_limit=False):
        """
        参数:
        - input_dir: 卷打包的原始章节 txt 所在目录
        - output_dir: 拆分后的章节输出目录（如 standardized/）
        - punct: 是否同时对正文做英文标点 -> 中文标点转换
        - name_only: True 时文件名只保留章节名不带章节号（完整标题仍在文件首行）；
                     默认 False（文件名含完整章节标题）
        - title_len_limit: 严格模式，无空格的章节标记额外要求整行 <= 20 字符
                     （默认 False：不限长度，仅靠"不含句号"判定，兼容长标题网文）
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.punct = punct
        self.name_only = name_only
        self.title_len_limit = title_len_limit

    def _parse_marker(self, line):
        """
        判断一行是否为章节标记行。返回 (marker, num, style)：
          marker: 完整标记行文本（如 "第一章 回家的召唤"）
          num:    编号整数（无法解析时 None）
          style:  'chinese' / 'arabic'（编号风格，无法解析时 None）
        不是标记行返回 None。
        """
        s = line.strip()
        if not s or len(s) > 40:
            return None
        m = VolumeSplitter.MARKER_RE.match(s)
        if m:
            rest = s[m.end():]
            # 编号后跟空格/冒号/行尾 -> 肯定是标记；
            # 编号后直接跟文字（作者漏写空格，如"第二章天使降临我身边？"）：
            #   判定为章节标题的核心条件：不含句号「。」（标题是一个短语，可带？！
            #   但几乎不带句号；正文段落必有句号等句子终止符，如"第三章内容。"）
            #   title_len_limit 开启时额外要求整行 <= 20 字符（防长正文误判，
            #   但可能误伤长标题网文，故默认关闭）
            if rest and not rest[0].isspace() and rest[0] not in '：:':
                if '。' in s or (self.title_len_limit and len(s) > 20):
                    return None
            num_text = m.group(1)
            if re.fullmatch(r'\d+', num_text):
                return s, int(num_text), 'arabic'
            num = _chinese_to_int(num_text)
            if num is not None:
                return s, num, 'chinese'
            return s, None, None
        if VolumeSplitter.FANWAI_RE.match(s):
            # 番外不算编号（保持原样不重排）
            return s, None, 'fanwai'
        return None

    def _split_file(self, path):
        """
        读取单个卷文件，返回 (segments, preamble)：
          segments: [{"marker": 原标记行, "title": 修正后标题, "lines": [正文行...]}, ...]
          preamble: 第一个标记之前的非空行列表（卷标题/前言，跳过不导出）
        """
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

        segments = []
        preamble = []
        current = None
        for line in lines:
            marker = self._parse_marker(line)
            if marker:
                current = {"marker": marker[0], "title": marker[0], "lines": []}
                segments.append(current)
            elif current is None:
                if line.strip():
                    preamble.append(line.strip())
            else:
                current["lines"].append(line)
        return segments, preamble

    def _renumber_segments(self, segments):
        """
        按出现顺序修正章节编号（修正作者标号错误，如重复/回退的编号）。
        以第一个可解析编号为起点，按可编号章节的出现顺序依次递增；
        番外等无法解析编号的标记保持原样且不占编号。返回 (segments, fixed_count)。
        """
        first_num = None
        style = None
        for seg in segments:
            _, num, st = self._parse_marker(seg["marker"])
            if num is not None:
                first_num, style = num, st
                break

        fixed_count = 0
        counter = 0
        for seg in segments:
            _, num, _st = self._parse_marker(seg["marker"])
            if num is None or style is None:
                continue
            new_num = first_num + counter
            counter += 1
            old_prefix = re.match(r'^(第[一二三四五六七八九十百千万零两0-9.]+)([章话节回])',
                                  seg["marker"])
            if not old_prefix:
                continue
            suffix = old_prefix.group(2)
            if new_num != num:
                fixed_count += 1
            if style == 'chinese':
                new_marker = f"第{_int_to_chinese(new_num)}{suffix}"
            else:
                new_marker = f"第{new_num}{suffix}"
            # 编号后的衔接：原标记编号后是空格/冒号则保留原样；
            # 无空格（作者漏写，如"第二章天使降临"）则补一个空格，
            # 让输出统一为 "第二十二章 天使降临"
            rest = seg["marker"][old_prefix.end():]
            if rest and not rest[0].isspace() and rest[0] not in '：:':
                seg["title"] = (new_marker + ' ' + rest.rstrip())
            else:
                seg["title"] = (new_marker + rest.rstrip())
        return segments, fixed_count

    @staticmethod
    def _chapter_name(title):
        """
        从章节标题中去掉章节号前缀，只保留章节名（文件首行仍有完整标题）。
        "第3章 雪棠" -> "雪棠"；"第一章 序幕" -> "序幕"；"番外：小剧场" 保持原样；
        标题只有编号（如"第一章"）时回退完整标题。
        """
        s = title.strip()
        m = re.match(r'^第[一二三四五六七八九十百千万零两0-9.]+[章话节回]\s*[：:]?\s*', s)
        if m:
            name = s[m.end():].strip()
            if name:
                return name
        return s

    def split(self):
        """
        执行拆分：遍历输入目录全部 txt，导出章节并生成 volumes.json。
        返回统计 dict；无内容可拆返回 None。
        """
        if not os.path.isdir(self.input_dir):
            logger.error(f"输入目录不存在: {self.input_dir}")
            return None
        os.makedirs(self.output_dir, exist_ok=True)

        files = [f for f in os.listdir(self.input_dir) if f.lower().endswith('.txt')]
        # 过滤索引/元数据文件（series_*_summary.txt / series_*_info.txt 等）与书籍信息占位
        files = [f for f in files
                 if not f.startswith(('series_', '_', '000 '))]

        def sort_key(filename):
            match = re.search(r'^(\d+)', filename)
            return (0, int(match.group(1))) if match else (1, filename)

        txt_files = sorted(files, key=sort_key)
        if not txt_files:
            logger.error(f"输入目录 {self.input_dir} 中没有 txt 文件。")
            return None

        volumes = []
        seq = 0
        total_fixed = 0
        total_preamble = 0

        logger.info(f"拆卷开始: {self.input_dir} -> {self.output_dir}（{len(txt_files)} 个文件）")
        for fname in txt_files:
            path = os.path.join(self.input_dir, fname)
            segments, preamble = self._split_file(path)
            if preamble:
                total_preamble += 1
                logger.info(f"  {fname}: 跳过卷标题/前言 {len(preamble)} 行"
                            f"（{' '.join(p[:20] for p in preamble[:2])}...）")

            if not segments:
                # 无卷内标记：整文件作为一个章节原样导出（标题取文件名，不算卷）
                title = re.sub(r'^\d+\s*', '', fname)
                if title.lower().endswith('.txt'):
                    title = title[:-4]
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                seq += 1
                out_name = f"{seq:03d} {_sanitize_filename_part(title.strip())}.txt"
                self._write_chapter(out_name, content)
                logger.info(f"  [{seq:03d}] {title.strip()}（整文件无卷内标记）")
                continue

            segments, fixed = self._renumber_segments(segments)
            total_fixed += fixed
            vol_start = seq + 1
            vol_name = re.sub(r'^\d+\s*', '', fname)
            if vol_name.lower().endswith('.txt'):
                vol_name = vol_name[:-4]
            vol_name = vol_name.strip()

            for seg in segments:
                seq += 1
                title = seg["title"].strip()
                name = self._chapter_name(title) if self.name_only else title
                out_name = f"{seq:03d} {_sanitize_filename_part(name)}.txt"
                self._write_chapter(out_name, '\n'.join([title] + seg["lines"]))
                logger.info(f"  [{seq:03d}] {title}")
            vol_end = seq
            volumes.append({"name": vol_name, "start": vol_start, "end": vol_end})
            logger.info(f"  卷「{vol_name}」: 章节 {vol_start:03d}~{vol_end:03d}"
                        + (f"（编号修正 {fixed} 处）" if fixed else ""))

        # volumes.json 写到输出目录的上级（series_xxx 目录），供 epub --volumes 使用
        parent = os.path.dirname(os.path.abspath(self.output_dir)) or self.output_dir
        vol_path = os.path.join(parent, 'volumes.json')
        with open(vol_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(volumes, ensure_ascii=False, indent=4) + '\n')

        # 末尾自动生成 000 书籍信息.txt（与 format 行为一致：
        # 输入目录上级能找到 series_*_info.txt 则套模板填充，否则空白占位）
        try:
            BookInfoGenerator(self.input_dir).generate(self.output_dir)
        except Exception as e:
            logger.warning(f"生成 000 书籍信息.txt 失败: {e}")

        logger.info(f"拆卷完成: 共导出 {seq} 章（{len(volumes)} 卷"
                    + (f"，编号修正 {total_fixed} 处" if total_fixed else "")
                    + f"，跳过前言 {total_preamble} 个文件）")
        logger.info(f"卷配置已生成: {vol_path}")
        return {"chapters": seq, "volumes": len(volumes),
                "fixed": total_fixed, "preamble_files": total_preamble,
                "volumes_file": vol_path}

    def _write_chapter(self, out_name, content):
        """写单个章节文件：标题行 + 段落空行（可选标点转换）。"""
        if self.punct:
            content, _ = convert_punctuation(content)
        lines = [line.strip() for line in content.splitlines()]
        out_path = os.path.join(self.output_dir, out_name)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(interleave_blank_lines(lines)) + '\n')


class EpubBuilder:
    """
    把章节目录打包为 EPUB 电子书（纯标准库实现，零第三方依赖）。

    打包结构（参照 FanFicFare / lncrawl 的手写方案，仅用 zipfile 与字符串模板）：
        <输出>.epub
        ├── mimetype                 # 固定 application/epub+zip，必须第一个写入且不压缩 (ZIP_STORED)
        ├── META-INF/container.xml   # 指向 OEBPS/content.opf
        └── OEBPS/
            ├── content.opf          # 元数据 + 文件清单 manifest + 阅读顺序 spine
            ├── toc.ncx              # EPUB2 目录（兼容老阅读器）
            ├── nav.xhtml            # EPUB3 目录导航
            ├── style.css            # 中文排版样式
            ├── vol_001.xhtml ...    # 卷/篇页（可选，独立占页，每卷一个）
            └── chap_001.xhtml ...   # 每章一个 XHTML

    章节收集：与 merge 相同的多目录配对语义（按数字前缀，后列目录优先，
    校正版覆盖标准化版）；"000 书籍信息.txt" 视为元数据不进入章节。

    卷/篇（可选）：通过 --volumes 传入 JSON 配置文件（见 _load_volumes 的格式说明），
    每卷生成一个独立占页的 vol_<n>.xhtml（卷名垂直居中），并在 toc.ncx / nav.xhtml
    目录中作为章节的上级嵌套；未配置卷时行为与旧版完全一致。

    元数据：优先解析输入目录里的 000 书籍信息.txt（从优先级最高的目录往前找），
    其次回退 pixiv 系列 info.txt / metadata.json（复用 BookInfoGenerator），
    最后用占位值；--title / --author 可显式覆盖。
    """

    # ---- 模板（参照 lncrawl 的 assets/epub 模板文件思路，此处内置为类常量） ----
    CHAPTER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h1 class="chapter-title">{title_html}</h1>
{body}
</body>
</html>"""

    # 卷/篇页：独立占页，卷名垂直居中（CSS 见 .volume-page / .volume-title；可拆两行）
    VOLUME_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{name}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="volume-page">
<div class="volume-title">{content}</div>
</body>
</html>"""

    # 书籍信息页：按 000 书籍信息.txt 的段落格式渲染（有真实信息来源才生成）
    BOOK_INFO_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="book-info-page">
<h1 class="book-info-title">书籍信息</h1>
{body}
</body>
</html>"""

    # 封面页：图片自适应占满一页（有封面文件时生成，spine 第一位）
    COVER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>封面</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="cover-page">
<div class="cover-image"><img src="{img}" alt="封面"/></div>
</body>
</html>"""

    NAV_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>目录</title>
</head>
<body>
<nav epub:type="toc" id="toc">
<h1>目录</h1>
<ol>
{items}
</ol>
</nav>
</body>
</html>"""

    NCX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
<head>
<meta name="dtb:uid" content="{uid}"/>
<meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/>
<meta name="dtb:maxPageNumber" content="0"/>
</head>
<docTitle><text>{title}</text></docTitle>
<navMap>
{points}
</navMap>
</ncx>"""

    CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>"""

    # 中文排版：首行缩进 2em、1.8 倍行距、两端对齐
    # 卷/篇页：独立占页（前后强制分页）+ 卷名垂直居中（padding-top 35% 兼容性最好）
    # 章标题样式由 _build_title_css 生成（对齐/颜色/字号/下划线均可配置）
    CSS = """body {{
    font-family: "Source Han Serif SC", "Noto Serif CJK SC", "SimSun", serif;
    line-height: 1.8;
    margin: 5% 6%;
    text-align: justify;
}}
h1.chapter-title {{
{chapter_title_css}
p {{
    text-indent: 2em;
    margin: 0 0 0.6em 0;
}}
.volume-page {{
    margin: 0;
    padding: 0;
    page-break-before: always;
    page-break-after: always;
}}
{volume_title_css}
.book-info-page p {{
    text-indent: 0;
    text-align: center;
    margin: 0 0 1.2em 0;
}}
.book-info-page .book-info-name {{
    font-size: 1.4em;
    font-weight: bold;
    margin: 0 0 1.5em 0;
}}
h1.book-info-title {{
    text-align: center;
    font-size: 1.8em;
    margin: 0 0 2em 0;
}}
.cover-page {{
    margin: 0;
    padding: 0;
    text-align: center;
}}
.cover-page .cover-image img {{
    max-width: 100%;
    max-height: 100%;
}}
.illustration {{
    text-align: center;
    margin: 1.5em 0;
    text-indent: 0;
}}
.illustration img {{
    max-width: 90%;
    height: auto;
}}
.illustration .illustration-desc {{
    font-size: 0.85em;
    color: #666666;
    margin-top: 0.5em;
    text-indent: 0;
}}"""

    # 章标题默认样式：居中、1.5em、无颜色、无下划线（与 v0.7.x 旧版行为一致）
    # split=True 时章节号与章名拆两行显示（第一行 .chapter-num，第二行 .chapter-name），
    # num_color / num_size 控制章节号行，color / size 控制章名行
    DEFAULT_TITLE_STYLE = {
        "align": "center",
        "color": "",
        "size": "1.5em",
        "underline": False,
        "split": False,
        "num_color": "",
        "num_size": "1em",
    }

    # 卷名默认样式：拆两行（卷号小灰 + 卷名大号深红，中间留间距）
    DEFAULT_VOLUME_STYLE = {
        "vol_split": True,
        "vol_num_color": "#555555",
        "vol_num_size": "1.2em",
        "vol_color": "#8B0000",
        "vol_size": "2.5em",
        "vol_gap": "0.6em",
    }

    # 样式预设示例模板（首次运行时若无 epub_styles.json 会自动生成此内容）
    # 分两段：chapter = 章标题样式，volume = 卷名样式，分别由 --title-style / --vol-style 调用
    STYLE_SAMPLE = {
        "chapter": {
            "default": {
                "align": "center",
                "color": "",
                "size": "1.5em",
                "underline": False,
                "desc": "默认章节样式：居中、1.5em、黑色、无下划线",
            },
            "split_title": {
                "align": "center",
                "color": "#8B0000",
                "size": "1.4em",
                "underline": True,
                "split": True,
                "num_color": "#555555",
                "num_size": "1em",
                "desc": "章节号与章名拆两行：上行小号灰色章节号，下行大号深红章名",
            },
        },
        "volume": {
            "default": {
                "vol_split": True,
                "vol_num_color": "#555555",
                "vol_num_size": "1.2em",
                "vol_color": "#8B0000",
                "vol_size": "2.5em",
                "vol_gap": "0.6em",
                "desc": "默认卷名样式：拆两行，卷号小灰、卷名大号深红",
            },
        },
    }

    @classmethod
    def load_presets(cls, styles_file=None):
        """
        读取样式预设文件（默认项目根目录 epub_styles.json），分两段：
            {
                "chapter": { 样式名 -> {align, color, size, underline, split, num_color, num_size, desc} },
                "volume":  { 样式名 -> {vol_split, vol_num_color, vol_num_size, vol_color, vol_size, vol_gap, desc} }
            }
        "chapter" 段由 --title-style 调用，"volume" 段由 --vol-style 调用。

        文件不存在时自动生成示例模板文件（chapter 含 default / split_title，
        volume 含 default）。旧版扁平格式（顶层直接是样式名）按章节预设兼容读取。

        返回 {"chapter": {...}, "volume": {...}}；解析失败返回空两段 dict。
        """
        if styles_file is None:
            styles_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'epub_styles.json')
        empty = {"chapter": {}, "volume": {}}
        if not os.path.isfile(styles_file):
            try:
                with open(styles_file, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(cls.STYLE_SAMPLE, ensure_ascii=False, indent=4) + '\n')
                logger.info(f"未找到样式预设文件，已生成示例模板: {styles_file}")
            except OSError as e:
                logger.warning(f"无法创建样式预设文件 {styles_file}: {e}")
                return empty
        try:
            with open(styles_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"样式预设文件解析失败（{styles_file}）: {e}")
            return empty
        if not isinstance(data, dict):
            logger.warning('样式预设文件应为 JSON 对象 {"chapter": {...}, "volume": {...}}')
            return empty

        # 兼容旧版扁平格式：顶层直接是样式名 -> 全部按章节预设读取
        if "chapter" in data or "volume" in data:
            chapter_raw = data.get("chapter", {})
            volume_raw = data.get("volume", {})
        else:
            logger.warning("样式预设文件为旧版扁平格式，已按 chapter 段读取"
                           "（卷样式请改为 \"volume\" 段，并用 --vol-style 调用）")
            chapter_raw = data
            volume_raw = {}
        return {
            "chapter": cls._parse_styles(chapter_raw, volume=False),
            "volume": cls._parse_styles(volume_raw, volume=True),
        }

    @staticmethod
    def _parse_styles(styles, volume=False):
        """解析一段样式预设（volume=False 为章节样式，True 为卷名样式）。"""
        presets = {}
        for name, style in styles.items():
            if not isinstance(style, dict):
                logger.warning(f"样式预设 {name!r} 无效（应为对象），已跳过")
                continue
            if volume:
                presets[name] = {
                    "vol_split": bool(style.get("vol_split", True)),
                    "vol_num_color": str(style.get("vol_num_color", "#555555")),
                    "vol_num_size": str(style.get("vol_num_size", "1.2em")),
                    "vol_color": str(style.get("vol_color", "#8B0000")),
                    "vol_size": str(style.get("vol_size", "2.5em")),
                    "vol_gap": str(style.get("vol_gap", "0.6em")),
                    "desc": str(style.get("desc", "")),
                }
                continue
            align = style.get("align", "center")
            if align not in ("center", "left"):
                logger.warning(f"样式预设 {name!r} 的 align {align!r} 无效（仅支持 center/left），已跳过")
                continue
            presets[name] = {
                "align": align,
                "color": str(style.get("color", "")),
                "size": str(style.get("size", "1.5em")),
                "underline": bool(style.get("underline", False)),
                "split": bool(style.get("split", False)),
                "num_color": str(style.get("num_color", "")),
                "num_size": str(style.get("num_size", "1em")),
                "desc": str(style.get("desc", "")),
            }
        return presets

    def __init__(self, input_folders, output_file, title=None, author=None,
                 volumes_file=None, title_style=None, vol_style=None, cover=None,
                 illustrations_file=None, image_quality=None):
        """
        参数:
        - input_folders: 章节 txt 目录，可传单个字符串或列表；
                         列表时后面的目录优先级高（同名/同前缀章节取后者的版本）。
        - output_file: 输出的 .epub 文件路径
        - title / author: 可选，显式覆盖元数据中的书名/作者
        - volumes_file: 可选，卷/篇配置文件路径（JSON，见 _load_volumes）
        - title_style: 可选 dict，章标题样式：
            align: 'center' 或 'left'（对齐方式）
            color: CSS 颜色（如 '#8B0000'），空串表示继承正文黑色
            size: CSS 字号（如 '1.5em'）
            underline: True 时标题下加与 color 同色的 2px 实线
        - vol_style: 可选 dict，卷名样式：
            vol_split: 是否拆两行（默认 True）
            vol_num_color / vol_num_size: 卷号行颜色/字号
            vol_color / vol_size: 卷名行颜色/字号
            vol_gap: 两行之间的间距
        - cover: 可选，显式指定封面图片路径；不指定时自动查找输入目录
                 及其父目录下的 cover.* / 封面.* 图片
        - illustrations_file: 可选，插图信息文件路径（见 _parse_illustrations_file）；
                 不指定时自动查找输入目录中的 插图信息.txt
        - image_quality: 可选，1-100 的 JPEG 压缩质量；设置后插图用 Pillow 重编码
                 为 JPEG（PNG/JPEG 均可，压缩后未变小则保留原图），未设置不压缩
        """
        if isinstance(input_folders, str):
            input_folders = [input_folders]
        self.input_folders = input_folders
        self.output_file = output_file
        self.overrides = {"title": title, "author": author}
        self.volumes_file = volumes_file
        self.cover = cover
        self.illustrations_file = illustrations_file
        self.image_quality = image_quality
        # 合并默认样式，用户只覆盖提供的项
        self.title_style = dict(self.DEFAULT_TITLE_STYLE)
        if title_style:
            self.title_style.update(title_style)
        self.vol_style = dict(self.DEFAULT_VOLUME_STYLE)
        if vol_style:
            self.vol_style.update(vol_style)

    # ---- 插图 ----

    ILLUSTRATION_MARKER_RE = re.compile(r'【插图[:：]\s*([^】]+)】')

    def _find_illustration_dirs(self):
        """收集插图库候选目录（输入目录及其父目录下的 插图库/ 或 illustrations/）。"""
        dirs = []
        seen = set()
        for d in reversed(self.input_folders):
            for base in (d, os.path.dirname(os.path.abspath(d))):
                for sub in ("插图库", "illustrations"):
                    c = os.path.join(base, sub)
                    if os.path.isdir(c) and c not in seen:
                        seen.add(c)
                        dirs.append(c)
        return dirs

    def _find_image(self, img_name):
        """在插图库候选目录中查找图片文件，返回路径；找不到返回 None。"""
        for d in self._find_illustration_dirs():
            path = os.path.join(d, img_name)
            if os.path.isfile(path):
                return path
        return None

    def _maybe_compress_image(self, img_name, path):
        """
        按 self.image_quality 压缩插图（Pillow 重编码为 JPEG）。
        返回 (zip_name, data_or_path)：
          - 未启用压缩 / 无 Pillow / 压缩失败 / 压缩后未变小 -> (img_name, path) 原样
          - 压缩成功 -> (新文件名 <原名>_q<质量>.jpg, bytes)
        """
        if not self.image_quality:
            return img_name, path
        try:
            from PIL import Image
        except ImportError:
            logger.warning("未安装 Pillow，跳过插图压缩（可执行 pip install Pillow 启用）")
            self.image_quality = None  # 本次会话不再尝试
            return img_name, path
        try:
            with Image.open(path) as im:
                rgb = im.convert('RGB')
                buf = io.BytesIO()
                rgb.save(buf, format='JPEG', quality=self.image_quality, optimize=True)
                data = buf.getvalue()
        except Exception as e:
            logger.warning(f"插图压缩失败，使用原图 {img_name}: {e}")
            return img_name, path
        if len(data) >= os.path.getsize(path):
            logger.info(f"  插图 {img_name} 压缩后未变小，保留原图")
            return img_name, path
        stem, _ = os.path.splitext(img_name)
        new_name = f"{stem}_q{self.image_quality}.jpg"
        logger.info(f"  插图压缩: {img_name} -> {new_name} "
                    f"({os.path.getsize(path) // 1024}KB -> {len(data) // 1024}KB)")
        return new_name, data

    def _image_html(self, img_name, desc=None):
        """
        生成插图 HTML（居中图片 + 可选描述）。
        找不到图片文件时返回 None（调用方保留原文标记并告警）。
        启用压缩时先压缩（见 _maybe_compress_image），src 与 manifest 使用压缩后的文件名。
        """
        path = self._find_image(img_name)
        if not path:
            logger.warning(f"插图文件未找到，保留原文标记: {img_name}")
            return None
        zip_name, data = self._maybe_compress_image(img_name, path)
        self._used_images[zip_name] = data
        html = f'<div class="illustration"><img src="img/{zip_name}" alt="插图"/>'
        if desc:
            desc_text = '<br/>'.join(self._escape(line) for line in desc)
            html += f'<div class="illustration-desc">{desc_text}</div>'
        html += '</div>'
        return html

    def _render_inline_illustrations(self, text):
        """
        把段落中的【插图: xxx】标记替换为插图 HTML：
          - 整段只有一个标记 -> 插图（文本为空）
          - 标记与文字混排 -> 文字与插图依次输出
        找不到图片时保留标记原文（含告警，见 _image_html）。
        返回 HTML 片段列表（<p> 或插图 <div>）。
        """
        out = []
        pos = 0
        text_buf = []

        def flush_text():
            if text_buf:
                out.append(f"<p>{self._escape(''.join(text_buf).strip())}</p>")
                text_buf.clear()

        for m in self.ILLUSTRATION_MARKER_RE.finditer(text):
            before = text[pos:m.start()]
            if before.strip():
                text_buf.append(before)
            html = self._image_html(m.group(1).strip())
            if html is None:
                text_buf.append(m.group(0))
            else:
                flush_text()
                out.append(html)
            pos = m.end()
        rest = text[pos:]
        if rest.strip():
            text_buf.append(rest)
        flush_text()
        return out

    def _parse_illustrations_file(self, path):
        """
        解析插图信息文件（--illustrations 指定或自动识别插图信息.txt / 插图信息.json）。
        按文件内容自动识别两种格式：

        A. txt 格式：
            043 xxx                    （可选章节头：3 位数字开头（可单独成行或后跟内容），
                                        设定当前章节，后面的条目默认归属该章）
            【插图: ch041_up_22901790.jpg】
            描述插画的信息（可多行，直到下一个标记/章节头）
        B. JSON 格式（数组，结构严格）：
            [
                {"chapter": 41, "img": "ch041_up_22901790.jpg", "desc": "描述插画的信息"},
                {"chapter": "002", "img": "up_12345.png", "desc": "描述"}
            ]

        插图归属章节：txt 优先取文件名中的 ch<编号>（pixiv 命名），否则用章节头；
        JSON 用 chapter 字段（数字或 3 位字符串，缺省时回退文件名 ch<编号>）；
        都没有则跳过并警告。
        返回 {章节key: [{"img": 文件名, "desc": [描述行...]}, ...]}。
        """
        with open(path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        # 首字符是 [ 或 { 时按 JSON 解析；失败回退 txt 格式
        stripped = content.lstrip()
        if stripped.startswith(('[', '{')):
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"插图信息文件 {path} 解析 JSON 失败，已按 txt 格式处理")
                return self._parse_illustrations_txt(content)
            logger.info("插图信息文件格式: JSON")
            return self._parse_illustrations_json(data)
        return self._parse_illustrations_txt(content)

    def _parse_illustrations_txt(self, content):
        """解析 txt 格式的插图信息。"""
        entries = {}
        current_chapter = None
        current_entry = None

        def store(entry):
            if not entry["chapter"]:
                logger.warning(f"插图条目无法确定归属章节，已跳过: {entry['img']}")
                return
            entries.setdefault(entry["chapter"], []).append(
                {"img": entry["img"], "desc": entry["desc"]})

        for line in content.splitlines():
            s = line.strip()
            if not s:
                continue
            m = re.match(r'^(\d{3})(?:\s|$)', s)
            if m:
                current_chapter = m.group(1)
                current_entry = None
                continue
            m2 = self.ILLUSTRATION_MARKER_RE.fullmatch(s)
            if m2:
                if current_entry is not None:
                    store(current_entry)
                img = m2.group(1).strip()
                ch_m = re.search(r'ch(\d+)', img, re.IGNORECASE)
                chapter = ch_m.group(1) if ch_m else current_chapter
                current_entry = {"img": img, "chapter": chapter, "desc": []}
                continue
            if current_entry is not None:
                current_entry["desc"].append(s)
        if current_entry is not None:
            store(current_entry)
        return entries

    @staticmethod
    def _parse_illustrations_json(data):
        """解析 JSON 格式的插图信息（数组）。"""
        entries = {}
        if not isinstance(data, list):
            logger.warning("插图信息 JSON 应为数组 [{\"chapter\": 1, \"img\": \"...\"}, ...]")
            return entries
        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict) or not item.get("img"):
                logger.warning(f"插图信息 JSON 第 {i} 条无效（缺少 img），已跳过: {item}")
                continue
            img = str(item["img"]).strip()
            ch_m = re.search(r'ch(\d+)', img, re.IGNORECASE)
            chapter = ch_m.group(1) if ch_m else None
            if "chapter" in item:
                try:
                    chapter = f"{int(item['chapter']):03d}"
                except (TypeError, ValueError):
                    chapter = None
            if not chapter:
                logger.warning(f"插图信息 JSON 第 {i} 条无法确定归属章节，已跳过: {img}")
                continue
            desc_lines = [l.strip() for l in str(item.get("desc") or "").splitlines()
                          if l.strip()]
            entries.setdefault(chapter, []).append({"img": img, "desc": desc_lines})
        return entries

    def _find_illustrations_info(self):
        """自动查找输入目录中的 插图信息.txt / 插图信息.json。"""
        for d in reversed(self.input_folders):
            for name in ("插图信息.txt", "插图信息.json", "illustrations.json"):
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    return path
        return None

    # ---- 封面 ----

    @staticmethod
    def _image_mimetype(path):
        """按扩展名返回图片 MIME 类型。"""
        ext = os.path.splitext(path)[1].lower()
        return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")

    def _find_cover(self):
        """
        确定封面图片路径：
          1. --cover 显式指定（文件不存在则报错并返回 None）
          2. 自动查找：输入目录（后列优先级高在前）及其父目录下的 cover.* / 封面.*
        返回图片文件路径，找不到返回 None。
        """
        if self.cover:
            if not os.path.isfile(self.cover):
                logger.error(f"指定的封面文件不存在: {self.cover}")
                return None
            logger.info(f"封面图片（--cover 指定）: {self.cover}")
            return self.cover

        exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        candidates = []
        seen = set()
        for d in reversed(self.input_folders):
            for c in (d, os.path.dirname(os.path.abspath(d))):
                if c and os.path.isdir(c) and c not in seen:
                    seen.add(c)
                    candidates.append(c)
        for d in candidates:
            for fname in sorted(os.listdir(d)):
                stem, ext = os.path.splitext(fname.lower())
                if ext in exts and stem in ("cover", "封面"):
                    path = os.path.join(d, fname)
                    logger.info(f"封面图片（自动识别）: {path}")
                    return path
        return None

    # ---- 章节收集（复用 merge 的多目录配对语义） ----

    def _collect_chapters(self):
        """
        从多个输入目录按数字前缀（或无前缀的完整文件名）收集章节。
        后面的目录优先级高；"000 书籍信息.txt" 是元数据不是章节，跳过。
        返回按前缀排序的 [(key, display_title, file_path)] 列表。
        """
        from collections import OrderedDict
        collected = OrderedDict()
        for d in self.input_folders:
            if not os.path.isdir(d):
                logger.warning(f"输入目录不存在，已跳过: {d}")
                continue
            for fname in os.listdir(d):
                if not fname.lower().endswith('.txt'):
                    continue
                if fname.startswith('000 '):
                    continue
                prefix = _file_prefix(fname)
                key = prefix if prefix is not None else fname
                collected[key] = (fname, os.path.join(d, fname))

        # 排序：数字前缀按整数升序；无前缀文件排在最后
        def sort_key(item_key):
            if isinstance(item_key, str) and item_key.isdigit():
                return (0, int(item_key))
            return (1, item_key)

        result = []
        for key in sorted(collected.keys(), key=sort_key):
            fname, path = collected[key]
            result.append((key, self._chapter_title(fname), path))
        return result

    @staticmethod
    def _chapter_title(fname):
        """从 '<编号> <标题>.txt' 提取章节标题（去掉数字前缀与扩展名）。"""
        title = re.sub(r'^\d+\s*', '', fname)
        if title.lower().endswith('.txt'):
            title = title[:-4]
        return title.strip()

    @staticmethod
    def _escape(text):
        """转义 XML/HTML 特殊字符（& < > " '）。"""
        return html.escape(text)

    def _resolve_chapter_title(self, path, fname_title):
        """
        决定章节展示标题：
          - 文件首行若是章节标记行（第X章/番外，如 split 拆卷输出），
            用它作标题并标记首行需从正文剔除；
          - 否则用文件名推导的标题（format 输出首行与之相同，由 _chapter_body 去重）。
        返回 (display_title, skip_first)。
        """
        with open(path, 'r', encoding='utf-8') as f:
            first = None
            for line in f:
                s = line.strip()
                if s:
                    first = s
                    break
        if first and VolumeSplitter('', '')._parse_marker(first):
            return first, True
        return fname_title, False

    def _chapter_body(self, path, display_title, skip_first=False,
                      chapter_key=None, illu_map=None):
        """
        读章节正文，返回 XHTML 片段（<p> 段落 + 插图 <div>）。
        skip_first=True 时丢弃首行（该行是章节标记行，已作为标题渲染）；
        否则若正文首段与展示标题一致（format 注入的标题行），丢弃该段避免与 h1 重复。
        正文中的【插图: xxx】标记在对应位置内嵌图片；illu_map 中该章节的插图
        （来自插图信息文件）追加在章节末尾。
        """
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        paras = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if skip_first:
                skip_first = False
                continue
            if not paras and stripped == display_title:
                continue
            if self.ILLUSTRATION_MARKER_RE.search(stripped):
                paras.extend(self._render_inline_illustrations(stripped))
            else:
                paras.append(f"<p>{self._escape(stripped)}</p>")
        # 章节末尾：追加插图信息文件中属于本章的插图（人工校正删掉正文标记后的方案）
        if chapter_key and illu_map and chapter_key in illu_map:
            for entry in illu_map[chapter_key]:
                html = self._image_html(entry["img"], entry["desc"] or None)
                if html:
                    paras.append(html)
        return '\n'.join(paras)

    # ---- 元数据 ----

    def _find_book_info(self):
        """
        解析书籍元数据：
          1. 输入目录中的 000 书籍信息.txt（多个输入目录都存在时取 mtime 最新——
             重新 format 后的新字段优先，用户手改过的同样优先；只搜输入目录本身，
             避免误命中父目录里其他系列/无关的 000）
          2. pixiv 系列 info.txt / metadata.json（复用 BookInfoGenerator）
          3. 占位默认值
        返回 (info_dict, found)：
          info: title/author/platform/status/word_count/description
          found: True 表示有真实书籍信息来源（000 文件或 pixiv 信息），
                 False 表示纯占位（此时不生成书籍信息页）
        """
        candidates = []
        for d in reversed(self.input_folders):
            path = os.path.join(d, '000 书籍信息.txt')
            if os.path.isfile(path) and path not in candidates:
                candidates.append(path)
        if candidates:
            path = max(candidates, key=os.path.getmtime)
            logger.info(f"书籍信息来源: {path}")
            return self._parse_book_info_file(path), True

        info = BookInfoGenerator(self.input_folders[0])._find_pixiv_info()
        if info:
            logger.info("未找到 000 书籍信息.txt，回退到 pixiv 系列 info/metadata")
            return {
                "title": info.get("title") or "未填",
                "author": info.get("author") or "未填",
                "platform": info.get("platform") or "Pixiv",
                "status": "",
                "word_count": BookInfoGenerator._format_wan(info.get("word_count", 0)),
                "description": info.get("description") or "未填",
            }, True

        logger.warning("未找到任何书籍信息源，使用占位元数据（可用 --title/--author 覆盖）")
        return {
            "title": "未填", "author": "未填", "platform": "",
            "status": "", "word_count": "", "description": "未填",
        }, False

    @staticmethod
    def _parse_book_info_file(path):
        """
        解析 000 书籍信息.txt（段落间空行格式）：
            书籍信息
            <书名>
            作者：xxx
            连载平台：xxx
            连载状态：xxx
            字数：xxx
            简介：
            <简介...>
        """
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        info = {"title": "未填", "author": "未填", "platform": "",
                "status": "", "word_count": "", "vol_count": "", "description": ""}

        # 书名 = 第二个非空段（第一段是 "书籍信息" 标题）
        non_empty = [ln.strip() for ln in lines if ln.strip()]
        if len(non_empty) >= 2:
            info["title"] = non_empty[1]

        # 键值字段与简介
        in_desc = False
        desc = []
        for ln in lines:
            stripped = ln.strip()
            if in_desc:
                if stripped:
                    desc.append(stripped)
                continue
            for sep in ('：', ':'):
                if sep in stripped:
                    key, _, value = stripped.partition(sep)
                    key = key.strip()
                    value = value.strip()
                    if key in ('作者', '作者'):
                        info['author'] = value
                    elif key in ('连载平台', '连载于'):
                        info['platform'] = value
                    elif key == '连载状态':
                        info['status'] = value
                    elif key in ('卷/篇数', '卷数', '分卷'):
                        info['vol_count'] = value
                    elif key == '字数':
                        info['word_count'] = value
                    elif key == '简介':
                        in_desc = True
                        if value:
                            desc.append(value)
                    break
        if desc:
            info['description'] = '\n'.join(desc)
        return info

    # ---- 三个 XML 骨架文件 ----

    def _content_opf(self, title, author, info, uid, spine_items,
                     cover_img_name=None, used_images=None):
        """
        生成 content.opf：元数据 + manifest + spine。
        spine_items 为 build 阶段规划好的阅读顺序列表（封面 + 书籍信息 + 卷页 + 章节）。
        cover_img_name 非空时加入封面图（EPUB3 properties="cover-image"）与
        EPUB2 兼容的 <meta name="cover"> / <guide> 封面引用。
        used_images 为已嵌入的插图 {文件名: 路径}，加入 manifest。
        """
        items = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
            '<item id="css" href="style.css" media-type="text/css"/>',
        ]
        if cover_img_name:
            cover_mime = self._image_mimetype(cover_img_name)
            items.append(f'<item id="cover-img" href="{cover_img_name}" '
                         f'media-type="{cover_mime}" properties="cover-image"/>')
        for img_name in sorted(used_images or {}):
            items.append(f'<item id="img-{len(items)}" href="img/{img_name}" '
                         f'media-type="{self._image_mimetype(img_name)}"/>')
        itemrefs = []
        for it in spine_items:
            items.append(f'<item id="{it["id"]}" href="{it["fname"]}" media-type="application/xhtml+xml"/>')
            itemrefs.append(f'<itemref idref="{it["id"]}"/>')

        meta_lines = [
            f'<dc:title>{self._escape(title)}</dc:title>',
            f'<dc:creator>{self._escape(author)}</dc:creator>',
            '<dc:language>zh-CN</dc:language>',
            f'<meta property="dcterms:modified">'
            f'{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>',
        ]
        if cover_img_name:
            meta_lines.append('<meta name="cover" content="cover-img"/>')
        if info.get("description") and info["description"] != "未填":
            meta_lines.append(f'<dc:description>{self._escape(info["description"])}</dc:description>')
        if info.get("status"):
            meta_lines.append(f'<meta name="pixiv:status" content="{self._escape(info["status"])}"/>')
        if info.get("word_count"):
            meta_lines.append(f'<meta name="pixiv:word_count" content="{self._escape(info["word_count"])}"/>')

        guide = ""
        if cover_img_name:
            guide = ('\n  <guide>\n'
                     '    <reference type="cover" title="封面" href="cover.xhtml"/>\n'
                     '  </guide>')

        return f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="zh-CN">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
{chr(10).join(meta_lines)}
  </metadata>
  <manifest>
{chr(10).join(items)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(itemrefs)}
  </spine>{guide}
</package>'''

    def _toc_ncx(self, title, uid, spine_items):
        """
        生成 toc.ncx：EPUB2 目录（老阅读器兼容）。
        卷页为一层 navPoint，其所属章节（按 vol 标记）为嵌套的子 navPoint；
        playOrder 按阅读顺序（父卷先于其子章）。
        """
        points = []
        order = 0

        def open_point(fname, text):
            nonlocal order
            order += 1
            return (f'<navPoint id="np_{order}" playOrder="{order}">'
                    f'<navLabel><text>{self._escape(text)}</text></navLabel>'
                    f'<content src="{fname}"/>')

        i = 0
        while i < len(spine_items):
            item = spine_items[i]
            if item["kind"] == "vol":
                vi = item["vol"]
                i += 1
                children = []
                while (i < len(spine_items) and spine_items[i]["kind"] == "chap"
                       and spine_items[i].get("vol") == vi):
                    children.append(spine_items[i])
                    i += 1
                # 先分配父卷序号，再分配子章（playOrder 按阅读顺序）
                parent = open_point(item["fname"], item["title"])
                inner = ''.join(open_point(c["fname"], c["title"]) + '</navPoint>'
                                for c in children)
                points.append(parent + inner + '</navPoint>')
            else:
                points.append(open_point(item["fname"], item["title"]) + '</navPoint>')
                i += 1

        return self.NCX_TEMPLATE.format(uid=uid, title=self._escape(title),
                                        points='\n'.join(points))

    def _nav_xhtml(self, spine_items):
        """
        生成 nav.xhtml：EPUB3 目录导航。
        卷为一级 li，其所属章节（按 vol 标记）为嵌套的 <ol> 子列表；
        游离章节（不属于任何卷）保持一级。
        """
        items = []
        i = 0
        while i < len(spine_items):
            item = spine_items[i]
            if item["kind"] == "vol":
                vi = item["vol"]
                i += 1
                children = []
                while (i < len(spine_items) and spine_items[i]["kind"] == "chap"
                       and spine_items[i].get("vol") == vi):
                    children.append(spine_items[i])
                    i += 1
                inner = '\n'.join(
                    f'<li><a href="{c["fname"]}">{self._escape(c["title"])}</a></li>'
                    for c in children
                )
                items.append(
                    f'<li><a href="{item["fname"]}">{self._escape(item["title"])}</a>\n'
                    f'<ol>\n{inner}\n</ol>\n</li>'
                )
            else:
                items.append(f'<li><a href="{item["fname"]}">{self._escape(item["title"])}</a></li>')
                i += 1
        return self.NAV_TEMPLATE.format(items='\n'.join(items))

    # ---- 卷/篇配置与阅读顺序规划 ----

    @staticmethod
    def _validate_css_value(value, pattern, what):
        """校验用户传入的 CSS 值是否安全（只含合法字符），非法时警告并返回 None。"""
        import re as _re
        if value and not _re.fullmatch(pattern, value.strip()):
            logger.warning(f"章标题{what} {value!r} 不是合法的 CSS 值，已忽略该项设置")
            return None
        return value.strip() if value else value

    @staticmethod
    def _split_title(display_title):
        """
        把章标题拆成「章节号 + 章节名」两行显示的两部分。

        支持形态：
          - "第一章 xxx" / "第2.5章 xxx" / "第38话 xxx"  -> ("第一章", "xxx")
          - "番外：xxx" / "番外 xxx"                      -> ("番外", "xxx")
        无法识别时返回 (None, 完整标题)，由调用方决定是否拆行。
        """
        # 番外：冒号或空格后为章名
        m = re.match(r'^番外[：:]\s*(.+)$', display_title)
        if m:
            return "番外", m.group(1).strip()
        m = re.match(r'^番外\s+(.+)$', display_title)
        if m:
            return "番外", m.group(1).strip()
        # 第X章 / 第X话 / 第X回（中文数字或阿拉伯数字，含小数点），编号后跟空格为章名
        m = re.match(r'^(第[0-9一二三四五六七八九十百千万零点.]+[章话回节])\s+(.+)$', display_title)
        if m:
            return m.group(1), m.group(2).strip()
        return None, display_title

    def _build_title_html(self, display_title):
        """
        根据标题样式生成 h1 内部 HTML：
          - split 开启且能识别章节号时：<div class="chapter-num">第一章</div>
                                          <div class="chapter-name">章名</div>
          - 否则：直接标题文本（与旧版一致）

        用 div 而非 span：div 是原生块级元素，即使阅读器（如微信读书）剥掉
        display:block 布局 CSS，div 也天然换行；span 被剥掉后会退回行内导致并成一行。
        """
        if self.title_style.get("split", False):
            num, name = self._split_title(display_title)
            if num is not None:
                return (f'<div class="chapter-num">{self._escape(num)}</div>'
                        f'<div class="chapter-name">{self._escape(name)}</div>')
        return self._escape(display_title)

    def _build_book_info_body(self, info, title, author):
        """
        生成书籍信息页正文（按 000 书籍信息.txt 的段落格式渲染）：
            书籍信息        （页面标题，模板已含）
            <书名>          （大号加粗）
            作者：xxx
            连载平台：xxx
            连载状态：xxx
            卷/篇数：N
            字数：xxx
            简介：
            <简介每段一个 p>
        书名/作者优先取 --title/--author 覆盖值。
        """
        paras = [
            (f'<p class="book-info-name">{self._escape(title)}</p>'),
            f'<p>{self._escape("作者：" + (author or "未填"))}</p>',
        ]
        if info.get("platform"):
            paras.append(f'<p>{self._escape("连载平台：" + info["platform"])}</p>')
        if info.get("status"):
            paras.append(f'<p>{self._escape("连载状态：" + info["status"])}</p>')
        if info.get("vol_count"):
            paras.append(f'<p>{self._escape("卷/篇数：" + info["vol_count"])}</p>')
        if info.get("word_count"):
            paras.append(f'<p>{self._escape("字数：" + info["word_count"])}</p>')
        desc = (info.get("description") or "").strip()
        if desc and desc != "未填":
            paras.append('<p>简介：</p>')
            for line in desc.splitlines():
                if line.strip():
                    paras.append(f'<p>{self._escape(line.strip())}</p>')
        return '\n'.join(paras)

    @staticmethod
    def _split_volume_title(name):
        """
        把卷名拆成「卷号 + 卷名」两行显示的两部分：
          "第一卷 示例卷名"        -> ("第一卷", "示例卷名")
          "第三卷 示例卷名"  -> ("第三卷", "示例卷名")
          "番外篇 往事"           -> ("番外篇", "往事")
        无法识别时返回 (None, 完整卷名)，由调用方决定是否拆行。
        """
        m = re.match(r'^(第[一二三四五六七八九十百千万零两0-9.]+[卷部篇集]|番外(?:篇)?)\s*(.*)$', name)
        if m and m.group(2).strip():
            return m.group(1).strip(), m.group(2).strip()
        return None, name

    def _build_volume_html(self, name):
        """
        根据样式生成卷页标题 HTML：
          - vol_split 开启且能识别卷号时：<div class="volume-num">第一卷</div>
                                           <div class="volume-name">示例卷名</div>
          - 否则：单行 <div class="volume-name">卷名</div>
            （始终套 .volume-name，避免无卷号的卷名掉回正文默认字号/颜色）

        用 div 而非 span：div 是原生块级元素，即使阅读器（如微信读书）剥掉
        display:block 布局 CSS 也天然换行（span 会退回行内并成一行）。
        """
        if self.vol_style.get("vol_split", True):
            num, vol_name = self._split_volume_title(name)
            if num is not None:
                return (f'<div class="volume-num">{self._escape(num)}</div>'
                        f'<div class="volume-name">{self._escape(vol_name)}</div>')
        return f'<div class="volume-name">{self._escape(name)}</div>'

    def _build_volume_css(self):
        """
        生成 .volume-title 的 CSS 规则（拆两行时卷号/卷名各自可调颜色、字号与间距）：
          - 基础规则：加粗、居中、无缩进、padding-top 35% 垂直居中
          - vol_split 开启：.volume-num（vol_num_color/vol_num_size + vol_gap 下间距）
                            与 .volume-name（vol_color/vol_size）
          - 关闭：字号/颜色直接作用于 .volume-title
        """
        style = self.vol_style
        vol_color = self._validate_css_value(
            style.get("vol_color", "#8B0000"), r"[#0-9a-zA-Z(),.%\s-]+", "卷名颜色")
        vol_size = self._validate_css_value(
            style.get("vol_size", "2.5em"), r"[0-9]+(\.[0-9]+)?\s*(em|px|pt|%|rem)", "卷名字号")
        if vol_color is None:
            vol_color = "#8B0000"
        if vol_size is None:
            vol_size = "2.5em"

        base = [
            ".volume-title {",
            "    display: block;",
            "    font-weight: bold;",
            "    text-align: center;",
            "    text-indent: 0;",
            "    border-bottom: none;",
            "    margin-top: 0;",
            "    padding-top: 35%;",
        ]
        if style.get("vol_split", True):
            base.append("}")
            num_color = self._validate_css_value(
                style.get("vol_num_color", "#555555"), r"[#0-9a-zA-Z(),.%\s-]+", "卷号颜色")
            num_size = self._validate_css_value(
                style.get("vol_num_size", "1.2em"),
                r"[0-9]+(\.[0-9]+)?\s*(em|px|pt|%|rem)", "卷号字号")
            gap = self._validate_css_value(
                style.get("vol_gap", "0.6em"),
                r"[0-9]+(\.[0-9]+)?\s*(em|px|pt|%|rem)", "卷号间距")
            if num_color is None:
                num_color = "#555555"
            if num_size is None:
                num_size = "1.2em"
            if gap is None:
                gap = "0.6em"
            base.append(".volume-title .volume-num {")
            base.append("    display: block;")
            base.append(f"    font-size: {num_size};")
            base.append(f"    color: {num_color};")
            base.append(f"    margin-bottom: {gap};")
            base.append("}")
            base.append(".volume-title .volume-name {")
            base.append("    display: block;")
            base.append(f"    font-size: {vol_size};")
            base.append(f"    color: {vol_color};")
            base.append("}")
        else:
            base.append(f"    font-size: {vol_size};")
            base.append(f"    color: {vol_color};")
            base.append("}")
        return '\n'.join(base) + '\n'

    def _build_title_css(self):
        """
        根据 title_style 生成 h1.chapter-title 的 CSS 规则字符串。

        参考样式（左对齐 + 深红 + 下划线）：
            text-align: left; color: #8B0000; font-size: 1.2em;
            padding-bottom: 0.5em; border-bottom: #8B0000 solid 2px;
        """
        style = self.title_style
        align = style.get("align", "center")
        if align not in ("center", "left"):
            logger.warning(f"章标题对齐方式 {align!r} 无效，仅支持 center/left，已回退 center")
            align = "center"

        color = self._validate_css_value(
            style.get("color", ""), r"[#0-9a-zA-Z(),.%\s-]+", "颜色")
        size = self._validate_css_value(
            style.get("size", "1.5em"), r"[0-9]+(\.[0-9]+)?\s*(em|px|pt|%|rem)", "字号")
        underline = bool(style.get("underline", False))

        if size is None:
            size = "1.5em"

        rules = [
            f"    text-align: {align};",
            f"    font-size: {size};",
            "    font-weight: bold;",
            "    line-height: 1.5;",
            "    text-indent: 0;",
        ]
        if color:
            rules.append(f"    color: {color};")
        if underline:
            # 下划线用与标题同色（无颜色设置时默认深红 #8B0000）
            line_color = color or "#8B0000"
            rules.append(f"    border-bottom: {line_color} solid 2px;")
            rules.append("    padding-bottom: 0.5em;")
            rules.append("    margin: 0 0 0.8em;")
        else:
            rules.append("    margin: 0 0 2em 0;")

        # 闭合 h1.chapter-title 块（模板中 {chapter_title_css} 之后不再补 }，
        # 拆两行的 span 规则也由本方法整体输出，避免花括号失衡导致整份样式失效）
        css = '\n'.join(rules) + '\n}'

        # 拆两行模式：章节号行与章名行的独立样式（各自可调颜色/字号）
        if style.get("split", False):
            num_color = self._validate_css_value(
                style.get("num_color", ""), r"[#0-9a-zA-Z(),.%\s-]+", "章节号颜色")
            num_size = self._validate_css_value(
                style.get("num_size", "1em"), r"[0-9]+(\.[0-9]+)?\s*(em|px|pt|%|rem)", "章节号字号")
            if num_color is None:
                num_color = color or ""
            if num_size is None:
                num_size = "1em"
            span_rules = [
                "h1.chapter-title .chapter-num {",
                "    display: block;",
                f"    font-size: {num_size};",
                "    line-height: 1.4;",
                "    margin-bottom: 0.35em;",
            ]
            if num_color:
                span_rules.append(f"    color: {num_color};")
            span_rules.append("}")
            span_rules.append("h1.chapter-title .chapter-name {")
            span_rules.append("    display: block;")
            span_rules.append("}")
            css += '\n' + '\n'.join(span_rules) + '\n'
        return css

    def _load_volumes(self):
        """
        读取卷/篇配置文件（--volumes 指定），JSON 列表格式：
            [
                {"name": "第一卷 示例卷名", "start": 1, "end": 17},
                {"name": "第二卷 示例卷名", "start": 18, "end": 35}
            ]
        - name: 卷/篇标题（显示在独立卷页与目录里）
        - start / end: 章节文件数字前缀范围（含端点）；只写 start 时视为单章
        返回按 start 排序的 [{name, start, end}] 列表；未配置或配置为空返回 []；
        文件不存在 / 解析失败返回 None（build 将中止）。
        """
        return _load_volumes_file(self.volumes_file)

    def _plan_spine(self, chapters, volumes):
        """
        规划阅读顺序：卷页插入其范围内首章之前，其余章节保持原顺序。

        返回 (spine_items, vol_chapter_map):
          spine_items: 按阅读顺序的条目列表
            {"kind": "vol",  "fname": "vol_1.xhtml", "id": "vol_1", "title": "第一卷 xxx"}
            {"kind": "chap", "key": "001", "fname": "chap_001.xhtml", "id": "chap_001",
             "title": "第一章 xxx", "path": "..."}
          vol_chapter_map: {卷序号: [该卷包含的章节 key 列表]}
        """
        # 过滤掉范围内没有匹配章节的卷（给出警告，不生成无内容的卷页）
        valid_vols = []
        for vol in volumes:
            keys = [key for key, _, _ in chapters
                    if key.isdigit() and vol["start"] <= int(key) <= vol["end"]]
            if not keys:
                logger.warning(f"卷「{vol['name']}」范围内没有匹配章节"
                               f"（{vol['start']}-{vol['end']}），不生成该卷页")
                continue
            valid_vols.append({"name": vol["name"], "start": vol["start"],
                               "end": vol["end"], "keys": keys})
            logger.info(f"卷「{vol['name']}」: 覆盖 {len(keys)} 章（{keys[0]}~{keys[-1]}）")

        vol_first = {i + 1: vol["keys"][0] for i, vol in enumerate(valid_vols)}
        vol_chapter_map = {i + 1: vol["keys"] for i, vol in enumerate(valid_vols)}

        spine_items = []
        chap_seq = 0
        for key, display_title, path in chapters:
            # 该章节属于哪一卷（无匹配则为 None）
            vol_idx = None
            if key.isdigit():
                for vi, vol in enumerate(valid_vols, start=1):
                    if vol["start"] <= int(key) <= vol["end"]:
                        vol_idx = vi
                        break
            # 卷页插在卷内第一章之前
            if vol_idx is not None and key == vol_first[vol_idx]:
                spine_items.append({
                    "kind": "vol",
                    "fname": f"vol_{vol_idx}.xhtml",
                    "id": f"vol_{vol_idx}",
                    "title": valid_vols[vol_idx - 1]["name"],
                    "vol": vol_idx,
                })
            chap_seq += 1
            fname = f"chap_{key}.xhtml" if key.isdigit() else f"chap_{chap_seq:04d}.xhtml"
            spine_items.append({
                "kind": "chap", "key": key,
                "fname": fname, "id": fname[:-6],
                "title": display_title, "path": path,
                "vol": vol_idx,
            })
        return spine_items, vol_chapter_map

    # ---- 主流程 ----

    def build(self):
        """
        收集章节并打包为 EPUB 文件。返回输出文件路径，失败返回 None。
        """
        chapters = self._collect_chapters()
        if not chapters:
            logger.error("所有输入目录中都没有章节 txt，无法生成 EPUB。")
            return None

        volumes = self._load_volumes()
        if volumes is None:
            logger.error("卷/篇配置读取失败，中止打包（可去掉 --volumes 参数重试）。")
            return None

        spine_items, vol_chapter_map = self._plan_spine(chapters, volumes)
        if not spine_items:
            logger.error("没有可打包的内容。")
            return None

        # 每次打包前刷新书籍信息：按实际打包章节重新统计章节数与字数，
        # 更新 000 书籍信息.txt（写回优先级最高的输入目录，通常是 corrected/；
        # 只搜输入目录本身，避免误命中父目录里其他系列的 000）
        try:
            BookInfoGenerator(self.input_folders).update_word_count_for_merge(
                search_parent=False, volumes=volumes)
        except Exception as e:
            logger.warning(f"书籍信息刷新失败（继续打包）: {e}")

        info, info_found = self._find_book_info()
        title = self.overrides["title"] or info["title"]
        author = self.overrides["author"] or info["author"]
        uid = f"urn:uuid:{uuid.uuid4()}"

        # 有真实书籍信息来源时，在书的最前面生成书籍信息页（并进入目录）
        if info_found:
            spine_items.insert(0, {
                "kind": "info",
                "fname": "book_info.xhtml",
                "id": "book_info",
                "title": "书籍信息",
            })

        # 封面：有封面图片时生成封面页并放在全书最前（spine 第一位）
        cover_file = self._find_cover()
        if self.cover and not cover_file:
            logger.error("指定的封面文件不存在，中止打包（可去掉 --cover 参数重试）。")
            return None
        cover_img_name = None
        if cover_file:
            ext = os.path.splitext(cover_file)[1].lower() or ".jpg"
            cover_img_name = f"cover{ext}"
            spine_items.insert(0, {
                "kind": "cover",
                "fname": "cover.xhtml",
                "id": "cover",
                "title": "封面",
                "img": cover_img_name,
            })

        # 插图信息文件（--illustrations 显式指定或自动识别 插图信息.txt）
        illu_file = self.illustrations_file or self._find_illustrations_info()
        illu_map = {}
        if illu_file:
            if os.path.isfile(illu_file):
                illu_map = self._parse_illustrations_file(illu_file)
                total = sum(len(v) for v in illu_map.values())
                logger.info(f"插图信息文件: {illu_file}（{total} 条）")
            else:
                logger.error(f"指定的插图信息文件不存在: {illu_file}")
                return None
        self._used_images = {}

        out_dir = os.path.dirname(os.path.abspath(self.output_file))
        os.makedirs(out_dir, exist_ok=True)

        logger.info(f"EPUB 打包开始: {len(chapters)} 章"
                    + (f" + {len(vol_chapter_map)} 卷页" if vol_chapter_map else "")
                    + (f" + 1 书籍信息页" if info_found else "")
                    + f" -> {self.output_file}")
        logger.info(f"  书名: {title} | 作者: {author}")

        # mimetype 必须第一个写入且不压缩（ZIP_STORED），否则阅读器不认
        with zipfile.ZipFile(self.output_file, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr('mimetype', 'application/epub+zip')

        # 其余内容用 DEFLATED 压缩追加写入
        with zipfile.ZipFile(self.output_file, 'a', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('META-INF/container.xml', self.CONTAINER_XML)
            zf.writestr('OEBPS/style.css',
                        self.CSS.format(chapter_title_css=self._build_title_css(),
                                        volume_title_css=self._build_volume_css()))

            for item in spine_items:
                if item["kind"] == "cover":
                    zf.write(cover_file, f'OEBPS/{cover_img_name}')
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.COVER_TEMPLATE.format(img=item["img"]),
                    )
                    logger.info(f"  [封面] {os.path.basename(cover_file)}")
                elif item["kind"] == "info":
                    body = self._build_book_info_body(info, title, author)
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.BOOK_INFO_TEMPLATE.format(title=self._escape(item["title"]),
                                                       body=body),
                    )
                    logger.info(f"  [书籍信息] {item['title']}")
                elif item["kind"] == "vol":
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.VOLUME_TEMPLATE.format(name=self._escape(item["title"]),
                                                    content=self._build_volume_html(item["title"])),
                    )
                    logger.info(f"  [卷] {item['title']}")
                else:
                    resolved_title, skip_first = self._resolve_chapter_title(
                        item["path"], item["title"])
                    body = self._chapter_body(item["path"], resolved_title,
                                              skip_first=skip_first,
                                              chapter_key=item.get("key"),
                                              illu_map=illu_map)
                    zf.writestr(
                        f'OEBPS/{item["fname"]}',
                        self.CHAPTER_TEMPLATE.format(title=self._escape(resolved_title),
                                                     title_html=self._build_title_html(resolved_title),
                                                     body=body),
                    )
                    item["title"] = resolved_title  # 目录/日志用解析后的标题
                    logger.info(f"  [{item['key']}] {resolved_title}")

            # 插图图片文件写进包（OEBPS/img/ 下；压缩过的为 bytes，其余为原路径）
            for img_name, img_data in sorted(self._used_images.items()):
                if isinstance(img_data, bytes):
                    zf.writestr(f'OEBPS/img/{img_name}', img_data)
                else:
                    zf.write(img_data, f'OEBPS/img/{img_name}')
            if self._used_images:
                logger.info(f"  已嵌入插图 {len(self._used_images)} 张")

            zf.writestr('OEBPS/content.opf',
                        self._content_opf(title, author, info, uid, spine_items,
                                          cover_img_name=cover_img_name,
                                          used_images=self._used_images))
            zf.writestr('OEBPS/toc.ncx', self._toc_ncx(title, uid, spine_items))
            zf.writestr('OEBPS/nav.xhtml', self._nav_xhtml(spine_items))

        logger.info(f"EPUB 生成完成: {self.output_file}"
                    f"（{len(spine_items) - len(vol_chapter_map) - (1 if info_found else 0)} 章"
                    + (f" + {len(vol_chapter_map)} 卷页" if vol_chapter_map else "")
                    + (f" + 1 书籍信息页" if info_found else "") + "）")
        return self.output_file


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
                  volumes_file=volumes_file, indent=args.indent).merge_txt_files()
    return 0


def _cmd_split(args):
    """
    拆卷：把"一卷一个文件、卷内章节未划分"的原始下载内容拆成独立章节文件，
    按全局顺序编号导出到输出目录，并在其上级目录生成 volumes.json。
    """
    input_dir = _resolve_path(args.input_dir)
    output_dir = _resolve_path(args.output_dir)

    if not os.path.isdir(input_dir):
        logger.error(f"输入目录不存在: {input_dir}")
        return 1

    result = VolumeSplitter(input_dir, output_dir, punct=args.punct,
                            name_only=args.name_only,
                            title_len_limit=args.title_len_limit).split()
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
        help="拆卷：把一卷一个文件、卷内章节未划分的原始下载内容拆成独立章节文件"
             "（识别第X章/番外标记行，按顺序修正作者编号错误，全局连续编号导出到"
             "输出目录，并在其上级目录生成 volumes.json）"
    )
    p_split.add_argument("input_dir", help="卷打包的原始章节 txt 目录（如 chapters/）")
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
    p_split.set_defaults(func=_cmd_split)

    return parser


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    configure_postprocess_logging(base_dir)
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
