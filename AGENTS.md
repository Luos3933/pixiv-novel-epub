# AGENTS.md

Pixiv 小说下载与自动整理工具包。下载 Pixiv 小说正文及插图，自动维护章节索引与元数据；下载后通过三层流水线（原始 → 标准化 → 校正）完成成书整理。

## 快速命令

```bash
# 下载（cli.py 为唯一入口，pixiv_novel_scraper.py 直接运行会委托给它）
python cli.py series <系列ID>                    # 下载整个系列（默认跳过已存在章节）
python cli.py series <系列ID> --workers 3        # 并发下载
python cli.py series <系列ID> --chapters 11-21   # 按区间下载
python cli.py retry series <系列ID>              # 一键补跑缺失章节
python cli.py novel <小说ID> --chapter <编号> --force

# 后处理（txt_file_processing.py）
python txt_file_processing.py format <章节目录> [输出目录] --punct  # 标准化：重命名+注入标题+标点转换+生成 000 书籍信息.txt（输出目录缺省时用同级 standardized/）
python txt_file_processing.py merge <标准化目录> <校正目录> <输出txt> # 多目录合并，校正优先，--info 刷新字数（默认开），--volumes 卷名插入，--indent 正文首行缩进（两全角空格，标题/卷名/000 不缩进）
python txt_file_processing.py diff <标准化> <校正> [报告.txt]         # 目录级对比
python txt_file_processing.py note add <校正目录> <编号> --msg "..."  # 修订说明
python txt_file_processing.py assemble <标准化> <校正> <final目录>    # 可选：只合成分章目录
python txt_file_processing.py split <原始目录> <输出目录> [--punct] [--name-only] [--title-len-limit]  # 拆卷：一卷一个文件拆为独立章节+生成 volumes.json
python txt_file_processing.py epub <目录1> [<目录2> ...] <输出.epub>  # 打包 EPUB（多目录校正版优先；--title/--author 覆盖元数据；--volumes 导入卷/篇配置；--title-style/--vol-style 调用样式预设 / --title-styles 列表 / --title-align/--title-color/--title-size/--title-underline 覆盖预设；--cover 指定封面，默认自动识别 cover.*/封面.*；--illustrations 插图信息文件，默认自动识别插图信息.txt）

# 日志：logs/download.log 与 logs/postprocess.log（追加，超 1MB 自动归档到 logs/archive/）
```

## 架构

| 文件 | 职责 |
|---|---|
| `pixiv_novel_scraper.py` | `PixivNovelScraper` 类：HTTP 请求（带重试/限速）、章节/系列下载、插图抓取、系列封面下载（`download_series_cover`，cover.urls 回退链 original→480mw→1200x1200→240x480，已存在 cover.* 跳过）、CSV/metadata/summary 索引维护。模块级纯函数：`clean_filename`/`clean_html`/`parse_chapter_selection`/`extract_tag_names` |
| `cli.py` | argparse 子命令入口（novel/csv/series/retry），无参数时进交互菜单；日志由 `log_setup` 配置 |
| `txt_file_processing.py` | 后处理 9 个子命令（merge/format/format-single/compare/punct/diff/note/assemble/split/epub）；核心类 `TxtFileMerger`/`BatchTxtFileFormatter`/`BookInfoGenerator`/`DirectoryDiffer`/`RevisionsStore`/`DirectoryAssembler`/`VolumeSplitter`/`EpubBuilder` |
| `log_setup.py` | 共享日志配置：固定文件名追加 + 超阈值归档到 logs/archive/ |
| `pixiv_cookie.txt` | 登录 Cookie（已 gitignore，不提交） |

## 三层流水线工作流

```
series/series_<ID>/
├── chapters/          # ① 下载原始（不动）
├── standardized/      # ② format --punct 输出（含自动生成的 000 书籍信息.txt）
├── corrected/         # ③ 人工校正（只放改过的文件 + _revisions.json）
└── final/             # ④ assemble 输出（可选）
```

