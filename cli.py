"""
Pixiv 系列下载器命令行入口。

提供两种使用方式：
  1) 子命令模式：适合脚本/批处理，参数明确可复用
     python cli.py novel <id> --chapter <num> [--force]
     python cli.py csv <path> [--force]
     python cli.py series <id> [--from N] [--chapters 11-21] [--index-only] [--force]
  2) 交互模式：不带任何子命令时启动交互菜单，与旧版行为一致
     python cli.py

`pixiv_novel_scraper.py` 仍可被直接运行；其 `if __name__ == "__main__"` 入口
会委托到这里的 `main()`，向后兼容旧的使用习惯。
"""

import argparse
import os
import sys

from log_setup import configure_logging
from pixiv_novel_scraper import PixivNovelScraper, __version__


def configure_download_logging(base_dir):
    """配置下载日志：固定文件 logs/download.log 追加，超 1MB 自动归档到 logs/archive/。"""
    return configure_logging(base_dir, "pixiv_novel_toolkit", "download.log")


def build_scraper(base_dir):
    """读取 cookie 文件并构造已登录的下载器实例。"""
    cookie_file = os.path.join(base_dir, "pixiv_cookie.txt")
    temp_scraper = PixivNovelScraper(base_dir=base_dir)
    cookie = temp_scraper.load_cookie_from_file(cookie_file)
    if not cookie:
        print(f"[WARN] No valid cookie was loaded from {cookie_file}. "
              "Some restricted novels may be inaccessible.")
    return PixivNovelScraper(cookie=cookie, base_dir=base_dir)


def cmd_novel(args, scraper):
    """单章下载。"""
    scraper.download_novel(args.novel_id, args.chapter, force=args.force)


def cmd_csv(args, scraper):
    """根据 CSV 记录批量下载。"""
    csv_path = args.csv_path
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(scraper.base_dir, csv_path)
    scraper.download_from_csv(csv_path, force=args.force)


def cmd_series(args, scraper):
    """整系列下载或仅更新索引。"""
    scraper.download_series(
        args.series_id,
        start_chapter=args.start,
        only_update_csv=args.index_only,
        chapter_selection=args.chapters or "",
        force=args.force,
        workers=args.workers,
    )


def cmd_retry(args, scraper):
    """根据现有 records.csv 找出缺失章节并补跑。"""
    scraper.download_missing(args.scope, args.target_id, force=args.force)


def run_interactive(scraper):
    """无参数时的交互式菜单，等价于旧版主入口行为。"""
    print(f"Pixiv Novel EPUB v{__version__}")
    print("=" * 40)
    print("1. Download a single chapter")
    print("2. Download chapters from CSV records")
    print("3. Process a complete Pixiv series")
    print("4. Retry missing chapters of a downloaded work")
    print("=" * 40)

    choice = input("Select an option [1/2/3/4] (press Enter for default: 3): ").strip()
    force_choice = input(
        "Overwrite existing chapters if found? [y/N] (press Enter for default: N): "
    ).strip().lower()
    force = force_choice in ('y', 'yes')

    if choice == '1':
        novel_id = input("\nEnter the Pixiv novel ID: ").strip()
        chapter_number = input("Enter the chapter index to save: ").strip()
        if novel_id and chapter_number:
            scraper.download_novel(novel_id, chapter_number, force=force)

    elif choice == '2':
        csv_path = input(
            "\nEnter the CSV file path to import (press Enter for default: import_records.csv): "
        ).strip()
        csv_path = csv_path if csv_path else os.path.join(scraper.base_dir, "import_records.csv")
        if not os.path.isabs(csv_path):
            csv_path = os.path.join(scraper.base_dir, csv_path)
        scraper.download_from_csv(csv_path, force=force)

    elif choice == '4':
        scope = input("\nEnter scope [novel/series]: ").strip()
        target_id = input("Enter the work ID: ").strip()
        if scope in ('novel', 'series') and target_id:
            scraper.download_missing(scope, target_id, force=force)
        else:
            print("[WARN] Invalid scope or empty ID.")

    else:
        series_id = input("\nEnter the Pixiv series ID: ").strip()
        if not series_id:
            print("[WARN] Series ID cannot be empty.")
            return
        chapter_selection = input(
            "Enter chapter selection (e.g. 11 or 11-21, press Enter for all chapters): "
        ).strip()
        if chapter_selection:
            start_num = '1'
            print("[INFO] Custom chapter selection detected. Saved chapter numbers will "
                  "follow the original series chapter numbers.")
        else:
            start_num = input("Enter the starting chapter number (press Enter for default: 1): ").strip()
            start_num = start_num if start_num else '1'

        print("\nChoose how to handle this series:")
        print("  [1] Download all chapter texts and illustrations (default)")
        print("  [2] Update the CSV index only without downloading chapter content")
        sub_choice = input("Enter [1/2]: ").strip()
        only_csv = sub_choice == '2'

        scraper.download_series(
            series_id,
            start_chapter=start_num,
            only_update_csv=only_csv,
            chapter_selection=chapter_selection,
            force=force,
        )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cli",
        description="pixiv-novel-epub：Pixiv 小说下载工具。不带子命令时进入交互模式。",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_novel = sub.add_parser("novel", help="Download a single chapter")
    p_novel.add_argument("novel_id", help="Pixiv novel ID")
    p_novel.add_argument("--chapter", required=True, help="Chapter index to save (e.g. 11)")
    p_novel.add_argument("--force", action="store_true", help="Overwrite if chapter file already exists")
    p_novel.set_defaults(func=cmd_novel)

    p_csv = sub.add_parser("csv", help="Batch download from a CSV record file")
    p_csv.add_argument("csv_path", nargs="?", default="import_records.csv",
                       help="CSV file path (default: import_records.csv)")
    p_csv.add_argument("--force", action="store_true", help="Overwrite existing chapters")
    p_csv.set_defaults(func=cmd_csv)

    p_series = sub.add_parser("series", help="Download or index a complete Pixiv series")
    p_series.add_argument("series_id", help="Pixiv series ID")
    p_series.add_argument("--from", dest="start", default="1",
                          help="Starting chapter number when not using --chapters (default: 1)")
    p_series.add_argument("--chapters", default=None,
                          help="Chapter selection, e.g. 11 or 11-21 (overrides --from)")
    p_series.add_argument("--index-only", action="store_true",
                          help="Update the CSV index only, do not download chapter content")
    p_series.add_argument("--force", action="store_true", help="Overwrite existing chapters")
    p_series.add_argument("--workers", type=int, default=1,
                          help="Concurrent download workers (default: 1 = sequential; >1 enables thread pool)")
    p_series.set_defaults(func=cmd_series)

    p_retry = sub.add_parser("retry", help="Re-download missing chapters based on records.csv")
    p_retry.add_argument("scope", choices=["novel", "series"],
                         help="Scope of the target work")
    p_retry.add_argument("target_id", help="Pixiv novel ID (if scope=novel) or series ID (if scope=series)")
    p_retry.add_argument("--force", action="store_true", help="Overwrite existing chapters")
    p_retry.set_defaults(func=cmd_retry)

    return parser


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    configure_download_logging(base_dir)
    parser = build_parser()
    args = parser.parse_args()

    scraper = build_scraper(base_dir)

    if getattr(args, "command", None):
        args.func(args, scraper)
    else:
        run_interactive(scraper)


if __name__ == "__main__":
    main()