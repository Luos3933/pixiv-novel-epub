"""Pixiv 下载命令旧入口；正式实现位于 pixiv_novel_toolkit.download_cli。"""

from pixiv_novel_toolkit import __version__
from pixiv_novel_toolkit.download_cli import (
    PROJECT_ROOT,
    build_parser,
    build_scraper,
    cmd_csv,
    cmd_novel,
    cmd_retry,
    cmd_series,
    configure_download_logging,
    main,
    run_interactive,
)
from pixiv_novel_toolkit.downloads.scraper import PixivNovelScraper


if __name__ == "__main__":
    main()
