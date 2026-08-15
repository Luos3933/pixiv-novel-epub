"""
Pixiv 小说下载工具。

功能概览：
- 支持按单章下载小说正文。
- 支持根据 CSV 记录批量下载多章内容。
- 支持解析系列并自动下载全部章节。
- 支持下载正文中引用或嵌入的插图，并在文本中替换为本地文件标记。
"""

import csv
import glob
import json
import logging
import os
import re
import threading
import time

import requests
from requests import exceptions as requests_exceptions

try:
    from tqdm import tqdm
except ImportError:  # tqdm 未安装时回退为普通迭代，保持可移植性。
    def tqdm(iterable=None, **kwargs):
        return iterable if iterable is not None else iter(())

__version__ = "0.6.0"

logger = logging.getLogger("pixiv_novel_toolkit")


# ---------------------------------------------------------------------------
# 纯辅助函数：不依赖 self，提取到模块级便于单测与复用。
# ---------------------------------------------------------------------------

def clean_filename(filename):
    """清理 Windows 不允许出现在文件名中的字符。"""
    return re.sub(r'[\/\\\:\*\?\"\<\>\|]', '_', filename)


def clean_html(raw_html):
    """将简介中的 HTML 标签转换为纯文本。"""
    if not raw_html:
        return ""
    text = raw_html.replace('<br />', '\n').replace('<br>', '\n')
    clean_text = re.sub(r'<[^>]+>', '', text)
    return clean_text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').strip()


def parse_chapter_selection(selection_text, total_chapters):
    """
    解析章节选择输入。

    支持：
    - 单章：11
    - 区间：11-21
    - 留空：全部章节
    """
    selection_text = (selection_text or "").strip()
    if not selection_text:
        return list(range(1, total_chapters + 1))

    match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", selection_text)
    if not match:
        raise ValueError("Invalid chapter selection format. Use '11' or '11-21'.")

    start_num = int(match.group(1))
    end_num = int(match.group(2) or start_num)

    if start_num > end_num:
        raise ValueError("The chapter range start cannot be greater than the end.")
    if start_num < 1 or end_num > total_chapters:
        raise ValueError(f"Chapter selection is out of range. Available chapters: 1-{total_chapters}.")

    return list(range(start_num, end_num + 1))


def extract_tag_names(tags_data):
    """将 Pixiv 返回的标签结构统一转换为标签名列表。"""
    tag_names = []
    if isinstance(tags_data, dict):
        candidates = tags_data.get("tags") or tags_data.get("items") or []
    else:
        candidates = tags_data or []

    for item in candidates:
        if isinstance(item, dict):
            tag_name = (
                item.get("tag")
                or item.get("name")
                or item.get("translation")
                or item.get("userTag")
            )
            if isinstance(tag_name, dict):
                tag_name = tag_name.get("en") or tag_name.get("romaji") or tag_name.get("name")
        else:
            tag_name = str(item).strip()

        if tag_name:
            tag_names.append(str(tag_name).strip())

    # 保留原始顺序去重
    return list(dict.fromkeys(tag_names))


