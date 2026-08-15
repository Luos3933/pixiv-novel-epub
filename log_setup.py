"""
共享日志配置：固定文件名 + 按大小轮转归档。

设计:
  - 每个职责（下载 / 后处理）对应一个固定文件名: logs/download.log, logs/postprocess.log
  - 每次运行追加写入，文件顶部加 "===== <时间戳> =====" 作为会话分隔
  - 启动时若文件已超过 max_bytes（默认 1 MB），先归档为
    logs/archive/<base>_<YYYYMMDD_HHMMSS>.log 再开新文件
  - 历史归档保留在 logs/archive/ 下按时间戳命名，便于事后追溯且不杂乱
  - 控制台走 TqdmLoggingHandler，不与 tqdm 进度条互相打断
"""

import logging
import os
import shutil
from datetime import datetime


class TqdmLoggingHandler(logging.Handler):
    """
    使用 tqdm.write 输出日志，避免直接 print 把进度条打断成多行重绘。
    无 tqdm 时回退到 print，仍能正常输出。
    """

    def __init__(self):
        super().__init__()
        try:
            from tqdm import tqdm
            self._write = tqdm.write
        except ImportError:
            import builtins
            self._write = builtins.print

    def emit(self, record):
        try:
            self._write(self.format(record))
        except Exception:
            self.handleError(record)


def _archive_if_needed(log_file, max_bytes):
    """
    若 log_file 已存在且大小超过 max_bytes，移到 logs/archive/<base>_<时间戳>.log。
    归档目录不存在会自动创建。返回最终生效的 log_file 路径（不变）。
    """
    if not os.path.isfile(log_file):
        return log_file
    if os.path.getsize(log_file) < max_bytes:
        return log_file

    archive_dir = os.path.join(os.path.dirname(log_file), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    base = os.path.basename(log_file)[:-len(".log")] if log_file.endswith(".log") else os.path.basename(log_file)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(archive_dir, f"{base}_{timestamp}.log")
    shutil.move(log_file, archive_path)
    return log_file


def configure_logging(base_dir, logger_name, filename, max_bytes=1024 * 1024):
    """
    配置指定 logger：控制台 + 固定文件名追加 + 超阈值归档。

    参数:
      base_dir      项目根目录
      logger_name   logging.getLogger(logger_name)，如 "pixiv_novel_toolkit"
      filename      日志文件名，如 "download.log" 或 "postprocess.log"
      max_bytes     单文件大小阈值，超过则归档（默认 1 MB）
    """
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, filename)

    # 启动时归档（若已有日志文件过大）
    _archive_if_needed(log_file, max_bytes)

    root_logger = logging.getLogger(logger_name)
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    fmt = logging.Formatter("[%(levelname)s] %(message)s")

    console = TqdmLoggingHandler()
    console.setFormatter(fmt)
    root_logger.addHandler(console)

    # 追加模式，保留跨会话历史
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root_logger.addHandler(file_handler)

    # 会话分隔行（写入固定文件顶部 / 当前末尾）
    session_line = f"===== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ====="
    root_logger.info(session_line)
    return log_file