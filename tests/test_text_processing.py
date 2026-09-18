import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pixiv_novel_toolkit.postprocess.auditing import TextAuditor, audit_lines
from pixiv_novel_toolkit.postprocess.cleaning import TextCleaner, clean_text
from pixiv_novel_toolkit.postprocess.processing_config import (
    TEXT_PROCESSING_DEFAULTS,
    load_text_processing_config,
)
from pixiv_novel_toolkit.postprocess_cli import _cmd_audit, _cmd_clean


class TextProcessingConfigTests(unittest.TestCase):
    def test_missing_config_generates_template_and_deep_copies_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "text_processing.json"
            config = load_text_processing_config(str(path))
            self.assertEqual(config, TEXT_PROCESSING_DEFAULTS)
            self.assertTrue(path.is_file())
            config["clean"]["join_broken_quote_lines"]["enabled"] = False
            self.assertTrue(
                TEXT_PROCESSING_DEFAULTS["clean"]["join_broken_quote_lines"]["enabled"]
            )

    def test_invalid_single_setting_falls_back_without_losing_other_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "text_processing.json"
            path.write_text(
                json.dumps({
                    "clean": {
                        "normalize_punctuation": {"enabled": True},
                    },
                    "audit": {
                        "long_paragraph": {"minimum_length": "很多"},
                    },
                }),
                encoding="utf-8",
            )
            config = load_text_processing_config(str(path))
            self.assertTrue(config["clean"]["normalize_punctuation"]["enabled"])
            self.assertEqual(config["audit"]["long_paragraph"]["minimum_length"], 339)


