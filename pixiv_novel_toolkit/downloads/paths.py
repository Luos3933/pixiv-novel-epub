"""下载产物的目录、文件名和兼容路径规则。"""

import glob
import os


def ensure_directory(path):
    """确保目录存在。"""
    os.makedirs(path, exist_ok=True)


def normalize_chapter_number(chapter_num):
    """将可转换的章节号补齐为三位，否则保留清理后的原值。"""
    try:
        return f"{int(chapter_num):03d}"
    except (ValueError, TypeError):
        return str(chapter_num).strip()


def chapter_file_exists(chapters_dir, chapter_num):
    """仅按章节数字前缀检查正文文件是否存在。"""
    normalized_num = normalize_chapter_number(chapter_num)
    return bool(glob.glob(os.path.join(chapters_dir, f"{normalized_num} *.txt")))


def build_novel_output_dir(novels_dir, novel_id):
    return os.path.join(novels_dir, f"novel_{novel_id}")


def build_series_output_dir(series_dir, series_id):
    return os.path.join(series_dir, f"series_{series_id}")


def build_chapters_dir(work_dir):
    return os.path.join(work_dir, "chapters")


def build_images_dir(work_dir):
    """优先沿用已存在的旧中文插图库目录。"""
    legacy_dir = os.path.join(work_dir, "插图库")
    if os.path.isdir(legacy_dir):
        return legacy_dir
    return os.path.join(work_dir, "illustrations")


def build_scope_output_dir(novels_dir, series_dir, scope, target_id):
    """沿用旧规则：仅 novel 使用单章目录，其余 scope 使用系列目录。"""
    if scope == "novel":
        return build_novel_output_dir(novels_dir, target_id)
    return build_series_output_dir(series_dir, target_id)


def build_record_file(novels_dir, series_dir, scope, target_id):
    work_dir = build_scope_output_dir(novels_dir, series_dir, scope, target_id)
    return os.path.join(work_dir, f"{scope}_{target_id}_records.csv")


def build_metadata_file(novels_dir, series_dir, scope, target_id):
    work_dir = build_scope_output_dir(novels_dir, series_dir, scope, target_id)
    return os.path.join(work_dir, f"{scope}_{target_id}_metadata.json")


def build_summary_file(novels_dir, series_dir, scope, target_id):
    work_dir = build_scope_output_dir(novels_dir, series_dir, scope, target_id)
    return os.path.join(work_dir, f"{scope}_{target_id}_summary.txt")


def build_series_catalog_file(series_dir):
    return os.path.join(series_dir, "_catalog.csv")


def build_series_info_file(series_dir, series_id):
    work_dir = build_series_output_dir(series_dir, series_id)
    return os.path.join(work_dir, f"series_{series_id}_info.txt")


def build_cover_file(work_dir, extension=".jpg"):
    return os.path.join(work_dir, f"cover{extension}")


def find_existing_cover(work_dir):
    """返回工作目录中首个现有 cover.*，没有则返回 None。"""
    return next(iter(glob.glob(os.path.join(work_dir, "cover.*"))), None)