- `format` 自动生成 `000 书籍信息.txt`：有 `series_<ID>_info.txt` 则套模板填充，否则空白占位
- `merge` 多目录时**后列的目录优先**（`merge standardized/ corrected/ out.txt`），按文件名开头数字前缀配对
- `diff`/`note`/`assemble`/`epub` 均按**数字前缀**配对（允许校正阶段改名），无前缀文件回退完整文件名
- **EPUB 打包**（`epub` 子命令，纯标准库 zipfile，零新依赖）：mimetype 首个且 ZIP_STORED 不压缩；container.xml + content.opf + 双目录（toc.ncx/nav.xhtml）+ style.css 中文排版 + 每章 chap_<编号>.xhtml；元数据优先解析 `000 书籍信息.txt`，其次回退 pixiv info/metadata，`--title`/`--author` 可覆盖；正文首段与文件名标题一致时自动去重（format 注入的标题行）
- **卷/篇**（`epub --volumes <json>` / `merge --volumes <json>`）：JSON 列表 `[{"name": "第一卷", "start": 1, "end": 17}]` 按章节数字前缀范围定义卷（`_load_volumes_file` 模块级函数共用）；epub 每卷生成独立占页的 `vol_<n>.xhtml`（`.volume-page` 强制分页 + `.volume-title` 垂直居中），toc.ncx/nav.xhtml 目录中卷为父级、其章节嵌套为子级（按 vol 标记配对，playOrder 父先子后）；游离章保持一级；范围内无章节的卷跳过；merge 在卷首章前插入卷名行并在 000 补充 `卷/篇数：N`（无卷配置时删除该行）
- **章标题样式**（`epub --title-align/--title-color/--title-size/--title-underline`）：CSS 模板含 `{chapter_title_css}` 占位（其余花括号已转义 `{{}}`），由 `_build_title_css()` 生成 h1.chapter-title 规则；颜色/字号有白名单正则校验，非法值忽略并警告
- **样式预设**（`epub_styles.json` 项目根目录，缺失时自动生成示例）：分 `chapter`/`volume` 两段；`--title-style <名称>` 调 chapter 段 / `--vol-style <名称>` 调 volume 段 / `--title-styles` 列表（可省略位置参数）/ `--title-styles-file` 自定义路径；显式样式参数覆盖预设（`EpubBuilder.load_presets` 为可独立调用的类方法）
- **拆两行标题**（预设字段 `split: true`）：`EpubBuilder._split_title` 把标题拆为章节号+章名（识别 `第X章/第X话/第X回`、`番外：xxx`）；`_build_title_html` 生成 `<span class="chapter-num">` + `<span class="chapter-name">` 两行，`_build_title_css` 输出各自 color/size 规则；无法识别时保持单行
- **书籍信息页**（有来源才生成）：`_find_book_info` 返回 `(info, found)`，found 时 spine 首位插入 `book_info.xhtml`（`BOOK_INFO_TEMPLATE` + `_build_book_info_body` 按 000 段落格式渲染，`--title/--author` 覆盖优先），目录顶部同步条目；纯占位无来源时不生成
- **封面**（`EpubBuilder._find_cover`）：`--cover` 显式指定优先（不存在报错中止），否则自动查找输入目录及父目录下 `cover.*`/`封面.*`；命中时 spine 首位生成 `cover.xhtml`（`COVER_TEMPLATE`，图片自适应），OPF 加 `properties="cover-image"` + `<meta name="cover">` + guide 引用（EPUB2/3 双兼容），目录顶部同步「封面」条目
- **插图**（`EpubBuilder` 插图系列方法）：正文 `【插图: 文件名】` 标记经 `_render_inline_illustrations` 原位内嵌（`ILLUSTRATION_MARKER_RE`，混排自动拆分）；图片经 `_find_image` 在输入目录及父目录的 `插图库/`/`illustrations/` 查找，缺失保留原文标记并告警；`_parse_illustrations_file` 按首字符自动分发 txt/JSON 两种格式（`_parse_illustrations_txt`：`ch<编号>` 文件名或 3 位数字章节头归属；`_parse_illustrations_json`：chapter 字段优先、缺省回退 ch 编号），描述行居中渲染 `.illustration-desc`（多行 `<br/>`），条目追加到对应章末；嵌入图写入 `OEBPS/img/` 并登记 manifest
- **插图压缩**（`--image-quality <1-100>`）：`_maybe_compress_image` 用 Pillow 重编码为 JPEG（`<原名>_q<质量>.jpg`，src/manifest 同步新名），压缩后未变小保留原图；无 Pillow 跳过并提示
- **拆卷**（`split` 子命令，`VolumeSplitter` 类）：识别卷内 `第X章/番外` 独立标记行（编号后须空格/冒号/行尾，或**无空格但不含句号**——核心判定靠句号，`--title-len-limit` 可选加 ≤20 字限制），按出现顺序重排作者编号错误（以首个标记编号为起点，中文/阿拉伯风格保持，番外不占编号），全局连续编号导出 `<3位> <标题>.txt`；默认文件名含完整章节标题，`--name-only` 时只留章节名（完整标题保留文件首行，`_chapter_name` 去前缀）；**无空格标记重排后自动补空格**；过滤 `series_*` 索引文件；volumes.json 写到输出目录上级锚定每卷全局章节范围；末尾自动生成 `000 书籍信息.txt`（同 format）；无标记文件整文件导出为单章
- **卷名样式**（`volume` 段字段 `vol_split` 默认 True）：`EpubBuilder._split_volume_title` 拆卷号+卷名（`第X卷/部/篇/集`、`番外篇`），`_build_volume_html` 生成 `.volume-num`/`.volume-name` 两个 span，`_build_volume_css` 输出各自 color/size + `vol_gap` 间距（CSS 模板占位 `{volume_title_css}`）；无法识别时单行但仍包 `.volume-name` span（防掉回正文默认样式），`vol_split: false` 时样式作用于 `.volume-title`
- **样式预设两段式**：`epub_styles.json` 分 `chapter`/`volume` 两段，`load_presets` 返回 `{"chapter": {...}, "volume": {...}}`（旧版扁平格式按 chapter 段兼容）；`--title-style` 取 chapter 段、`--vol-style` 取 volume 段；`EpubBuilder` 用独立 `title_style`/`vol_style` 两个 dict（各有 DEFAULT_*_STYLE）
- **epub 章节标题解析**：`_resolve_chapter_title` 优先取文件首行章节标记行（第X章/番外）作标题并 skip_first 剔除正文首行，否则用文件名推导；旧命名 standardized 重跑 split 前需清空旧 txt（防前缀冲突）

