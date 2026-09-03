"""统一命令入口，同时兼容项目原有的两个命令行脚本。"""

from __future__ import annotations

import sys


POSTPROCESS_COMMANDS = frozenset({
    "merge",
    "format",
    "format-single",
    "compare",
    "punct",
    "diff",
    "note",
    "assemble",
    "split",
    "toc",
    "epub",
})

ROOT_HELP = """usage: pixiv-novel <command> [options]

Pixiv 小说下载、文本整理与 EPUB 打包工具。

下载命令:
  novel, csv, series, retry

后处理命令:
  merge, format, format-single, compare, punct, diff, note,
  assemble, split, toc, epub

后处理命令既可直接调用，也可加 text 分组，例如：
  pixiv-novel epub standardized book.epub
  pixiv-novel text epub standardized book.epub

使用 pixiv-novel <command> --help 查看具体参数。
"""


def main(argv=None):
    """分发下载与后处理命令。

    原下载命令可直接使用，例如 ``pixiv-novel series 123``；后处理命令既可
    直接使用 ``pixiv-novel epub ...``，也可写成更明确的
    ``pixiv-novel text epub ...``。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    first = args[0] if args else None

    if first in {"-h", "--help"}:
        print(ROOT_HELP)
        return 0

    if first == "text":
        from pixiv_novel_toolkit.postprocess_cli import main as postprocess_main

        return postprocess_main(args[1:])
    if first in POSTPROCESS_COMMANDS:
        from pixiv_novel_toolkit.postprocess_cli import main as postprocess_main

        return postprocess_main(args)

    from pixiv_novel_toolkit.download_cli import main as download_main

    return download_main(args)


if __name__ == "__main__":
    main()
