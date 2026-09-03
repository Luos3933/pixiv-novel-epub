"""下载索引的 CSV/JSON 持久化与派生摘要生成。"""

import csv
import json
import os


def load_record_rows(csv_file):
    """读取两列章节记录，跳过格式不完整的行。"""
    if not os.path.exists(csv_file):
        return []
    with open(csv_file, "r", encoding="utf-8") as file_obj:
        return [row for row in csv.reader(file_obj) if len(row) == 2]


def save_chapter_record(chapter_num, novel_id, csv_file):
    """写入章节号到小说 ID 的映射，并按数字章节号排序。"""
    records = {}
    if os.path.exists(csv_file):
        with open(csv_file, "r", encoding="utf-8") as file_obj:
            for row in csv.reader(file_obj):
                if len(row) == 2:
                    try:
                        records[int(row[0])] = row[1].strip()
                    except ValueError:
                        pass

    records[int(chapter_num)] = str(novel_id).strip()
    with open(csv_file, "w", encoding="utf-8", newline="") as file_obj:
        writer = csv.writer(file_obj)
        for current_num in sorted(records):
            writer.writerow([f"{current_num:03d}", records[current_num]])


def save_metadata_record(
    chapter_num,
    title,
    formatted_time,
    word_count,
    description,
    metadata_file,
):
    """更新单章 metadata 记录，同时保留同文件中的已有章节。"""
    records = {}
    if os.path.exists(metadata_file):
        with open(metadata_file, "r", encoding="utf-8") as file_obj:
            try:
                records = json.load(file_obj)
            except json.JSONDecodeError:
                pass

    formatted_num = f"{int(chapter_num):03d}"
    records[formatted_num] = {
        "title": title,
        "time": formatted_time,
        "word_count": word_count,
        "desc": description if description else "（本章无简介或留言）",
    }
    with open(metadata_file, "w", encoding="utf-8") as file_obj:
        json.dump(records, file_obj, ensure_ascii=False, indent=4)


def regenerate_summary(metadata_file, summary_file):
    """从 metadata 真值源重新生成按章节号排序的可读摘要。"""
    if not os.path.exists(metadata_file):
        return
    with open(metadata_file, "r", encoding="utf-8") as file_obj:
        try:
            records = json.load(file_obj)
        except json.JSONDecodeError:
            return

    with open(summary_file, "w", encoding="utf-8") as file_obj:
        for chapter_num in sorted(records):
            data = records[chapter_num]
            file_obj.write(
                f"{chapter_num} {data['title']} {data['time']} "
                f"字数: {data['word_count']}\n{data['desc']}\n\n"
            )


def sum_word_count_from_metadata(metadata_file):
    """累加 metadata 中有效的单章 word_count，读取失败时返回 0。"""
    if not os.path.exists(metadata_file):
        return 0
    try:
        with open(metadata_file, "r", encoding="utf-8") as file_obj:
            records = json.load(file_obj)
    except (json.JSONDecodeError, OSError):
        return 0

    total = 0
    for value in records.values():
        if isinstance(value, dict):
            word_count = value.get("word_count")
            if isinstance(word_count, (int, float)):
                total += int(word_count)
    return total


def update_series_catalog(csv_file, series_id, series_title):
    """更新系列 ID 与名称对照表，并保持可预测的 ID 排序。"""
    records = {}
    if os.path.exists(csv_file):
        with open(csv_file, "r", encoding="utf-8") as file_obj:
            for row in csv.reader(file_obj):
                if len(row) >= 2:
                    records[row[0].strip()] = row[1].strip()

    records[str(series_id).strip()] = series_title.strip()
    with open(csv_file, "w", encoding="utf-8", newline="") as file_obj:
        writer = csv.writer(file_obj)
        for current_id in sorted(
            records, key=lambda value: int(value) if value.isdigit() else value
        ):
            writer.writerow([current_id, records[current_id]])