class TextCleaningTests(unittest.TestCase):
    def test_clean_text_applies_only_enabled_safe_rules(self):
        source = (
            "第1.2章 测试\n"
            "第二百五十三 见到学姐\n"
            "一百章 开始\n"
            "三章之后他终于回来了\n"
            "他说：“\n"
            "你好。”\n"
            "重复正文\n"
            "重复正文\n"
            "PS：求收藏，谢谢大家\n"
            "\n"
            "另外：推荐好友新书【山村后宫】\n"
            "\n"
            "这里是正常正文。\n"
            "英文!\n"
        )
        cleaned, changes = clean_text(source, copy.deepcopy(TEXT_PROCESSING_DEFAULTS))
        self.assertIn("第12章 测试", cleaned)
        self.assertIn("第二百五十三章 见到学姐", cleaned)
        self.assertIn("第一百章 开始", cleaned)
        self.assertIn("三章之后他终于回来了", cleaned)
        self.assertNotIn("第三章之后他终于回来了", cleaned)
        self.assertIn("他说：“你好。”", cleaned)
        self.assertEqual(cleaned.count("重复正文"), 1)
        self.assertNotIn("求收藏", cleaned)
        self.assertNotIn("山村后宫", cleaned)
        self.assertIn("这里是正常正文。", cleaned)
        self.assertIn("英文!", cleaned)
        self.assertGreaterEqual(sum(item["count"] for item in changes), 5)

    def test_clean_removes_blank_separated_tail_note_and_keeps_normal_body(self):
        source = (
            "第一章 正文\n"
            "最后一段。\n\n\n\n"
            "赞助地址：https://example.com\n"
            "（加入交流群）\n"
            "感谢您的支持\n"
            "第二章 正文\n"
            "这里是正常内容。\n\n\n\n"
            "场景转换\n"
            "结尾正文。\n"
        )
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        self.assertFalse(
            config["clean"]["remove_blank_separated_author_notes"]["enabled"]
        )
        config["clean"]["remove_blank_separated_author_notes"]["enabled"] = True
        cleaned, changes = clean_text(source, config)
        self.assertNotIn("赞助地址", cleaned)
        self.assertNotIn("感谢您的支持", cleaned)
        self.assertIn("第二章 正文", cleaned)
        self.assertIn("场景转换", cleaned)
        self.assertIn("结尾正文。", cleaned)
        change = next(
            item for item in changes
            if item["rule"] == "remove_blank_separated_author_notes"
        )
        self.assertEqual(change["count"], 3)

    def test_tail_note_signal_must_appear_near_start_of_candidate(self):
        source = (
            "第一章 正文\n"
            "上一幕。\n\n\n\n"
            "正常正文一。\n"
            "正常正文二。\n"
            "正常正文三。\n"
            "正常正文四提到了交流群。\n"
        )
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        config["clean"]["remove_blank_separated_author_notes"]["enabled"] = True
        cleaned, changes = clean_text(source, config)
        self.assertEqual(cleaned, source)
        self.assertFalse(any(
            item["rule"] == "remove_blank_separated_author_notes"
            for item in changes
        ))

    def test_tail_note_uses_two_blank_lines_and_removes_illustration_marker(self):
        source = (
            "第四十三章 正文\n"
            "　　最后一段正文。\n\n\n"
            "依旧是来自群友遥香的无偿插画：\n"
            "纪清仪be like：\n\n\n"
            "【插图: ch043_up_23017765.jpg】\n\n"
        )
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        rule = config["clean"]["remove_blank_separated_author_notes"]
        self.assertEqual(rule["minimum_blank_lines"], 2)
        self.assertEqual(rule["signal_scan_lines"], 2)
        rule["enabled"] = True
        cleaned, changes = clean_text(source, config)
        self.assertNotIn("来自群友遥香", cleaned)
        self.assertNotIn("be like", cleaned)
        self.assertIn("　　最后一段正文。", cleaned)
        self.assertNotIn("【插图: ch043_up_23017765.jpg】", cleaned)
        change = next(
            item for item in changes
            if item["rule"] == "remove_blank_separated_author_notes"
        )
        self.assertEqual(change["count"], 3)

    def test_tail_note_removes_pixiv_uploadedimage_marker(self):
        source = (
            "第五十八章 正文\n"
            "　　最后一段正文。\n\n\n"
            "遥香说：新插画来了\n"
            "[uploadedimage:24406402]\n"
        )
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        config["clean"]["remove_blank_separated_author_notes"]["enabled"] = True
        cleaned, changes = clean_text(source, config)
        self.assertNotIn("遥香说", cleaned)
        self.assertNotIn("uploadedimage", cleaned)
        change = next(
            item for item in changes
            if item["rule"] == "remove_blank_separated_author_notes"
        )
        self.assertEqual(change["count"], 2)

    def test_tail_note_expands_back_to_illustration_before_author_text(self):
        source = (
            "第四十六章 正文\n"
            "　　最后一段正文。\n\n\n"
            "【插图: ch046_up_23544553.jpg】\n\n\n"
            "（插画来自群友遥香）\n"
        )
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        config["clean"]["remove_blank_separated_author_notes"]["enabled"] = True
        cleaned, changes = clean_text(source, config)
        self.assertNotIn("【插图:", cleaned)
        self.assertNotIn("插画来自群友遥香", cleaned)
        self.assertIn("　　最后一段正文。", cleaned)
        change = next(
            item for item in changes
            if item["rule"] == "remove_blank_separated_author_notes"
        )
        self.assertEqual(change["count"], 2)

    def test_scene_break_replacement_inserts_once_and_handles_existing_ellipsis(self):
        source = (
            "第一章 正文\n"
            "场景一结束。\n\n\n\n"
            "场景二开始。\n"
            "第二章 正文\n"
            "另一个场景结束。\n"
            "……\n\n\n\n"
            "下一幕开始。\n"
        )
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        self.assertFalse(
            config["clean"]["replace_scene_break_blank_lines"]["enabled"]
        )
        config["clean"]["replace_scene_break_blank_lines"]["enabled"] = True
        cleaned, changes = clean_text(source, config)
        self.assertEqual(cleaned.count("……"), 2)
        change = next(
            item for item in changes
            if item["rule"] == "replace_scene_break_blank_lines"
        )
        self.assertEqual(change["count"], 2)
        self.assertIn("插入分隔符 1 处", change["message"])
        self.assertIn("已有分隔符 1 处", change["message"])

    def test_cleaner_writes_separate_disabled_feature_reports_with_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text(
                "第一章 正文\n前一段。\n再前一段。\n\n\n\n"
                "后一段。\n再后一段。\n正文结尾。\n\n\n\n"
                "赞助地址：https://example.com\n感谢您的支持\n",
                encoding="utf-8",
            )
            reports = root / "reports"
            TextCleaner(
                source,
                root / "cleaned",
                reports,
                copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
            ).run()

            author = json.loads(
                (reports / "blank_author_notes_report.json").read_text(
                    encoding="utf-8"
                )
            )
            scenes = json.loads(
                (reports / "scene_breaks_report.json").read_text(encoding="utf-8")
            )
            self.assertFalse(author["enabled"])
            self.assertEqual(author["candidate_count"], 1)
            self.assertEqual(author["candidates"][0]["action"], "not_enabled")
            self.assertFalse(scenes["enabled"])
            self.assertEqual(scenes["candidate_count"], 1)
            self.assertEqual(len(scenes["candidates"][0]["before"]), 2)
            self.assertEqual(len(scenes["candidates"][0]["after"]), 2)
            self.assertTrue((reports / "blank_author_notes_report.txt").is_file())
            self.assertTrue((reports / "scene_breaks_report.txt").is_file())

    def test_cleaner_writes_utf8_output_and_reports_to_separate_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            chapters.mkdir()
            source = chapters / "001 测试.txt"
            source.write_bytes("重复正文\n重复正文\n".encode("gb18030"))
            cleaned = root / "cleaned"
            reports = root / "reports"
            report = TextCleaner(
                chapters,
                cleaned,
                reports,
                copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
            ).run()
            self.assertEqual(
                (cleaned / source.name).read_text(encoding="utf-8"),
                "重复正文\n",
            )
            self.assertEqual(report["summary"]["changed_files"], 1)
            self.assertTrue((reports / "clean_report.txt").is_file())
            self.assertTrue((reports / "clean_report.json").is_file())
            self.assertTrue((reports / "blank_author_notes_report.txt").is_file())
            self.assertTrue((reports / "scene_breaks_report.txt").is_file())

    def test_dry_run_writes_report_but_not_cleaned_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("重复正文\n重复正文\n", encoding="utf-8")
            output = root / "cleaned"
            reports = root / "reports"
            TextCleaner(
                source,
                output,
                reports,
                copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
                dry_run=True,
            ).run()
            self.assertFalse(output.exists())
            self.assertTrue((reports / "clean_report.json").is_file())

    def test_cleaner_reports_damaged_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "damaged.txt"
            source.write_bytes("第一章 正文".encode("utf-8") + b"\xff")
            report = TextCleaner(
                source,
                root / "cleaned",
                root / "reports",
                copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
            ).run()

            changes = report["files"][0]["changes"]
            self.assertEqual(changes[0]["rule"], "decode_recovery")
            self.assertTrue(report["files"][0]["changed"])
            self.assertIn(
                "\ufffd",
                (root / "cleaned" / "damaged.txt").read_text(encoding="utf-8"),
            )


