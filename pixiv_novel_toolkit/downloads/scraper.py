"""Pixiv 下载器兼容类的正式包实现。"""

import logging
import os
from pathlib import Path
import threading
import time

import requests
from requests import exceptions as requests_exceptions

from pixiv_novel_toolkit.downloads import (
    build_chapters_dir as make_chapters_dir,
    build_cover_file as make_cover_file,
    build_images_dir as make_images_dir,
    build_metadata_file as make_metadata_file,
    build_novel_output_dir as make_novel_output_dir,
    build_record_file as make_record_file,
    build_series_catalog_file as make_series_catalog_file,
    build_series_info_file as make_series_info_file,
    build_series_output_dir as make_series_output_dir,
    build_series_tasks,
    build_summary_file as make_summary_file,
    chapter_file_exists as has_chapter_file,
    build_request_headers,
    clean_filename,
    clean_html,
    DEFAULT_CHAPTER_DELAY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRY_DELAY,
    decode_json_response,
    extract_tag_names,
    ensure_directory,
    execute_batch_tasks,
    execute_series_tasks,
    fetch_and_save_novel,
    fetch_series_catalog,
    fetch_series_overview as request_series_overview,
    find_missing_records,
    initial_series_metadata,
    load_cookie_file,
    load_record_rows,
    normalize_chapter_number,
    normalize_series_update_time,
    NovelApiError,
    parse_chapter_selection,
    parse_pixiv_novel_id,
    parse_pixiv_series_id,
    parse_series_overview,
    regenerate_summary,
    record_rows_to_tasks,
    render_series_info,
    request_with_retry as perform_request_with_retry,
    save_chapter_record,
    save_metadata_record,
    save_series_cover,
    SeriesApiError,
    sum_word_count_from_metadata,
    update_series_catalog,
    unresolved_chapter_numbers,
    write_stream_response,
)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable=None, **kwargs):
        return iterable if iterable is not None else iter(())


