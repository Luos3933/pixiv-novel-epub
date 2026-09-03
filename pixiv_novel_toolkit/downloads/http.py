"""Pixiv 下载器共享的 HTTP 重试、JSON 解码与流式写入。"""

import logging
import time

import requests
from requests import exceptions as requests_exceptions


LOGGER = logging.getLogger("pixiv_novel_toolkit")


def request_with_retry(
    url,
    *,
    headers,
    stream=False,
    timeout=20,
    max_retries=3,
    retry_delay=2.0,
    purpose="request",
    request_get=None,
    sleep=None,
    log=None,
):
    """发起 GET 请求，并对超时、连接错误和一般请求错误有限重试。"""
    request_get = request_get or requests.get
    sleep = sleep or time.sleep
    log = log or LOGGER
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = request_get(
                url,
                headers=headers,
                stream=stream,
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except requests_exceptions.ReadTimeout as exc:
            last_error = exc
            log.warning(
                f"{purpose.capitalize()} timed out on attempt "
                f"{attempt}/{max_retries}. Retrying..."
            )
        except requests_exceptions.ConnectionError as exc:
            last_error = exc
            log.warning(
                f"Connection error occurred during {purpose} on attempt "
                f"{attempt}/{max_retries}. Retrying..."
            )
        except requests_exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            log.error(f"HTTP error during {purpose}. Status code: {status_code}")
            raise
        except requests_exceptions.RequestException as exc:
            last_error = exc
            log.warning(
                f"Request error occurred during {purpose} on attempt "
                f"{attempt}/{max_retries}: {exc}"
            )

        if attempt < max_retries:
            sleep(retry_delay * attempt)

    raise last_error


def decode_json_response(response, purpose="request"):
    """解析响应 JSON，并补充请求用途上下文。"""
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"Invalid JSON received during {purpose}: {exc}") from exc


def write_stream_response(response, save_path, chunk_size=1024):
    """将 requests 风格流式响应写入文件，忽略 keep-alive 空块。"""
    with open(save_path, "wb") as file_obj:
        for chunk in response.iter_content(chunk_size):
            if chunk:
                file_obj.write(chunk)
