"""外来小说文本的编码探测与统一读取。"""

from __future__ import annotations

from collections.abc import Callable
from os import PathLike


_COMMON_HAN = frozenset(
    "的一是不了在人有我他她它这中大来上和国说们到为地也子时道出而要就"
    "下得可你年生会自着去之过家学对里后么小好作分多天能同行见用与行"
    "沒有這個們時說會來對學國過後麼東車馬鳥龍風飛門問間書長樂體點"
)


def detect_encoding(path: str | PathLike[str]) -> str:
    """探测 UTF-8、UTF-16、GB18030 或 Big5 文本编码。"""
    with open(path, "rb") as file:
        data = file.read()
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    best_encoding, best_score = "gb18030", -1.0
    for encoding in ("gb18030", "big5"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        han = [char for char in text if "\u4e00" <= char <= "\u9fff"]
        score = sum(char in _COMMON_HAN for char in han) / len(han) if han else 0.0
        if score > best_score:
            best_encoding, best_score = encoding, score
    return best_encoding


def _report_non_utf8(
    encoding: str,
    path: str | PathLike[str],
    info: Callable[[str], None] | None,
) -> None:
    if encoding not in ("utf-8", "utf-8-sig") and info is not None:
        info(f"检测到非 UTF-8 编码（{encoding}），自动转换读取: {path}")


def read_text_lines(
    path: str | PathLike[str],
    *,
    info: Callable[[str], None] | None = None,
) -> list[str]:
    """自动探测编码后读取文本，并以 ``splitlines`` 拆行。"""
    encoding = detect_encoding(path)
    _report_non_utf8(encoding, path, info)
    with open(path, "r", encoding=encoding) as file:
        return file.read().splitlines()


def read_text(
    path: str | PathLike[str],
    *,
    info: Callable[[str], None] | None = None,
) -> str:
    """自动探测编码后读取完整文本。"""
    encoding = detect_encoding(path)
    _report_non_utf8(encoding, path, info)
    with open(path, "r", encoding=encoding) as file:
        return file.read()

