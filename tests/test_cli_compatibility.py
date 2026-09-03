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
        self.assertEqual(set(subparsers.choices), {"novel", "csv", "series", "retry"})

    def test_legacy_postprocess_commands_remain_registered(self):
        parser = txt_file_processing.build_arg_parser()
        subparsers = next(
            action for action in parser._actions if hasattr(action, "choices") and action.choices
        )
        self.assertEqual(set(subparsers.choices), set(POSTPROCESS_COMMANDS))


if __name__ == "__main__":
    unittest.main()