## 关键约定

- **字数统计**：网页口径 = 单章详情接口 `textCount` 累加（metadata.json）；`series_content` 接口的 `textCount` 偏小不可用。`download_series` 下载完成后会用 metadata 累加值修正 info.txt
- **文件名规则**：`<3位数字编号> <标题>.txt`，如 `043 第四十三章 xxx.txt`；`000` 前缀保留给书籍信息；标题含"番外"不递增正文章节计数
- **索引文件**：`_records.csv`（章节号↔小说ID）、`_metadata.json`（真值源）、`_summary.txt`（派生）、`_revisions.json`（人工修订说明）、`_source_map.txt`（assemble 来源映射）
- **编码**：全部 UTF-8；控制台日志走 `TqdmLoggingHandler`（tqdm.write）避免打断进度条
- **代码风格**：中文注释与 docstring；类方法命名 `build_*`（路径构建）/`save_*`（索引写入）；索引写入用 `self._index_lock` 加锁（并发 workers>1 时）

## 验证

每次改动后运行：

```bash
python -m py_compile cli.py pixiv_novel_scraper.py txt_file_processing.py log_setup.py
```

新命令需跑 `python xxx.py <命令> --help` 确认注册成功。测试不要删除用户 `logs/` 下的历史日志（`Remove-Item logs` 仅限临时测试产物，测试后恢复干净）。
