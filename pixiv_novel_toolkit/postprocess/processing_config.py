"""文本清洗与质量检查的共享配置。"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")

TEXT_PROCESSING_DEFAULTS = {
    "version": 1,
    "paths": {
        "clean_output": "cleaned",
        "report_output": "reports",
    },
    "clean": {
        "join_broken_quote_lines": {
            "enabled": True,
        },
        "join_suspected_hard_wraps": {
            "enabled": False,
            "minimum_previous_length": 30,
            "maximum_line_length": 80,
        },
        "normalize_chapter_titles": {
            "enabled": True,
            "repair_missing_prefix": True,
            "repair_missing_suffix": True,
            "remove_number_dots": True,
        },
        "remove_adjacent_duplicate_lines": {
            "enabled": True,
            "minimum_length": 4,
        },
        "remove_advertisement_lines": {
            "enabled": True,
            "required_prefixes": ["PS", "P.S.", "作者的话"],
            "keywords": [
                "求票",
                "求收藏",
                "求月票",
                "求鲜花",
                "收藏",
            ],
            "continuation_keywords": [
                "推荐好友",
                "推荐新书",
                "好友新书",
                "新书【",
                "求票",
                "求收藏",
                "求月票",
                "求鲜花",
                "收藏本书",
                "支持本书",
            ],
            "maximum_following_paragraphs": 3,
        },
        "remove_blank_separated_author_notes": {
            "enabled": False,
            "minimum_blank_lines": 2,
            "maximum_note_lines": 20,
            "signal_scan_lines": 2,
            "remove_illustration_markers": True,
            "signals": [
                "作者的话",
                "作者有话说",
                "赞助地址",
                "货摊地址",
                "感谢您的支持",
                "交流群",
                "交流QQ群",
                "推荐好友",
                "推荐新书",
                "题外话",
                "来自群友",
                "无偿插画",
                "插画来自",
                "插图来自",
                "插画：",
                "遥香说",
                "遥香：",
                "遥香忙",
                "本章没有插图",
                "感谢遥香",
                "一些要说的话",
                "停更",
                "本书仅发布",
                "读者群",
                "be like",
                "求票",
                "求收藏",
                "求月票",
                "求鲜花",
                "https://",
                "http://",
            ],
        },
        "replace_scene_break_blank_lines": {
            "enabled": False,
            "minimum_blank_lines": 3,
            "marker": "……",
            "context_paragraphs": 2,
        },
        "normalize_punctuation": {
            "enabled": False,
        },
    },
    "audit": {
        "decoding_anomalies": {
            "enabled": True,
        },
        "quote_balance": {
            "enabled": True,
        },
        "long_paragraph": {
            "enabled": True,
            "minimum_length": 339,
        },
        "duplicate_lines": {
            "enabled": True,
            "minimum_length": 4,
        },
        "duplicate_chapter_titles": {
            "enabled": True,
            "nearby_line_limit": 5,
        },
        "chapter_title_anomalies": {
            "enabled": True,
        },
        "chapter_context": {
            "enabled": False,
            "before": 2,
            "after": 2,
            "maximum_entries": 100,
        },
        "advertisement_keywords": {
            "enabled": True,
            "before": 2,
            "after": 2,
            "keywords": [
                "求票",
                "求收藏",
                "求月票",
                "求鲜花",
                "作者的话",
                "推荐好友新书",
                "推荐新书",
            ],
        },
        "blank_separated_author_notes": {
            "enabled": True,
            "minimum_blank_lines": 2,
            "maximum_note_lines": 20,
            "signal_scan_lines": 2,
            "remove_illustration_markers": True,
            "signals": [
                "作者的话",
                "作者有话说",
                "赞助地址",
                "货摊地址",
                "感谢您的支持",
                "交流群",
                "交流QQ群",
                "推荐好友",
                "推荐新书",
                "题外话",
                "来自群友",
                "无偿插画",
                "插画来自",
                "插图来自",
                "插画：",
                "遥香说",
                "遥香：",
                "遥香忙",
                "本章没有插图",
                "感谢遥香",
                "一些要说的话",
                "停更",
                "本书仅发布",
                "读者群",
                "be like",
                "求票",
                "求收藏",
                "求月票",
                "求鲜花",
                "https://",
                "http://",
            ],
        },
        "suspected_hard_wraps": {
            "enabled": True,
            "minimum_previous_length": 30,
            "maximum_line_length": 80,
        },
        "punctuation_anomalies": {
            "enabled": True,
        },
    },
}

TEXT_PROCESSING_SAMPLE = {
    "_说明": {
        "总览": "clean 写入 cleaned/，audit 与 clean 报告写入 reports/；每条规则用 enabled 控制。",
        "安全性": "clean 只自动修改高置信度问题；引号不配对、缺句末标点等歧义问题仅由 audit 提示。普通硬回车合并可能改变段落，默认关闭。",
        "路径": "paths 中的相对目录名以输入目录或输入文件的父目录为基准。",
    },
    **TEXT_PROCESSING_DEFAULTS,
}


def default_text_processing_config_path() -> str:
    """返回项目根目录下的默认配置路径。"""
    return str(Path(__file__).resolve().parents[2] / "text_processing.json")


def _merge_known_settings(defaults, supplied, path, warning):
    """只合并默认模板中存在且类型兼容的键。"""
    result = copy.deepcopy(defaults)
    if not isinstance(supplied, dict):
        warning(f"文本处理配置 {path} 应为 JSON 对象，已使用默认值")
        return result
    for key, default in defaults.items():
        if key not in supplied:
            continue
        value = supplied[key]
        label = f"{path}.{key}" if path else key
        if isinstance(default, dict):
            result[key] = _merge_known_settings(default, value, label, warning)
        elif isinstance(default, bool):
            if isinstance(value, bool):
                result[key] = value
            else:
                warning(f"文本处理配置 {label} 应为布尔值，已使用默认值 {default!r}")
        elif isinstance(default, int):
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                result[key] = value
            else:
                warning(f"文本处理配置 {label} 应为非负整数，已使用默认值 {default}")
        elif isinstance(default, list):
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                result[key] = value
            else:
                warning(f"文本处理配置 {label} 应为字符串列表，已使用默认值")
        elif isinstance(value, type(default)):
            result[key] = value
        else:
            warning(f"文本处理配置 {label} 类型不正确，已使用默认值 {default!r}")
    return result


def load_text_processing_config(config_file=None, *, info=None, warning=None):
    """读取配置；缺失时生成完整模板，非法字段独立回退默认值。"""
    info = info or logger.info
    warning = warning or logger.warning
    config_file = config_file or default_text_processing_config_path()
    path = Path(config_file)
    if not path.is_file():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(TEXT_PROCESSING_SAMPLE, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            info(f"未找到文本处理配置文件，已生成默认模板: {path}")
        except OSError as error:
            warning(f"无法创建文本处理配置文件 {path}: {error}")
        return copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        warning(f"文本处理配置文件解析失败（{path}），使用默认值: {error}")
        return copy.deepcopy(TEXT_PROCESSING_DEFAULTS)
    return _merge_known_settings(TEXT_PROCESSING_DEFAULTS, data, "", warning)