logger = logging.getLogger("pixiv_novel_toolkit")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        self.base_dir = base_dir or str(PROJECT_ROOT)
        self.novels_dir = os.path.join(self.base_dir, "novels")
        self.series_dir = os.path.join(self.base_dir, "series")
        self.request_timeout = DEFAULT_REQUEST_TIMEOUT
        self.max_retries = DEFAULT_MAX_RETRIES
        self.retry_delay = DEFAULT_RETRY_DELAY
        # 每个章节实际下载完成后的延迟，降低连续请求触发风控的概率；
        # 仅在真正发起网络请求时生效，跳过已存在章节时不会占用时间。
        self.chapter_delay = DEFAULT_CHAPTER_DELAY
        # 索引文件并发写入时的互斥锁（workers>1 时启用）。
        self._index_lock = threading.Lock()

        self.ensure_dir(self.novels_dir)
        self.ensure_dir(self.series_dir)

        self.headers = build_request_headers(self.cookie)

    def ensure_dir(self, path):
        """确保指定目录存在。"""
        ensure_directory(path)

    def chapter_file_exists(self, chapters_dir, chapter_num):
        """
        检查指定章节编号对应的正文 txt 是否已存在。

        不依赖标题，仅按编号前缀匹配（如 "011 xxx.txt"），便于在请求 API 之前就跳过。
        """
        return has_chapter_file(chapters_dir, chapter_num)

    def build_novel_output_dir(self, novel_id):
        """返回单章小说的输出目录。"""
        return make_novel_output_dir(self.novels_dir, novel_id)

    def build_series_output_dir(self, series_id):
        """返回系列小说的输出目录。"""
        return make_series_output_dir(self.series_dir, series_id)

    def build_chapters_dir(self, work_dir):
        """返回正文章节文件所在目录。"""
        return make_chapters_dir(work_dir)

    def build_images_dir(self, work_dir):
        """返回插图目录。优先沿用已存在的旧中文目录名以保持兼容。"""
        return make_images_dir(work_dir)

    def build_record_file(self, scope, target_id):
        """返回 CSV 记录文件路径。"""
        return make_record_file(self.novels_dir, self.series_dir, scope, target_id)

    def build_metadata_file(self, scope, target_id):
        """返回 JSON 元数据文件路径。"""
        return make_metadata_file(self.novels_dir, self.series_dir, scope, target_id)

    def build_summary_file(self, scope, target_id):
        """返回章节简介汇总文件路径。"""
        return make_summary_file(self.novels_dir, self.series_dir, scope, target_id)

    def build_series_catalog_file(self):
        """返回系列名称对照表文件路径。存放于 series 目录下，与作品数据集中管理。"""
        return make_series_catalog_file(self.series_dir)

    def build_series_info_file(self, series_id):
        """返回系列信息说明文件路径。"""
        return make_series_info_file(self.series_dir, series_id)

    def build_cover_file(self, work_dir, ext=".jpg"):
        """返回封面图片文件路径（系列目录下 cover.<ext>）。"""
        return make_cover_file(work_dir, ext)

    def download_series_cover(self, series_id, overview):
        """
        从系列总览信息下载封面图到系列目录（cover.<ext>）。

        cover 字段结构: overview['cover']['urls'] = {"original": "...", "480mw": "..."}。
        已存在 cover.* 时跳过不重复下载；下载失败只告警不影响正文下载。
        返回封面文件路径，未下载返回 None。
        """
        work_dir = self.build_series_output_dir(series_id)
        return save_series_cover(
            overview,
            work_dir,
            self.download_image,
            build_cover_path=self.build_cover_file,
            log=logger,
        )

    def request_with_retry(self, url, *, stream=False, timeout=None, purpose="request"):
        """
        发起带重试机制的 HTTP 请求。

        对临时网络波动、读取超时等问题进行有限次数重试，
        提高长篇小说和大图下载时的稳定性。
        """
        return perform_request_with_retry(
            url,
            headers=self.headers,
            stream=stream,
            timeout=timeout or self.request_timeout,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            purpose=purpose,
            request_get=requests.get,
            sleep=time.sleep,
            log=logger,
        )

    def request_json(self, url, *, timeout=None, purpose="request"):
        """请求 JSON 接口并返回解析结果。"""
        response = self.request_with_retry(url, timeout=timeout, purpose=purpose)
        return decode_json_response(response, purpose)

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
        update_series_catalog(self.build_series_catalog_file(), series_id, series_title)

    def fetch_series_overview(self, series_id):
        """
        获取系列级别的总览信息。

        优先读取系列专用接口；若接口字段结构变化，调用方可结合章节列表结果回退补齐。
        """
        return request_series_overview(series_id, self.request_json)

    def save_series_info_txt(self, series_id, series_info):
        """将系列简介与元数据写入系列目录中的说明文件。"""
        info_file = self.build_series_info_file(series_id)
        with open(info_file, 'w', encoding='utf-8') as f:
            f.write(render_series_info(series_id, series_info))

    def _sum_word_count_from_metadata(self, metadata_file):
        """
        从 metadata.json 累加各章 word_count 作为真实总字数。

        metadata 里的 word_count 是单章详情接口 (/ajax/novel/<id>) 返回的 textCount，
        与网页显示口径一致；优先级高于 series_content 接口的累加。
        """
        return sum_word_count_from_metadata(metadata_file)

    def load_cookie_from_file(self, cookie_file):
        """
        从文本文件中读取 Cookie 内容。

        该方法适用于将敏感登录态从主脚本中剥离，便于代码公开发布。
        """
        return load_cookie_file(cookie_file, warn=logger.warning)

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
            write_stream_response(res, save_path)
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
            save_chapter_record(chapter_num, novel_id, csv_file)

    def save_metadata(self, chapter_num, title, formatted_time, word_count, description, metadata_file):
        """
        更新元数据 JSON（唯一真值源）。

        按章节编号写入标题、时间、字数与简介；保留已有章节记录。
        """
        with self._index_lock:
            save_metadata_record(
                chapter_num,
                title,
                formatted_time,
                word_count,
                description,
                metadata_file,
            )

    def regenerate_summary(self, metadata_file, summary_file):
        """
        从 metadata JSON 重新生成章节简介汇总 txt。

        JSON 为唯一真值源，summary 仅作可读视图，按章节编号排序输出。
        可在外部修改 JSON 后单独调用以刷新 summary。
        """
        regenerate_summary(metadata_file, summary_file)

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
        try:
            novel_id = parse_pixiv_novel_id(novel_id)
        except ValueError as e:
            logger.error(str(e))
            return False

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
            normalized_num = normalize_chapter_number(chapter_num)
            logger.info(f"Chapter {normalized_num} already exists locally. Skipping download (use --force to overwrite).")
            return True

        logger.info(f"\nFetching novel content for chapter {chapter_num} (Novel ID: {novel_id})...")

        try:
            novel = fetch_and_save_novel(
                novel_id,
                chapter_num,
                chapters_dir,
                img_folder,
                self.request_json,
                self.download_image,
                log=logger,
            )
            logger.info(f"Chapter content saved successfully: {novel.filepath}")
            self.save_to_csv(chapter_num, novel_id, csv_file)
            self.save_summary_txt(
                chapter_num,
                novel.title,
                novel.formatted_time,
                novel.word_count,
                novel.description,
                metadata_file,
                summary_file,
            )
            # 实际下载完成的章节间限速；跳过路径在前面 early return，不会触发。
            time.sleep(self.chapter_delay)
            return True

        except NovelApiError as e:
            logger.error(f"Failed to fetch novel metadata: {e}")
            return False
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
        # 先读所有行再统一进入进度条，避免边读边改 total 闪烁。
        tasks = record_rows_to_tasks(load_record_rows(csv_file))

        def _process(task):
            chapter_num, novel_id = task
            output_folder = self.build_novel_output_dir(novel_id)
            target_csv = self.build_record_file("novel", novel_id)
            target_metadata = self.build_metadata_file("novel", novel_id)
            target_summary = self.build_summary_file("novel", novel_id)
            return self.download_novel(
                novel_id,
                chapter_num,
                output_folder=output_folder,
                csv_file=target_csv,
                metadata_file=target_metadata,
                summary_file=target_summary,
                force=force,
            )

        result = execute_batch_tasks(
            tasks,
            _process,
            progress=tqdm,
            desc="CSV batch",
        )
        logger.info(
            f"\nBatch download completed. Successful chapters: "
            f"{result.successful}/{result.total}."
        )

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
        tasks = record_rows_to_tasks(load_record_rows(csv_file))
        return find_missing_records(
            tasks,
            lambda chapter_num: self.chapter_file_exists(chapters_dir, chapter_num),
        )

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

        def _process(task):
            chapter_num, novel_id = task
            return self.download_novel(
                novel_id,
                chapter_num,
                output_folder=work_dir,
                csv_file=csv_file,
                metadata_file=metadata_file,
                summary_file=summary_file,
                force=force,
            )

        result = execute_batch_tasks(
            missing,
            _process,
            progress=tqdm,
            desc="Retry",
        )

        logger.info(
            f"[INFO] Retry completed. Recovered chapters: "
            f"{result.successful}/{result.total}."
        )
        chapters_dir = self.build_chapters_dir(work_dir)
        still_missing = unresolved_chapter_numbers(
            missing,
            lambda chapter_num: self.chapter_file_exists(chapters_dir, chapter_num),
        )
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
        try:
            series_id = parse_pixiv_series_id(series_id)
        except ValueError as e:
            logger.error(str(e))
            return False

        logger.info(f"\nResolving Pixiv series metadata (Series ID: {series_id})...")
        output_folder = self.build_series_output_dir(series_id)
        csv_file = self.build_record_file("series", series_id)
        metadata_file = self.build_metadata_file("series", series_id)
        summary_file = self.build_summary_file("series", series_id)

        self.ensure_dir(output_folder)
        series_info = initial_series_metadata(series_id)

        try:
            overview = self.fetch_series_overview(series_id)
            series_info = parse_series_overview(overview, series_id)
            # 系列封面：下载到系列目录（失败不影响正文流程）
            try:
                self.download_series_cover(series_id, overview)
            except Exception as e:
                logger.warning(f"Cover download error: {e}")
        except (requests_exceptions.RequestException, ValueError) as e:
            logger.warning(f"Failed to fetch standalone series overview. Falling back to chapter list metadata: {e}")

        try:
            catalog = fetch_series_catalog(series_id, self.request_json, series_info)
        except SeriesApiError as e:
            logger.error(f"Failed to resolve series metadata: {e}")
            return False
        except requests_exceptions.ReadTimeout:
            logger.error("Series metadata request timed out after multiple attempts.")
            return False
        except requests_exceptions.RequestException as e:
            logger.error(f"A network error occurred while fetching series data: {e}")
            return False
        except ValueError as e:
            logger.error(f"Failed to parse series metadata response: {e}")
            return False

        chapter_ids = catalog.chapter_ids
        chapter_word_count = catalog.word_count
        series_info = catalog.metadata

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

        series_info["update_time"] = normalize_series_update_time(
            series_info.get("update_time")
        )
        series_info["word_count"] = chapter_word_count
        series_info["chapter_count"] = total_chapters

        self.update_series_catalog(series_id, series_info["title"])
        self.save_series_info_txt(series_id, series_info)

        if only_update_csv:
            logger.info(f"Updating chapter index records in {csv_file}...")
        else:
            logger.info("Starting full series download pipeline...")

        # 预先生成待处理任务清单（章号 + novel_id），便于并发执行；
        # only_update_csv 路径无需并发，仍串行写索引即可。
        use_original_chapter_numbers = bool((chapter_selection or "").strip())
        tasks = build_series_tasks(
            selected_chapter_ids,
            selected_positions,
            start_chapter,
            preserve_positions=use_original_chapter_numbers,
        )

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

        success_count = execute_series_tasks(
            tasks,
            _process,
            workers=workers,
            index_only=only_update_csv,
            progress=tqdm,
        )

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
            series_info["word_count"] = chapter_word_count
            self.save_series_info_txt(series_id, series_info)

        return True
