"""拆卷识别配置的默认值、模板和加载。"""

import json
import logging
import os
from pathlib import Path


logger = logging.getLogger("pixiv_novel_toolkit.postprocess")

SPLIT_CONFIG_DEFAULTS = {
    "chapter_gap_limit": 10,
    "marker_max_len": 40,
}

SPLIT_CONFIG_SAMPLE = {
    "_说明": {
        "chapter_gap_limit": "章节编号连续性校验：新识别编号比最高编号回退超过该值时"
        "不视为章节标记（并入上一章正文，记入 _编号统计.txt 的"
        "「被连续性校验拒绝」清单；同号同题重发放行）；前向跳变"
        "不校验（缺号块正常）；0 或 null 关闭校验",
        "marker_max_len": "章节标记行最大长度（整行字符数），超过视为正文行",
    },
    **SPLIT_CONFIG_DEFAULTS,
}


def default_split_config_path():
    """返回与旧入口脚本同级的项目根目录配置路径。"""
    return str(Path(__file__).resolve().parents[2] / "split_config.json")


def load_split_config(config_file=None, *, info=None, warning=None):
    """读取配置，缺失时生成模板，非法单键回退默认值。"""
    info = info or logger.info
    warning = warning or logger.warning
    config = dict(SPLIT_CONFIG_DEFAULTS)
    config_file = config_file or default_split_config_path()
    if not os.path.isfile(config_file):
        try:
            with open(config_file, "w", encoding="utf-8") as file:
                file.write(json.dumps(SPLIT_CONFIG_SAMPLE, ensure_ascii=False, indent=4) + "\n")
            info(f"未找到拆分配置文件，已生成默认模板: {config_file}")
        except OSError as error:
            warning(f"无法创建拆分配置文件 {config_file}: {error}")
        return config
    try:
        with open(config_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        warning(f"拆分配置文件解析失败（{config_file}），使用默认值: {error}")
        return config
    if not isinstance(data, dict):
        warning(f"拆分配置文件应为 JSON 对象，使用默认值: {config_file}")
        return config
    for key, default in SPLIT_CONFIG_DEFAULTS.items():
        value = data.get(key, default)
        if value is None:
            config[key] = 0
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            warning(
                f"拆分配置 {key} 应为非负整数或 null，收到 {value!r}，"
                f"使用默认值 {default}"
            )
        else:
            config[key] = value
    return config