class TextAuditingTests(unittest.TestCase):
    def test_audit_finds_configured_quality_problems(self):
        config = copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
        config["audit"]["long_paragraph"]["minimum_length"] = 10
        config["audit"]["suspected_hard_wraps"]["minimum_previous_length"] = 10
        findings = audit_lines(
            [
                "第一章 开始",
                "这是一个达到长度阈值而且没有结束标点的段落",
                "下一行继续正文。",
                "重复正文",
                "重复正文",
                "本章求月票支持",
                "三章之后他终于回来了",
                "他说：“没有结束",
                "损坏字符：\ufffd",
            ],
            "book.txt",
            config,
        )
        rules = {finding["rule"] for finding in findings}
        self.assertIn("long_paragraph", rules)
        self.assertIn("duplicate_lines", rules)
        self.assertIn("advertisement_keywords", rules)
        self.assertIn("quote_balance", rules)
        self.assertIn("suspected_hard_wraps", rules)
        self.assertIn("chapter_title_anomalies", rules)
        self.assertIn("decoding_anomalies", rules)

    def test_audit_finds_blank_separated_tail_note(self):
        findings = audit_lines(
            [
                "第一章 正文",
                "最后一段。",
                "",
                "",
                "",
                "赞助地址：https://example.com",
                "感谢您的支持",
            ],
            "001 第一章.txt",
            copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
        )
        self.assertTrue(any(
            finding["rule"] == "blank_separated_author_notes"
            for finding in findings
        ))

    def test_numbered_chapter_only_checks_first_nonempty_line_for_title_anomaly(self):
        findings = audit_lines(
            ["第一章 开始", "", "605不负责"],
            "659 第六百五十九章.txt",
            copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
        )
        self.assertFalse(any(
            finding["rule"] == "chapter_title_anomalies" for finding in findings
        ))

    def test_auditor_skips_book_info_and_supports_selected_report_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "cleaned"
            reports = root / "reports"
            chapters.mkdir()
            (chapters / "000 书籍信息.txt").write_text("简介：求月票", encoding="utf-8")
            (chapters / "001 第一章.txt").write_text("正文", encoding="utf-8")
            report = TextAuditor(
                chapters,
                reports,
                copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
                report_format="json",
            ).run()
            self.assertEqual(report["file_count"], 1)
            self.assertTrue((reports / "audit_report.json").is_file())
            self.assertFalse((reports / "audit_report.txt").exists())

    def test_auditor_ignores_stale_unnumbered_txt_in_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "cleaned"
            chapters.mkdir()
            (chapters / "001 第一章.txt").write_text("第一章 正文", encoding="utf-8")
            (chapters / "全书.txt").write_text("一章 标题", encoding="utf-8")
            report = TextAuditor(
                chapters,
                root / "reports",
                copy.deepcopy(TEXT_PROCESSING_DEFAULTS),
                report_format="json",
            ).run()
            self.assertEqual(report["file_count"], 1)
            self.assertEqual(report["skipped_files"], ["全书.txt"])


