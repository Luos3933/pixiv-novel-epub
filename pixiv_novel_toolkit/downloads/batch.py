"""CSV 批量下载与缺失章节重试使用的共享任务逻辑。"""

from dataclasses import dataclass


@dataclass
class BatchResult:
    """一批串行任务的总数与成功数。"""

    total: int
    successful: int


def record_rows_to_tasks(rows):
    """把两列 CSV 行标准化为 ``(章节号, novel_id)`` 任务。"""
    return [(row[0].strip(), row[1].strip()) for row in rows]


def find_missing_records(tasks, chapter_exists):
    """依据调用方提供的章节存在性判断筛出缺失任务。"""
    return [task for task in tasks if not chapter_exists(task[0])]


def execute_batch_tasks(tasks, process_task, *, progress=None, desc="Batch"):
    """按原始顺序串行执行任务，并统计返回真值的任务。"""
    iterator = progress(tasks, desc=desc, unit="chap") if progress else tasks
    successful = sum(1 for task in iterator if process_task(task))
    return BatchResult(total=len(tasks), successful=successful)


def unresolved_chapter_numbers(tasks, chapter_exists):
    """返回执行后仍缺失的章节号。"""
    return [chapter_num for chapter_num, _ in tasks if not chapter_exists(chapter_num)]
