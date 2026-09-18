"""外来小说文本的编码探测与统一读取。"""

from __future__ import annotations

from collections.abc import Callable
from os import PathLike


_COMMON_HAN = frozenset(
    "的一是不了在人有我他她它这中大来上和国说们到为地也子时道出而要就"
    "下得可你年生会自着去之过家学对里后么小好作分多天能同行见用与行"
    "沒有這個們時說會來對學國過後麼東車馬鳥龍風飛門問間書長樂體點"
)


def _encoding_score(data: bytes, encoding: str) -> tuple[float, float]:
    """为带少量坏字节的文本评估候选编码，优先常见汉字与较少替换符。"""
    text = data.decode(encoding, errors="replace")
    han = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    common_ratio = sum(char in _COMMON_HAN for char in han) / len(han) if han else 0.0
    replacement_ratio = text.count("\ufffd") / max(len(text), 1)
    return common_ratio, -replacement_ratio


def _detect_encoding_bytes(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    best_encoding = None
    best_score = -1.0
    for encoding in ("gb18030", "big5"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        han = [char for char in text if "\u4e00" <= char <= "\u9fff"]
        score = sum(char in _COMMON_HAN for char in han) / len(han) if han else 0.0
        if score > best_score:
            best_encoding, best_score = encoding, score
    if best_encoding is not None:
        return best_encoding

    # 少量字节损坏、混入单字节控制码时，所有严格解码都可能失败。
    # 此时不能无条件回退 GB18030，否则本来几乎完整的 UTF-8 会整篇乱码。
    return max(
        ("utf-8", "gb18030", "big5"),
        key=lambda encoding: _encoding_score(data, encoding),
    )


def detect_encoding(path: str | PathLike[str]) -> str:
    """探测 UTF-8、UTF-16、GB18030 或 Big5 文本编码。"""
    with open(path, "rb") as file:
        return _detect_encoding_bytes(file.read())


def _report_non_utf8(
    encoding: str,
    path: str | PathLike[str],
    info: Callable[[str], None] | None,
) -> None:
    if encoding not in ("utf-8", "utf-8-sig") and info is not None:
        info(f"检测到非 UTF-8 编码（{encoding}），自动转换读取: {path}")


def _read_decoded(
    path: str | PathLike[str],
    info: Callable[[str], None] | None,
) -> str:
    """严格解码优先；遇到少量坏字节时保留其余正文并标记替换位置。"""
    with open(path, "rb") as file:
        data = file.read()
    encoding = _detect_encoding_bytes(data)
    _report_non_utf8(encoding, path, info)
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as error:
        text = data.decode(encoding, errors="replace")
        if info is not None:
            info(
                f"文本包含无法按 {encoding} 解码的异常字节（首处偏移 {error.start}），"
                f"已用替换符保留其余内容: {path}"
            )
    # 与原先文本模式读取的 universal-newline 行为保持一致。
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_lines(
    path: str | PathLike[str],
    *,
    info: Callable[[str], None] | None = None,
) -> list[str]:
    """自动探测编码后读取文本，并以 ``splitlines`` 拆行。"""
    return _read_decoded(path, info).splitlines()


def read_text(
    path: str | PathLike[str],
    *,
    info: Callable[[str], None] | None = None,
) -> str:
    """自动探测编码后读取完整文本。"""
    return _read_decoded(path, info)