class TextProcessingCliTests(unittest.TestCase):
    def test_commands_use_configured_sibling_output_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            chapters.mkdir()
            (chapters / "001 测试.txt").write_text("重复正文\n重复正文\n", encoding="utf-8")
            config_path = root / "settings.json"
            config_path.write_text(
                json.dumps(TEXT_PROCESSING_DEFAULTS, ensure_ascii=False),
                encoding="utf-8",
            )
            clean_result = _cmd_clean(SimpleNamespace(
                input=str(chapters),
                output_dir=None,
                config=str(config_path),
                report_dir=None,
                dry_run=False,
            ))
            audit_result = _cmd_audit(SimpleNamespace(
                input=str(root / "cleaned"),
                report_dir=None,
                config=str(config_path),
                format="both",
            ))
            self.assertEqual(clean_result, 0)
            self.assertEqual(audit_result, 0)
            self.assertTrue((root / "cleaned" / "001 测试.txt").is_file())
            self.assertTrue((root / "reviewed").is_dir())
            self.assertTrue((root / "reports" / "audit_report.txt").is_file())

    def test_clean_preserves_reviewed_and_dry_run_does_not_create_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            chapters.mkdir()
            (chapters / "001 测试.txt").write_text("正文", encoding="utf-8")
            config_path = root / "settings.json"
            config_path.write_text(
                json.dumps(TEXT_PROCESSING_DEFAULTS, ensure_ascii=False),
                encoding="utf-8",
            )

            dry_result = _cmd_clean(SimpleNamespace(
                input=str(chapters),
                output_dir=None,
                config=str(config_path),
                report_dir=None,
                dry_run=True,
            ))
            self.assertEqual(dry_result, 0)
            self.assertFalse((root / "reviewed").exists())

            reviewed = root / "reviewed"
            reviewed.mkdir()
            keep = reviewed / "001 人工版.txt"
            keep.write_text("保留人工修改", encoding="utf-8")
            clean_result = _cmd_clean(SimpleNamespace(
                input=str(chapters),
                output_dir=None,
                config=str(config_path),
                report_dir=None,
                dry_run=False,
            ))
            self.assertEqual(clean_result, 0)
            self.assertEqual(keep.read_text(encoding="utf-8"), "保留人工修改")


if __name__ == "__main__":
    unittest.main()
