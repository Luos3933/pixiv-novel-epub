"""人工校正修订记录的持久化。"""

from datetime import datetime
import json
import logging
import os

from pixiv_novel_toolkit.chapters.overlay import build_prefix_index, file_prefix


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")


class RevisionsStore:
    """维护校正目录下以章节数字前缀为主键的 ``_revisions.json``。"""

    FILENAME = "_revisions.json"

    def __init__(self, corrected_dir):
        self.corrected_dir = corrected_dir
        self.path = os.path.join(corrected_dir, self.FILENAME)
        self.data = self._load()

    def _load(self):
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            logger.warning(f"读取修订记录失败，将重置: {self.path} ({error})")
            return {}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _normalize_key(filename):
        """完整文件名和纯编号统一为章节前缀；无前缀时保留文件名。"""
        if filename is None:
            return None
        prefix = file_prefix(filename)
        return prefix if prefix is not None else filename

    def set(self, filename, msg):
        """新增或覆盖一条修订记录。"""
        key = self._normalize_key(filename)
        if key is None:
            raise ValueError("note add 必须提供 filename 或前缀编号")

        existing = self.data.get(key, {})
        record = {
            "msg": msg,
            "filename": existing.get("filename", filename if filename != key else ""),
            "mtime": existing.get("mtime", ""),
            "updated_at": self._now(),
        }

        if filename and filename != key:
            record["filename"] = filename
            file_path = os.path.join(self.corrected_dir, filename)
        else:
            prefix_map, _ = build_prefix_index(self.corrected_dir, warn=logger.warning)
            actual_name = prefix_map.get(key)
            record["filename"] = actual_name or ""
            file_path = (
                os.path.join(self.corrected_dir, actual_name) if actual_name else None
            )

        if file_path and os.path.isfile(file_path):
            timestamp = os.path.getmtime(file_path)
            record["mtime"] = datetime.fromtimestamp(timestamp).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

        self.data[key] = record
        self._save()

    def remove(self, filename):
        """删除一条修订记录，并兼容旧版完整文件名主键。"""
        key = self._normalize_key(filename)
        if key is None:
            return False
        if key in self.data:
            del self.data[key]
            self._save()
            return True
        if filename in self.data:
            del self.data[filename]
            self._save()
            return True
        return False

    def list_all(self):
        """返回记录副本。"""
        return dict(self.data)

    def clear(self):
        """清空全部记录并持久化。"""
        self.data = {}
        self._save()
