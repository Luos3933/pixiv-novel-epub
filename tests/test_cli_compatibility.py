import unittest

import cli
import txt_file_processing
from pixiv_novel_toolkit.__main__ import POSTPROCESS_COMMANDS
from pixiv_novel_toolkit import download_cli, postprocess_cli


class CliCompatibilityTests(unittest.TestCase):
    def test_legacy_download_entry_reexports_package_cli(self):
        self.assertIs(cli.main, download_cli.main)
        self.assertIs(cli.build_parser, download_cli.build_parser)

    def test_download_cli_keeps_project_root_for_runtime_files(self):
        self.assertEqual(download_cli.PROJECT_ROOT.name, "pixiv-novel-toolkit")

    def test_legacy_postprocess_entry_reexports_package_cli(self):
        self.assertIs(txt_file_processing.main, postprocess_cli.main)
        self.assertIs(txt_file_processing.build_arg_parser, postprocess_cli.build_arg_parser)

    def test_postprocess_relative_paths_still_resolve_from_project_root(self):
        expected = postprocess_cli.PROJECT_ROOT / "standardized"
        self.assertEqual(postprocess_cli._resolve_path("standardized"), str(expected))

    def test_legacy_download_commands_remain_registered(self):
        parser = cli.build_parser()
        subparsers = next(
            action for action in parser._actions if hasattr(action, "choices") and action.choices
        )
        self.assertEqual(
            set(subparsers.choices),
            {"novel", "csv", "series", "retry", "quick"},
        )

    def test_download_cli_normalizes_novel_and_series_urls(self):
        parser = cli.build_parser()
        novel = parser.parse_args(
            ["novel", "pixiv.net/novel/show.php?id=123", "--chapter", "1"]
        )
        series = parser.parse_args(
            ["series", "www.pixiv.net/novel/series/456"]
        )
        quick = parser.parse_args(
            [
                "quick",
                "pixiv.net/novel/series/789",
                "--workers",
                "3",
                "--volumes",
                "volumes.json",
                "--maker",
                "Laffey",
                "--title-style",
                "split_title",
                "--vol-style",
                "default",
                "--title-align",
                "left",
                "--title-underline",
                "--indent",
            ]
        )
        self.assertEqual(novel.novel_id, "123")
        self.assertEqual(series.series_id, "456")
        self.assertEqual(quick.series_id, "789")
        self.assertEqual(quick.workers, 3)
        self.assertEqual(quick.volumes, "volumes.json")
        self.assertEqual(quick.maker, "Laffey")
        self.assertEqual(quick.title_style, "split_title")
        self.assertEqual(quick.vol_style, "default")
        self.assertEqual(quick.title_align, "left")
        self.assertTrue(quick.title_underline)
        self.assertTrue(quick.indent)

    def test_legacy_postprocess_commands_remain_registered(self):
        parser = txt_file_processing.build_arg_parser()
        subparsers = next(
            action for action in parser._actions if hasattr(action, "choices") and action.choices
        )
        self.assertEqual(set(subparsers.choices), set(POSTPROCESS_COMMANDS))

    def test_toc_inspect_subcommand_is_registered(self):
        args = txt_file_processing.build_arg_parser().parse_args(
            ["toc", "inspect", "book.txt"]
        )
        self.assertEqual(args.toc_action, "inspect")
        self.assertEqual(args.path, "book.txt")


if __name__ == "__main__":
    unittest.main()