class PixivNovelScraper:
    """
    Pixiv 小说下载器。

    该类负责与 Pixiv 小说接口交互，完成章节下载、系列解析、
    插图保存、CSV 记录维护以及章节摘要汇总等工作。
    """

    def __init__(self, cookie="", base_dir=None):
        """
        初始化下载器配置。

        参数:
            cookie: 用于访问受限内容的 Pixiv 登录态 Cookie。
            base_dir: 所有输出文件的根目录；默认使用脚本所在目录。
        """
        self.cookie = cookie
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.novels_dir = os.path.join(self.base_dir, "novels")
        self.series_dir = os.path.join(self.base_dir, "series")
        self.request_timeout = 20
        self.max_retries = 3
        self.retry_delay = 2.0
        # 每个章节实际下载完成后的延迟，降低连续请求触发风控的概率；
        # 仅在真正发起网络请求时生效，跳过已存在章节时不会占用时间。
        self.chapter_delay = 1.5
        # 索引文件并发写入时的互斥锁（workers>1 时启用）。
        self._index_lock = threading.Lock()

        self.ensure_dir(self.novels_dir)
        self.ensure_dir(self.series_dir)

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.pixiv.net/',  # Pixiv 图片资源需要合法 Referer 才能访问
            'Accept-Language': 'zh-CN,zh;q=0.9',
}
        if self.cookie:
            self.headers['Cookie'] = self.cookie

    def ensure_dir(self, path):
        """确保指定目录存在。"""
        os.makedirs(path, exist_ok=True)

    def chapter_file_exists(self, chapters_dir, chapter_num):
        """
        检查指定章节编号对应的正文 txt 是否已存在。

        不依赖标题，仅按编号前缀匹配（如 "011 xxx.txt"），便于在请求 API 之前就跳过。
        """
        try:
            normalized_num = f"{int(chapter_num):03d}"
        except (ValueError, TypeError):
            normalized_num = str(chapter_num).strip()
        pattern = f"{normalized_num} *.txt"
        return bool(glob.glob(os.path.join(chapters_dir, pattern)))

    def build_novel_output_dir(self, novel_id):
        """返回单章小说的输出目录。"""
        return os.path.join(self.novels_dir, f"novel_{novel_id}")

    def build_series_output_dir(self, series_id):
        """返回系列小说的输出目录。"""
        return os.path.join(self.series_dir, f"series_{series_id}")

    def build_chapters_dir(self, work_dir):
        """返回正文章节文件所在目录。"""
        return os.path.join(work_dir, "chapters")

    def build_images_dir(self, work_dir):
        """返回插图目录。优先沿用已存在的旧中文目录名以保持兼容。"""
        legacy = os.path.join(work_dir, "插图库")
        if os.path.isdir(legacy):
            return legacy
        return os.path.join(work_dir, "illustrations")

    def build_record_file(self, scope, target_id):
        """返回 CSV 记录文件路径。"""
        work_dir = self.build_novel_output_dir(target_id) if scope == "novel" else self.build_series_output_dir(target_id)
        return os.path.join(work_dir, f"{scope}_{target_id}_records.csv")

    def build_metadata_file(self, scope, target_id):
        """返回 JSON 元数据文件路径。"""
        work_dir = self.build_novel_output_dir(target_id) if scope == "novel" else self.build_series_output_dir(target_id)
        return os.path.join(work_dir, f"{scope}_{target_id}_metadata.json")

    def build_summary_file(self, scope, target_id):
        """返回章节简介汇总文件路径。"""
        work_dir = self.build_novel_output_dir(target_id) if scope == "novel" else self.build_series_output_dir(target_id)
        return os.path.join(work_dir, f"{scope}_{target_id}_summary.txt")

    def build_series_catalog_file(self):
        """返回系列名称对照表文件路径。存放于 series 目录下，与作品数据集中管理。"""
        return os.path.join(self.series_dir, "_catalog.csv")

    def build_series_info_file(self, series_id):
        """返回系列信息说明文件路径。"""
        return os.path.join(self.build_series_output_dir(series_id), f"series_{series_id}_info.txt")

    def build_cover_file(self, work_dir, ext=".jpg"):
        """返回封面图片文件路径（系列目录下 cover.<ext>）。"""
        return os.path.join(work_dir, f"cover{ext}")

    def download_series_cover(self, series_id, overview):
        """
        从系列总览信息下载封面图到系列目录（cover.<ext>）。

        cover 字段结构: overview['cover']['urls'] = {"original": "...", "480mw": "..."}。
        已存在 cover.* 时跳过不重复下载；下载失败只告警不影响正文下载。
        返回封面文件路径，未下载返回 None。
        """
        cover = overview.get("cover") or {}
        urls = cover.get("urls") or {}
        cover_url = (
            urls.get("original")
            or urls.get("480mw")
            or urls.get("1200x1200")
            or urls.get("240x480")
        )
        if not cover_url:
            logger.info("Series overview has no cover image.")
            return None

        work_dir = self.build_series_output_dir(series_id)
        for existing in glob.glob(os.path.join(work_dir, "cover.*")):
            logger.info(f"Cover image already exists. Skipping download: {existing}")
            return existing

        ext = os.path.splitext(cover_url.split('?')[0])[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        cover_file = self.build_cover_file(work_dir, ext)
        logger.info(f"Downloading series cover image: {cover_url}")
        if self.download_image(cover_url, cover_file):
            logger.info(f"Cover image saved: {cover_file}")
            return cover_file
        logger.warning("Cover image download failed.")
        return None

    def request_with_retry(self, url, *, stream=False, timeout=None, purpose="request"):
        """
        发起带重试机制的 HTTP 请求。

        对临时网络波动、读取超时等问题进行有限次数重试，
        提高长篇小说和大图下载时的稳定性。
        """
        timeout = timeout or self.request_timeout
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    stream=stream,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response
            except requests_exceptions.ReadTimeout as exc:
                last_error = exc
                logger.warning( f"{purpose.capitalize()} timed out on attempt " f"{attempt}/{self.max_retries}. Retrying..." )
            except requests_exceptions.ConnectionError as exc:
                last_error = exc
                logger.warning( f"Connection error occurred during {purpose} on attempt " f"{attempt}/{self.max_retries}. Retrying..." )
            except requests_exceptions.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else "unknown"
                logger.error(f"HTTP error during {purpose}. Status code: {status_code}")
                raise
            except requests_exceptions.RequestException as exc:
                last_error = exc
                logger.warning( f"Request error occurred during {purpose} on attempt " f"{attempt}/{self.max_retries}: {exc}" )

            if attempt < self.max_retries:
                time.sleep(self.retry_delay * attempt)

        raise last_error

    def request_json(self, url, *, timeout=None, purpose="request"):
        """请求 JSON 接口并返回解析结果。"""
        response = self.request_with_retry(url, timeout=timeout, purpose=purpose)
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Invalid JSON received during {purpose}: {exc}") from exc

    # ----- 以下原为类方法，已提取为模块级纯函数；保留 thin wrapper 以维持向后兼容 -----

    def clean_filename(self, filename):
        """[已弃用] 请使用模块级 clean_filename()。"""
        return clean_filename(filename)

    def clean_html(self, raw_html):
        """[已弃用] 请使用模块级 clean_html()。"""
        return clean_html(raw_html)

    def parse_chapter_selection(self, selection_text, total_chapters):
        """[已弃用] 请使用模块级 parse_chapter_selection()。"""
        return parse_chapter_selection(selection_text, total_chapters)

    def extract_tag_names(self, tags_data):
        """[已弃用] 请使用模块级 extract_tag_names()。"""
        return extract_tag_names(tags_data)

    def update_series_catalog(self, series_id, series_title):
        """更新脚本目录下的系列 ID 与系列名对照表。"""
        csv_file = self.build_series_catalog_file()
        records = {}

        if os.path.exists(csv_file):
            with open(csv_file, 'r', encoding='utf-8') as f:
                for row in csv.reader(f):
                    if len(row) >= 2:
                        records[row[0].strip()] = row[1].strip()

        records[str(series_id).strip()] = series_title.strip()

        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            for current_series_id in sorted(records.keys(), key=lambda value: int(value) if value.isdigit() else value):
                writer.writerow([current_series_id, records[current_series_id]])

    def fetch_series_overview(self, series_id):
        """
        获取系列级别的总览信息。

        优先读取系列专用接口；若接口字段结构变化，调用方可结合章节列表结果回退补齐。
        """
        api_url = f"https://www.pixiv.net/ajax/novel/series/{series_id}?lang=zh"
        data = self.request_json(api_url, timeout=25, purpose="series overview request")
        if data.get("error"):
            raise ValueError(data.get("message") or "Failed to fetch series overview")
        return data.get("body", {}) or {}

    def save_series_info_txt(self, series_id, series_info):
        """将系列简介与元数据写入系列目录中的说明文件。"""
        info_file = self.build_series_info_file(series_id)
        tags = series_info.get("tags") or []
        tags_text = "、".join(tags) if tags else "无"

        lines = [
            f"系列ID: {series_id}",
            f"系列名称: {series_info.get('title') or '未知系列'}",
            f"作者: {series_info.get('author') or '未知作者'}",
            f"更新时间: {series_info.get('update_time') or '未知时间'}",
            f"总字数: {series_info.get('word_count') or 0}",
            f"章节数: {series_info.get('chapter_count') or 0}",
            f"标签: {tags_text}",
            "",
            "简介:",
            series_info.get('description') or "（暂无简介）",
        ]

        with open(info_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

    def _sum_word_count_from_metadata(self, metadata_file):
        """
        从 metadata.json 累加各章 word_count 作为真实总字数。

        metadata 里的 word_count 是单章详情接口 (/ajax/novel/<id>) 返回的 textCount，
        与网页显示口径一致；优先级高于 series_content 接口的累加。
        """
        if not os.path.exists(metadata_file):
            return 0
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            return 0
        total = 0
        for v in records.values():
            if isinstance(v, dict):
                wc = v.get("word_count")
                if isinstance(wc, (int, float)):
                    total += int(wc)
        return total

    def load_cookie_from_file(self, cookie_file):
        """
        从文本文件中读取 Cookie 内容。

        该方法适用于将敏感登录态从主脚本中剥离，便于代码公开发布。
        """
        if not os.path.exists(cookie_file):
            logger.warning(f"Cookie file not found: {cookie_file}")
            return ""

        with open(cookie_file, 'r', encoding='utf-8') as f:
            return f.read().strip()

    def download_image(self, img_url, save_path):
        """
        下载单张图片到本地。

        采用流式写入，避免在处理大图时一次性占用过多内存。
        """
        try:
            res = self.request_with_retry(
                img_url,
                stream=True,
                timeout=25,
                purpose="image download",
            )
            with open(save_path, 'wb') as f:
                for chunk in res.iter_content(1024):
                    if chunk:
                        f.write(chunk)
            return True
        except requests_exceptions.HTTPError:
            logger.warning("    Image download was rejected by the remote server.")
        except requests_exceptions.ReadTimeout:
            logger.warning("    Image download timed out after multiple attempts.")
        except requests_exceptions.RequestException as e:
            logger.warning(f"    Failed to download image: {e}")
        return False

    def save_to_csv(self, chapter_num, novel_id, csv_file):
        """保存或更新章节编号与小说 ID 的映射关系。"""
        with self._index_lock:
            records = {}
            if os.path.exists(csv_file):
                with open(csv_file, 'r', encoding='utf-8') as f:
                    for row in csv.reader(f):
                        if len(row) == 2:
                            try:
                                records[int(row[0])] = row[1].strip()
                            except ValueError:
                                pass

            records[int(chapter_num)] = str(novel_id).strip()
            with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                for c_num in sorted(records.keys()):
                    writer.writerow([f"{c_num:03d}", records[c_num]])

    def save_metadata(self, chapter_num, title, formatted_time, word_count, description, metadata_file):
        """
        更新元数据 JSON（唯一真值源）。

        按章节编号写入标题、时间、字数与简介；保留已有章节记录。
        """
        with self._index_lock:
            records = {}
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    try:
                        records = json.load(f)
                    except json.JSONDecodeError:
                        pass

            formatted_c_num = f"{int(chapter_num):03d}"
            records[formatted_c_num] = {
                "title": title, "time": formatted_time,
                "word_count": word_count, "desc": description if description else "（本章无简介或留言）"
            }

            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=4)

    def regenerate_summary(self, metadata_file, summary_file):
        """
        从 metadata JSON 重新生成章节简介汇总 txt。

        JSON 为唯一真值源，summary 仅作可读视图，按章节编号排序输出。
        可在外部修改 JSON 后单独调用以刷新 summary。
        """
        if not os.path.exists(metadata_file):
            return
        with open(metadata_file, 'r', encoding='utf-8') as f:
            try:
                records = json.load(f)
            except json.JSONDecodeError:
                return

        with open(summary_file, 'w', encoding='utf-8') as f:
            for c_num in sorted(records.keys()):
                d = records[c_num]
                f.write(
                    f"{c_num} {d['title']} {d['time']} 字数: {d['word_count']}\n{d['desc']}\n\n")

    def save_summary_txt(self, chapter_num, title, formatted_time, word_count, description, metadata_file, summary_file):
        """
        更新元数据 JSON 并重新生成章节简介汇总文件。

        兼容旧调用入口：内部先写 JSON 真值源，再派生 summary。
        """
        self.save_metadata(chapter_num, title, formatted_time, word_count, description, metadata_file)
        self.regenerate_summary(metadata_file, summary_file)

    def download_novel(self, novel_id, chapter_num, output_folder=None, csv_file=None, metadata_file=None, summary_file=None, force=False):
        """
        下载单章小说正文及其关联插图。

        下载完成后会同步更新 CSV 记录与章节摘要文件。
        若 force=False 且本地已存在同编号章节文件，则跳过下载以支持断点续传。
        """
        output_folder = output_folder or self.build_novel_output_dir(novel_id)
        csv_file = csv_file or self.build_record_file("novel", novel_id)
        metadata_file = metadata_file or self.build_metadata_file("novel", novel_id)
        summary_file = summary_file or self.build_summary_file("novel", novel_id)

        self.ensure_dir(output_folder)
        chapters_dir = self.build_chapters_dir(output_folder)
        img_folder = self.build_images_dir(output_folder)
        self.ensure_dir(chapters_dir)
        self.ensure_dir(img_folder)

        if not force and self.chapter_file_exists(chapters_dir, chapter_num):
            try:
                normalized_num = f"{int(chapter_num):03d}"
            except (ValueError, TypeError):
                normalized_num = str(chapter_num).strip()
            logger.info(f"Chapter {normalized_num} already exists locally. Skipping download (use --force to overwrite).")
            return True

        api_url = f"https://www.pixiv.net/ajax/novel/{novel_id}"
        logger.info(f"\nFetching novel content for chapter {chapter_num} (Novel ID: {novel_id})...")

        try:
            data = self.request_json(api_url, timeout=25, purpose="novel metadata request")
            if data.get('error'):
                logger.error(f"Failed to fetch novel metadata: {data.get('message')}")
                return False

            title = data['body']['title']
            content = data['body']['content']
            raw_description = data['body'].get('description', '')
            raw_time = data['body'].get('createDate', '未知时间')
            formatted_time = raw_time.replace(
                'T', ' ')[:19] if raw_time != '未知时间' else raw_time
            word_count = data['body'].get('textCount', len(content))
            description = clean_html(raw_description)

            # 统一处理分页标记，并准备插图保存目录。
            content = content.replace('[newpage]', '\n\n')
            # 处理作者直接上传的图片标记：[uploadedimage:xxxx]
            embedded_images = data['body'].get('textEmbeddedImages') or {}
            for img_id, img_info in embedded_images.items():
                img_url = img_info['urls']['original']
                ext = img_url.split('.')[-1]
                img_name = f"ch{chapter_num}_up_{img_id}.{ext}"

                logger.info(f"  Embedded illustration detected. Downloading: {img_name}")
                if self.download_image(img_url, os.path.join(img_folder, img_name)):
                    # 将原始标签替换为可读性更高的本地插图提示。
                    content = content.replace(
                        f"[uploadedimage:{img_id}]", f"\n\n【插图: {img_name}】\n\n")

            # 处理站内插图引用标签：[pixivimage:xxxx]
            pixiv_imgs = re.findall(r'\[pixivimage:(\d+)\]', content)
            for pid in pixiv_imgs:
                logger.info(f"  Referenced Pixiv illustration detected. Resolving ID: {pid}...")
                ill_api = f"https://www.pixiv.net/ajax/illust/{pid}"
                try:
                    ill_res = self.request_json(ill_api, timeout=20, purpose="illustration metadata request")
                except requests_exceptions.RequestException as e:
                    logger.warning(f"    Failed to resolve referenced illustration metadata: {e}")
                    content = content.replace(
                        f"[pixivimage:{pid}]",
                        f"\n\n【插图获取失败: 原图 {pid} 请求超时或网络异常】\n\n",
                    )
                    continue
                except ValueError as e:
                    logger.warning(f"    Failed to parse referenced illustration metadata: {e}")
                    content = content.replace(
                        f"[pixivimage:{pid}]",
                        f"\n\n【插图获取失败: 原图 {pid} 返回数据异常】\n\n",
                    )
                    continue

                if not ill_res.get('error'):
                    img_url = ill_res['body']['urls']['original']
                    ext = img_url.split('.')[-1]
                    img_name = f"ch{chapter_num}_pid_{pid}.{ext}"

                    if self.download_image(img_url, os.path.join(img_folder, img_name)):
                        content = content.replace(
                            f"[pixivimage:{pid}]", f"\n\n【插图: {img_name}】\n\n")
                else:
                    logger.warning("    Failed to resolve referenced illustration. The original image may have been removed.")
                    content = content.replace(
                        f"[pixivimage:{pid}]", f"\n\n【插图失效: 原图 {pid} 已删除】\n\n")

            safe_title = clean_filename(title)
            filepath = os.path.join(
                chapters_dir, f"{chapter_num} {safe_title}.txt")

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"Chapter content saved successfully: {filepath}")
            self.save_to_csv(chapter_num, novel_id, csv_file)
            self.save_summary_txt(
                chapter_num, title, formatted_time, word_count, description, metadata_file, summary_file)
            # 实际下载完成的章节间限速；跳过路径在前面 early return，不会触发。
            time.sleep(self.chapter_delay)
            return True

        except requests_exceptions.ReadTimeout:
            logger.error( "The novel request timed out after multiple attempts. " "This chapter may be temporarily unavailable or responding too slowly." )
            return False
        except requests_exceptions.RequestException as e:
            logger.error(f"A network request failed while downloading the chapter: {e}")
            return False
        except ValueError as e:
            logger.error(f"Failed to parse API response while downloading the chapter: {e}")
            return False
        except Exception as e:
            logger.error(f"A network or parsing error occurred while downloading the chapter: {e}")
            return False

    def download_from_csv(self, csv_file, force=False):
        """根据指定 CSV 记录批量下载章节。"""
        if not os.path.exists(csv_file):
            logger.warning(f"CSV record file not found: {csv_file}. Please create it first.")
            return

        logger.info("\nStarting batch download from CSV records...")
        success_count, total_count = 0, 0

        # 先读所有行再统一进入进度条，避免边读边改 total 闪烁。
        with open(csv_file, 'r', encoding='utf-8') as f:
            rows = [row for row in csv.reader(f) if len(row) == 2]

        for row in tqdm(rows, desc="CSV batch", unit="chap"):
            total_count += 1
            novel_id = row[1].strip()
            chapter_num = row[0].strip()
            output_folder = self.build_novel_output_dir(novel_id)
            target_csv = self.build_record_file("novel", novel_id)
            target_metadata = self.build_metadata_file("novel", novel_id)
            target_summary = self.build_summary_file("novel", novel_id)
            if self.download_novel(
                novel_id,
                chapter_num,
                output_folder=output_folder,
                csv_file=target_csv,
                metadata_file=target_metadata,
                summary_file=target_summary,
                force=force,
            ):
                success_count += 1
        logger.info(f"\nBatch download completed. Successful chapters: {success_count}/{total_count}.")

    def find_missing_chapters(self, scope, target_id):
        """
        扫描指定作品（novel 或 series）目录下的 records.csv，
        对每条记录比对 chapters/ 中的 txt 文件，返回缺失章节列表。

        返回：[(chapter_num, novel_id), ...]，无缺失时返回空列表。
        """
        work_dir = (self.build_novel_output_dir(target_id) if scope == "novel"
                    else self.build_series_output_dir(target_id))
        csv_file = self.build_record_file(scope, target_id)
        if not os.path.exists(csv_file):
            logger.warning(f"Records CSV not found: {csv_file}")
            return []

        chapters_dir = self.build_chapters_dir(work_dir)
        missing = []
        with open(csv_file, 'r', encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) != 2:
                    continue
                chapter_num, novel_id = row[0].strip(), row[1].strip()
                if not self.chapter_file_exists(chapters_dir, chapter_num):
                    missing.append((chapter_num, novel_id))
        return missing

    def download_missing(self, scope, target_id, force=False):
        """
        根据现有 records.csv 扫描缺失的章节并重新下载，支持一键补跑。

        不会覆盖已下载成功的章节（除非 force=True）。
        """
        work_dir = (self.build_novel_output_dir(target_id) if scope in ("novel", "single")
                    else self.build_series_output_dir(target_id))
        csv_file = self.build_record_file(scope, target_id)
        metadata_file = self.build_metadata_file(scope, target_id)
        summary_file = self.build_summary_file(scope, target_id)

        missing = self.find_missing_chapters(scope, target_id)
        if not missing:
            logger.info(f"[INFO] No missing chapters detected for {scope} {target_id}. Nothing to retry.")
            return

        logger.info(f"[INFO] Found {len(missing)} missing chapter(s). Starting retry...")
        success = 0
        for chapter_num, novel_id in tqdm(missing, desc="Retry", unit="chap"):
            if self.download_novel(
                novel_id,
                chapter_num,
                output_folder=work_dir,
                csv_file=csv_file,
                metadata_file=metadata_file,
                summary_file=summary_file,
                force=force,
            ):
                success += 1
            # 章节间限速已下沉到 download_novel 的成功路径，跳过章节不占用时间。

        logger.info(f"[INFO] Retry completed. Recovered chapters: {success}/{len(missing)}.")
        still_missing = [c for c, _ in missing
                         if not self.chapter_file_exists(self.build_chapters_dir(work_dir), c)]
        if still_missing:
            logger.warning(f"[WARN] Still missing: {', '.join(still_missing)}")

    def download_series(self, series_id, start_chapter=1, only_update_csv=False, chapter_selection="", force=False, workers=1):
        """
        根据系列 ID 获取所有章节，并按需执行下载或仅更新目录。

        说明:
            - Pixiv 系列接口单次最多返回 30 条记录。
            - 通过 last_order 分页可稳定遍历完整系列目录。
            - only_update_csv=True 时，仅更新章节索引，不下载正文。
            - chapter_selection 可指定单章或章节区间，例如 11 或 11-21。
        - workers 控制正文并发下载数；默认 1 串行（旧行为），>1 时启用线程池但仍按章限速以防风控。
        """
        logger.info(f"\nResolving Pixiv series metadata (Series ID: {series_id})...")
        output_folder = self.build_series_output_dir(series_id)
        csv_file = self.build_record_file("series", series_id)
        metadata_file = self.build_metadata_file("series", series_id)
        summary_file = self.build_summary_file("series", series_id)

        self.ensure_dir(output_folder)
        series_title = f"series_{series_id}"
        series_author = ""
        series_description = ""
        series_update_time = ""
        series_tags = []

        chapter_ids = []
        chapter_word_count = 0
        limit = 30
        last_order = 0

        try:
            overview = self.fetch_series_overview(series_id)
            series_title = (
                overview.get("title")
                or overview.get("seriesTitle")
                or overview.get("name")
                or series_title
            )
            series_author = (
                overview.get("userName")
                or overview.get("authorName")
                or overview.get("user", {}).get("name")
                or ""
            )
            series_description = clean_html(
                overview.get("caption")
                or overview.get("description")
                or overview.get("content")
                or ""
            )
            series_update_time = (
                overview.get("updateDate")
                or overview.get("createDate")
                or overview.get("publishedDate")
                or ""
            )
            series_tags = extract_tag_names(overview.get("tags"))
            # 系列封面：下载到系列目录（失败不影响正文流程）
            try:
                self.download_series_cover(series_id, overview)
            except Exception as e:
                logger.warning(f"Cover download error: {e}")
        except (requests_exceptions.RequestException, ValueError) as e:
            logger.warning(f"Failed to fetch standalone series overview. Falling back to chapter list metadata: {e}")

        while True:
            api_url = f"https://www.pixiv.net/ajax/novel/series_content/{series_id}?limit={limit}&last_order={last_order}&order_by=asc&lang=zh"

            try:
                data = self.request_json(api_url, timeout=25, purpose="series metadata request")

                if data.get('error'):
                    logger.error(f"Failed to resolve series metadata: {data.get('message')}")
                    return False

                # 兼容两种可能的返回结构，保证旧接口或变体结构都能正常处理。
                contents = data.get('body', {}).get('seriesContents', [])
                if not contents:
                    contents = data.get('body', {}).get('page', {}).get('seriesContents', [])

                if not contents:
                    break

                for item in contents:
                    chapter_ids.append(item['id'])
                    chapter_word_count += item.get('textCount') or item.get('wordCount') or 0

                if contents and series_title == f"series_{series_id}":
                    first_item = contents[0]
                    series_title = (
                        data.get('body', {}).get('title')
                        or data.get('body', {}).get('seriesTitle')
                        or data.get('body', {}).get('name')
                        or first_item.get('seriesTitle')
                        or first_item.get('title')
                        or series_title
                    )
                    series_author = (
                        series_author
                        or first_item.get('userName')
                        or first_item.get('authorName')
                        or ""
                    )
                    if not series_update_time:
                        series_update_time = (
                            first_item.get('updateDate')
                            or first_item.get('createDate')
                            or ""
                        )
                    if not series_tags:
                        series_tags = extract_tag_names(first_item.get('tags'))
                    if not series_description:
                        series_description = clean_html(
                            data.get('body', {}).get('caption')
                            or data.get('body', {}).get('description')
                            or ""
                        )

                if len(contents) < limit:
                    break

                # 使用接口返回的真实排序位置，避免翻页时出现漏章或重复。
                last_item_order = contents[-1].get('order')
                if last_item_order is not None:
                    last_order = last_item_order
                else:
                    last_order += limit

            except requests_exceptions.ReadTimeout:
                logger.error("Series metadata request timed out after multiple attempts.")
                return False
            except requests_exceptions.RequestException as e:
                logger.error(f"A network error occurred while fetching series data: {e}")
                return False
            except ValueError as e:
                logger.error(f"Failed to parse series metadata response: {e}")
                return False

        total_chapters = len(chapter_ids)
        logger.info(f"Series resolved successfully. Total chapters found: {total_chapters}.")

        if total_chapters == 0:
            logger.warning("No chapters were found. Please verify the series ID and cookie validity.")
            return

        try:
            selected_positions = parse_chapter_selection(chapter_selection, total_chapters)
        except ValueError as e:
            logger.warning(f"{e}")
            return False

        selected_chapter_ids = [chapter_ids[position - 1] for position in selected_positions]

        if series_update_time:
            series_update_time = series_update_time.replace('T', ' ')[:19]

        self.update_series_catalog(series_id, series_title)
        self.save_series_info_txt(
            series_id,
            {
                "title": series_title,
                "author": series_author,
                "description": series_description,
                "update_time": series_update_time,
                "word_count": chapter_word_count,
                "chapter_count": total_chapters,
                "tags": series_tags,
            },
        )

        if only_update_csv:
            logger.info(f"Updating chapter index records in {csv_file}...")
        else:
            logger.info("Starting full series download pipeline...")

        # 预先生成待处理任务清单（章号 + novel_id），便于并发执行；
        # only_update_csv 路径无需并发，仍串行写索引即可。
        use_original_chapter_numbers = bool((chapter_selection or "").strip())
        current_chapter_num = int(start_chapter)
        tasks = []
        for offset, n_id in enumerate(selected_chapter_ids):
            actual_position = selected_positions[offset]
            save_chapter_num = actual_position if use_original_chapter_numbers else current_chapter_num
            formatted_num = f"{save_chapter_num:03d}"
            tasks.append((formatted_num, n_id))
            if not use_original_chapter_numbers:
                current_chapter_num += 1

        success_count = 0

        def _process(task):
            fmt_num, n_id = task
            if only_update_csv:
                self.save_to_csv(fmt_num, n_id, csv_file)
                return True
            ok = self.download_novel(
                str(n_id),
                fmt_num,
                output_folder=output_folder,
                csv_file=csv_file,
                metadata_file=metadata_file,
                summary_file=summary_file,
                force=force,
            )
            # 章节间限速已下沉到 download_novel 的成功路径；
            # workers>1 时由线程池本身 + 章节内 sleep 共同节流。
            return ok

        iterator = tqdm(tasks, desc="Series", unit="chap")
        if only_update_csv or workers <= 1:
            for task in iterator:
                if _process(task):
                    success_count += 1
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_process, task): task for task in tasks}
                for future in tqdm(as_completed(futures), total=len(futures),
                                   desc=f"Series(x{workers})", unit="chap"):
                    if future.result():
                        success_count += 1

        if only_update_csv:
            logger.info(f"\nChapter index update completed. Records written: {success_count}. Output file: {csv_file}.")
        else:
            logger.info(f"\nFull series download completed. Success rate: {success_count}/{len(selected_chapter_ids)}.")

        # 修正总字数：从已下载各章的 metadata.json 累加真实字数。
        # 系列分页接口（series_content）的 textCount 与单章详情接口的 textCount 统计口径不同，
        # 通常前者偏小、与网页显示值不符；优先使用 metadata 里单章详情接口的字数累加。
        real_word_count = self._sum_word_count_from_metadata(metadata_file)
        if real_word_count > 0 and real_word_count != chapter_word_count:
            logger.info(
                f" Corrected total word count: {real_word_count} (from metadata) "
                f"instead of {chapter_word_count} (from series_content API)."
            )
            chapter_word_count = real_word_count
            self.save_series_info_txt(
                series_id,
                {
                    "title": series_title,
                    "author": series_author,
                    "description": series_description,
                    "update_time": series_update_time,
                    "word_count": chapter_word_count,
                    "chapter_count": total_chapters,
                    "tags": series_tags,
                },
            )

        return True


if __name__ == "__main__":
    # 库文件不直接包含交互逻辑，交由 cli.py 统一入口处理（懒导入避免循环依赖）。
    # 直接运行 `python pixiv_novel_scraper.py` 与 `python cli.py` 行为一致。
    from cli import main
    main()
