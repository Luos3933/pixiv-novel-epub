"""下载器默认参数、请求头与 Cookie 文件读取。"""

import logging
import os


DEFAULT_REQUEST_TIMEOUT = 20
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2.0
DEFAULT_CHAPTER_DELAY = 1.5

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.pixiv.net/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

LOGGER = logging.getLogger("pixiv_novel_toolkit")


def build_request_headers(cookie=""):
    """为单个下载器实例创建独立请求头，并按需附加登录 Cookie。"""
    headers = dict(DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    return headers


def load_cookie_file(cookie_file, *, warn=None):
    """读取并清理 Cookie；文件缺失时警告并返回空字符串。"""
    if not os.path.exists(cookie_file):
        warning = warn or LOGGER.warning
        warning(f"Cookie file not found: {cookie_file}")
        return ""
    with open(cookie_file, "r", encoding="utf-8") as file_obj:
        return file_obj.read().strip()
