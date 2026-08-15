# pixiv-novel-epub — Pixiv 小说下载与 EPUB 整理工具包

从 Pixiv 下载系列/单章小说正文及插图，并自动维护章节索引、元数据与简介汇总；下载完成后可配合 `txt_file_processing.py` 进行拆卷、合并、标准化、校正、比对与 EPUB 打包，通过「原始 → 标准化 → 校正」三层流水线完成成书整理。

> 约定：命令中的 `<内容>` 为必填项，`[内容]` 为选填项。

## 依赖

```bash
pip install -r requirements.txt
```

## 配置登录态

Pixiv 的多数接口需要登录态。首次使用前：

**① 把模板文件变成 `pixiv_cookie.txt`**（两种方式任选，文件管理器右键改名也行）：

```bash
# 方式一：重命名（简单直接，但模板文件不再保留）
ren pixiv_cookie.example.txt pixiv_cookie.txt        # Windows
mv pixiv_cookie.example.txt pixiv_cookie.txt         # Linux / macOS

# 方式二：复制（推荐，保留模板，不破坏项目文件完整性）
copy pixiv_cookie.example.txt pixiv_cookie.txt       # Windows
cp pixiv_cookie.example.txt pixiv_cookie.txt         # Linux / macOS
```

**② 把浏览器中 `www.pixiv.net` 的登录 Cookie**（`F12 → Network → 任意请求 → Headers → Cookie` 的完整内容）粘贴进 `pixiv_cookie.txt` 并保存。

注意：

- 文件里**只放 Cookie 内容本身**，不要带 `Cookie:` 前缀、不要有多余换行或空格
- `pixiv_cookie.txt` 已被 `.gitignore` 忽略，**不会提交到仓库**（隐私安全）；模板 `pixiv_cookie.example.txt` 可以正常提交
- Cookie 会过期（几周到几个月），遇到 `401 Unauthorized` 时重新复制粘贴一次即可

## 快速使用

### 0. 准备工作

打开终端，切换到项目目录：

```bash
cd /目录/pixiv-novel-epub
```

### 1. 获取小说 ID

在 Pixiv 中打开目标小说，**网址数字部分即为小说 ID**：

![Pixiv 网址中的小说 ID](/docs/images/Snipaste_2026-08-13_19-52-56.png)

### 2. 下载系列小说

```bash
python cli.py series <小说ID>
```

下载完成后，章节正文与插图存放在 `series/series_<ID>/` 中：

![下载完成后的目录结构](/docs/images/Snipaste_2026-08-13_20-06-50.png)

### 3. 格式化章节

将下载的章节批量标准化（重命名 + 注入标题 + 段落空行；`--punct` 同时转换中文标点）。输出目录缺省时自动写入 `series/series_<ID>/standardized/`：

```bash
python txt_file_processing.py format "series/series_<ID>" [输出目录] [--punct]
```

### 4. （可选）人工修订

对不满意的章节进行人工修订，把**改过的文件**放进 `corrected/` 目录（未改的章节后续会自动取 standardized 版）；本步骤可跳过。

### 5. 生成成书

**未修订**时直接基于 `standardized/` 输出；**已修订**时在命令中追加 `corrected/` 目录（校正版优先）。

生成全本 txt：

```bash
# 未修订
python txt_file_processing.py merge "series/series_<ID>/standardized" "series/series_<ID>/全书.txt"

# 已修订
python txt_file_processing.py merge "series/series_<ID>/standardized" "series/series_<ID>/corrected" "series/series_<ID>/全书.txt"
```

生成 EPUB（自动加载封面/插图、按 `000 书籍信息.txt` 填充元数据）：

```bash
# 未修订
python txt_file_processing.py epub "series/series_<ID>/standardized" "series/series_<ID>/全书.epub"

# 已修订
python txt_file_processing.py epub "series/series_<ID>/standardized" "series/series_<ID>/corrected" "series/series_<ID>/全书.epub"
```

最终成书效果：

![最终 EPUB 阅读效果](/docs/images/Snipaste_2026-08-13_20-26-04.png)
## 下载：cli.py（唯一命令行入口）

`cli.py` 是下载的唯一入口（`pixiv_novel_scraper.py` 直接运行会委托给它）；不带任何参数时进入交互式菜单。

### 子命令

| 命令 | 作用 |
|---|---|
| `python cli.py novel <小说ID> --chapter <编号>` | 下载单章正文到 `novels/novel_<ID>/chapters/` |
| `python cli.py csv [csv路径]` | 按 CSV（默认 `import_records.csv`）「编号,小说ID」逐行批量下载 |
| `python cli.py series <系列ID>` | 整系列下载（自动分页遍历，默认跳过已存在章节） |
| `python cli.py retry <novel\|series> <ID>` | 按现有 `*_records.csv` 找出本地缺失章节一键补跑 |

### 常用选项

```bash
python cli.py series 123456789                      # 下载全系列（默认跳过已存在章节）
python cli.py series 123456789 --chapters 11-21     # 只下指定章节区间
python cli.py series 123456789 --from 30            # 从第 30 章开始（编号沿用原始章节号）
python cli.py series 123456789 --index-only         # 只更新 CSV 索引，不下载正文
python cli.py series 123456789 --workers 3          # 3 线程并发下载
python cli.py series 123456789 --force              # 覆盖已存在的章节
python cli.py novel 123456789 --chapter 11 --force  # 强制覆盖单章
python cli.py retry series 123456789                # 补跑缺失章节（支持 --force）
python cli.py                                       # 无参数进入交互式菜单
```

说明：

- **断点续传**：默认跳过本地已存在的章节文件，重跑不会重复下载；`--force` 强制覆盖
- **下载内容**：正文 txt（`[newpage]` 转换行、插图标记替换为本地「【插图: xxx】」）+ 插图自动抓取 + **系列封面自动下载**（保存为 `series/series_<ID>/cover.jpg`，已存在则跳过）+ 三类索引（`_records.csv` / `_metadata.json` / `_summary.txt`）同步维护 + 系列 `info.txt` 与目录总表
- **日志**：`logs/download.log`（追加写入，超 1MB 自动归档到 `logs/archive/`）

### 输出结构

```
novels/novel_<ID>/
├── chapters/                # 章节正文 txt
├── 插图库/                  # 章节插图（新下载默认 illustrations/，检测到旧目录时沿用旧名）
├── novel_<ID>_records.csv   # 章节号 ↔ 小说 ID 映射
├── novel_<ID>_metadata.json # 章节元数据
└── novel_<ID>_summary.txt   # 章节简介汇总

series/series_<ID>/
├── chapters/
├── 插图库/
├── series_<ID>_records.csv
├── series_<ID>_metadata.json
├── series_<ID>_summary.txt
└── series_<ID>_info.txt     # 系列说明（作者、标签、简介、字数等）
```

`series/_catalog.csv` 维护所有已下载系列的 ID 与名称对照表。

## 整理：txt_file_processing.py

下载并完成人工校对后，使用子命令进行后处理（不会在下载时自动调用，保留校对时间窗口）：

```bash
# 按章节顺序合并一个或多个目录下所有 txt 为单个文件。
# 多目录时按数字前缀配对，后列的目录优先（如 corrected/ 覆盖 standardized/）；
# --info 默认开启，合并前根据实际参与合并的章节重新统计字数并刷新 000 书籍信息.txt 的『字数』行。
python txt_file_processing.py merge <输入目录1> [<输入目录2> ...] <输出文件>
# 例：把改过的章节放在 corrected/、未改的留在 standardized/
python txt_file_processing.py merge standardized/ corrected/ 全书.txt
# 关闭字数刷新：
python txt_file_processing.py merge standardized/ corrected/ 全书.txt --no-info
# 卷名插入：--volumes 同 epub 格式（每卷第一章前插入卷名行，split 生成的 volumes.json 可直接用；
# 000 书籍信息会补充"卷/篇数：N"行）
python txt_file_processing.py merge standardized/ corrected/ 全书.txt --volumes volumes.json
# 正文首行缩进：--indent 给正文段落加两个全角空格（标题/卷名/000 不缩进）
python txt_file_processing.py merge standardized/ corrected/ 全书.txt --indent

# 批量重命名 + 顶部注入章节标题（正文转中文数字，跳过番外）+ 段落空行
# 同时会自动在输出目录生成 "000 书籍信息.txt"：
#   - 若能找到 pixiv 系列目录下的 series_<ID>_info.txt，则自动套用模板填充
#     书名/作者/连载平台/连载状态(N章+M番外+日期)/字数/简介
#   - 找不到则生成空白占位模板由用户手填
# --punct：同时把正文英文标点转中文（! → ！、? → ？、" → 按全文奇偶配对 “ ”）；
#          不加 --punct 则只做重命名/标题/空行，标点保持原样
# 输出目录可省略：缺省时输出到输入目录同级的 standardized/
python txt_file_processing.py format <输入目录> [输出目录] [--punct]
# 例：format "series/series_<ID>/chapters" --punct   → 输出到 series/series_<ID>/standardized

# 为单个 txt 段落间加空行（不重命名、不注入标题、不转标点）
python txt_file_processing.py format-single <输入文件> <输出文件>

# 逐段比对两个 txt 并输出差异（用于校对：对比下载内容或修改前后；差异同时写日志，
# 第三个参数缺省时差异报告写 text_differences.txt）
python txt_file_processing.py compare <文件1> <文件2> [差异输出文件]

# 标点转换：英文 ! ? " 转中文 ！？“ ”（引号按全文奇偶配对，奇数个会告警；
# ' 不处理以避免误伤英文撇号）
python txt_file_processing.py punct <输入文件> [输出文件]   # 后者缺省则原地覆盖

# 拆卷：把"一卷一个文件、卷内章节未划分"的原始下载拆成独立章节
# （识别第X章/番外标记行、按顺序修正作者编号错误、全局连续编号），
# 同时在上级目录生成 volumes.json（锚定每卷全局章节范围，供 epub --volumes 用）
# 输出目录自动生成 000 书籍信息.txt（与 format 一致：有 series info 套模板，否则空白占位）
# 默认文件名含完整章节标题（003 第3章 雪棠.txt）；--name-only 时只留章节名
# （003 雪棠.txt，完整标题仍在文件首行）；--punct 同时把正文英文标点转中文
# --title-len-limit：严格模式，无空格标记额外要求 ≤20 字（默认关闭，靠"不含句号"判定）
python txt_file_processing.py split <原始目录> <输出目录> [--punct] [--name-only] [--title-len-limit]

# 打包 EPUB：多目录按数字前缀配对、后列优先（校正版覆盖标准化版），
# 元数据自动取自 000 书籍信息.txt（其次 pixiv 系列信息，--title/--author 可覆盖）
# 封面：自动识别输入目录/父目录下的 cover.* 或 封面.*（如下载器保存的封面），--cover 可指定
python txt_file_processing.py epub <目录1> [<目录2> ...] <输出.epub> [--cover 图片路径]

# 卷/篇支持：--volumes 导入 JSON 配置，每卷独立占页并作为目录的上级嵌套
# [{"name": "第一卷 示例卷名", "start": 1, "end": 17}, ...]
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --volumes volumes.json

# 插图支持：正文残留的【插图: xxx】标记自动原位内嵌图片（插图库/ 或 illustrations/ 中查找）
# 人工删掉标记后：插图信息文件（txt 或 JSON 两种格式，自动识别）条目放到对应章节末尾
# 压缩插图：--image-quality <1-100> 重编码为 JPEG 减小体积（需 Pillow，压缩后未变小则保留原图）
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --illustrations 插图信息.txt --image-quality 75

# 章标题样式可配置：对齐 / 颜色 / 字号 / 下划线
python txt_file_processing.py epub standardized/ corrected/ 全书.epub \
    --title-align left --title-color "#8B0000" --title-size 1.2em --title-underline

# 样式预设：存于 epub_styles.json（chapter 章标题 / volume 卷名 两段），按名称一键调用
python txt_file_processing.py epub --title-styles                       # 列出全部预设（可省略目录/输出参数）
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --title-style split_title --vol-style default
python txt_file_processing.py epub standardized/ 全书.epub --title-style default --title-align left
#   预设基础上微调：--title-align/--title-color/--title-size/--title-underline 优先级高于预设
#   （--no-title-underline 可关闭预设里的下划线）
# 拆两行：预设里 split:true + num_color/num_size（章节号行）与 color/size（章名行）各自可调
```

#### epub 其他参数

```bash
# 覆盖书名/作者（000 里是占位"未填"时用；优先级高于 000 书籍信息.txt 与 pixiv 信息）
python txt_file_processing.py epub standardized/ 全书.epub --title "书名" --author "作者"

# 自定义样式文件（默认项目根目录 epub_styles.json）
python txt_file_processing.py epub standardized/ 全书.epub --title-styles-file my_styles.json

# 卷名样式：在 epub_styles.json 的 "volume" 段加条目后按名调用，
# 可调卷号/卷名的颜色、字号与两行间距（vol_split 默认 True 拆两行）：
#   "my_vol": {"vol_split": true, "vol_num_color": "#555555", "vol_num_size": "1.2em",
#              "vol_color": "#8B0000", "vol_size": "2.5em", "vol_gap": "0.6em"}
python txt_file_processing.py epub standardized/ 全书.epub --vol-style my_vol

# 章标题拆两行：在 "chapter" 段条目里加 split:true（章节号/章名各自可调颜色字号）：
#   "my_split": {"split": true, "num_color": "#555555", "num_size": "1em",
#                "color": "#8B0000", "size": "1.4em", "align": "center", "underline": true}
python txt_file_processing.py epub standardized/ 全书.epub --title-style my_split
```

有书籍信息来源（000 书籍信息.txt 或 pixiv 信息）时，epub 会自动在书最前面生成「书籍信息」页（按 000 段落格式渲染，含书名/作者/连载平台/连载状态/字数/简介），并出现在目录顶部；没有信息来源则不生成。

路径参数可写相对路径（相对脚本所在目录）或绝对路径。

## 三层流水线工作流（推荐）

下载后保持原始下载文件不动，通过三层渐进式处理得到最终成书目录，每一步都生成日志可追溯：

```
series/series_<ID>/
├── chapters/          # ① 下载原始（不动，保持原始性）
├── standardized/      # ② 标准化（format --punct 输出）
├── corrected/         # ③ 校正（人工修改的子集 + _revisions.json）
└── final/             # ④ 合成（assemble 输出 + _source_map.txt）
```

### 完整流程示例

```bash
# 1) 标准化：批量化重命名 + 注入标题 + 加空行 + 标点转换
python txt_file_processing.py format "series/series_<ID>/chapters" "series/series_<ID>/standardized" --punct

# 2) 人工校正：把 standardized/ 需要改的 txt 拷到 corrected/ 再改
#    在 corrected/ 里只保留你改过的文件（未改的由 merge/epub 自动取 standardized 版）
#    顺手给改过的文件记一条修订说明：
python txt_file_processing.py note add "series/series_<ID>/corrected" "043 第一章 xxx.txt" --msg "删除作者 PS 与两处错字"

# 3) 对比查看：差异报告 + 完整日志
python txt_file_processing.py diff "series/series_<ID>/standardized" "series/series_<ID>/corrected" "diff_report.txt"

# 4) 查看修订记录
python txt_file_processing.py note list "series/series_<ID>/corrected"

# 5) 出成书 txt（推荐，一步到位）：
#    corrected/ 改过的取校正版，未改的取 standardized，合并成一个 txt；
#    --info 默认开启，合并输出开头的 000 书籍信息.txt 自动按实际合并字数刷新『字数』行。
python txt_file_processing.py merge "series/series_<ID>/standardized" "series/series_<ID>/corrected" "series/series_<ID>/全书.txt"

# 5') 可选：只要分章成书目录、不要单文件，再走 assemble（默认不开启）
python txt_file_processing.py assemble "series/series_<ID>/standardized" "series/series_<ID>/corrected" "series/series_<ID>/final"

# 6) 出 EPUB 电子书（纯标准库实现，零依赖）：校正版优先，未改的取 standardized
python txt_file_processing.py epub "series/series_<ID>/standardized" "series/series_<ID>/corrected" "series/series_<ID>/全书.epub"
#    只用单目录也行：epub "series/series_<ID>/final" 全书.epub
#    覆盖书名/作者：--title "..." --author "..."
```

### 三个新子命令要点

- **`diff <标准化> <校正> [报告]`**：**默认按文件名开头数字编号配对**，名字不同但编号一致视为同章节比对内容；同时识别五类信息：内容有改 / 仅改了文件名 / 内容一致 / 仅一侧（未校正或新增）；每处段落差异列出行号+第一个差异字符+两端原文。控制台每文件预览前 3 条差异（`--preview N` 可调整，默认 3）、日志与报告保留全部。无数字前缀的文件（如"附录.txt"）按完整文件名匹配。
- **`note <add|remove|list|clear> <校正目录> [文件名或编号] [--msg "..."]`**：维护校正目录下的 `_revisions.json`，**key 使用数字前缀编号**（如 `043`），允许校对时改了文件名也不会丢失修订记录。`add` 必须传 `--msg`；文件名参数可写完整名 `043 xxx.txt` 或纯编号 `043`，内部统一规范化为前缀。
- **`assemble <标准化> <校正> <输出>`**：**按数字前缀配对**合成最终目录；输出文件名优先采用校正版命名（你改过标题的章节用新标题），未改的取标准化命名；校正目录独有（新增）也进入最终目录；无数字前缀的文件按完整名匹配。自动生成 `_source_map.txt` 记录每文件来源与改名轨迹。

### split 拆卷要点

- **适用场景**：pixiv 系列中「一卷一个文件、卷内全部章节未划分」（如 series_123456789 每文件含 20+ 章）
- **识别规则**：独立成行（≤40 字）的 `第X章/第X话/第X节/第X回`（中文/阿拉伯数字，编号后跟空格/冒号/行尾，或**无空格但不含句号**的短标题如「第二章天使降临我身边？」；含句号视为正文）+ `番外：xxx`；`--title-len-limit` 可开启 ≤20 字严格模式（默认关闭，兼容长标题网文）
- **编号修正**：按出现顺序重排作者标号错误（重复/回退），以首个标记编号为起点；中文风格保持中文、阿拉伯保持阿拉伯；番外不占编号
- **输出**：`<3位全局编号> <章节标题>.txt`（跨卷连续；默认文件名含完整标题如 `003 第3章 雪棠.txt`，`--name-only` 时只留章节名如 `003 雪棠.txt`，完整标题始终保留在文件首行）；第一个标记前的卷标题/前言跳过；无标记的文件整文件导出为单章（不进卷）
- **volumes.json**：写到输出目录上级（series_xxx 目录），`{"name": "第一卷 xxx", "start": 1, "end": 27}` 锚定每卷全局章节范围，可直接 `epub --volumes` 使用

### epub 打包要点

- 结构（参照 FanFicFare / WebToEpub / lncrawl 的手写方案，仅用标准库 `zipfile`）：`mimetype` 首个且不压缩 + `container.xml` + `content.opf`（元数据/manifest/spine）+ 双目录（`toc.ncx` EPUB2 + `nav.xhtml` EPUB3）+ `style.css` 中文排版（首行缩进 2em、1.8 行距）+ 每章一个 `chap_<编号>.xhtml`
- 元数据：优先解析输入目录的 `000 书籍信息.txt`（书名/作者/简介/连载状态/字数），其次回退 pixiv `info.txt`/`metadata.json`，最后占位；`--title`/`--author` 可覆盖
- 章节正文首段若与文件名标题一致（`format` 注入的标题行），自动丢弃避免与 `<h1>` 重复
- **卷/篇**（`--volumes volumes.json`）：JSON 列表 `[{"name": "第一卷 xxx", "start": 1, "end": 17}]` 定义章节范围；每卷生成独立占页的 `vol_<n>.xhtml`（卷名垂直居中、前后强制分页），并在 `toc.ncx`/`nav.xhtml` 目录中作为章节的上级嵌套；不属于任何卷的游离章保持原顺序
- **卷名样式**（`volume` 段字段 `vol_split` 默认 True）：卷名拆两行显示——卷号行（`.volume-num`，`vol_num_color`/`vol_num_size` 控制，默认 `#555555`/`1.2em`）+ 卷名行（`.volume-name`，`vol_color`/`vol_size` 控制，默认 `#8B0000`/`2.5em`），`vol_gap` 控制两行间距（默认 `0.6em`）；识别 `第X卷/部/篇/集` 与 `番外篇`，无法识别的卷名保持单行；`vol_split: false` 时单行且样式作用于 `.volume-title`
- **章节标题解析**：章节文件首行若是 `第X章/番外` 标记行（split 拆卷输出），优先用它作为 EPUB 标题并剔除正文首行；否则用文件名推导标题
- **章标题样式**：`--title-align {center|left}` / `--title-color <颜色>` / `--title-size <字号>` / `--title-underline`（2px 实线，颜色同标题色，未设色默认深红 `#8B0000`）；如左对齐深红下划线：`--title-align left --title-color "#8B0000" --title-size 1.2em --title-underline`；非法 CSS 值自动忽略并警告
- **样式预设**（`epub_styles.json`，分 `chapter`（章标题，随项目提供 `default`/`split_title`）与 `volume`（卷名，提供 `default`）两段）：`--title-style <名称>` 调用章节样式、`--vol-style <名称>` 调用卷名样式、`--title-styles` 分两段列表、`--title-styles-file <路径>` 自定义文件；显式样式参数优先级高于预设，`--no-title-underline` 可关闭预设的下划线；文件缺失时自动生成示例模板
- **拆两行标题**（预设字段 `split: true`）：`第一章`（`.chapter-num`，`num_color`/`num_size` 控制）+ 章名（`.chapter-name`，`color`/`size` 控制）分两行；识别 `第X章/第X话/第X回`（编号后须空格）与 `番外：xxx`；无法识别的标题保持单行
- **书籍信息页**：有 `000 书籍信息.txt`（或 pixiv info/metadata）来源时，spine 第一位自动生成 `book_info.xhtml`（按 000 段落格式：书名/作者/连载平台/连载状态/字数/简介），目录顶部同步「书籍信息」条目；纯占位无来源时不生成
- **封面**：自动查找输入目录及父目录下的 `cover.*` / `封面.*` 图片（下载器会保存到 `series_xxx/cover.jpg`），生成 spine 第一位的 `cover.xhtml`（图片自适应页面，目录顶部有「封面」条目），OPF 双规范兼容（EPUB3 `properties="cover-image"` + EPUB2 `<meta name="cover">`/guide）；`--cover <路径>` 显式指定（不存在则报错中止）；无封面时不生成
- **插图**：正文中的 `【插图: 文件名】` 标记在对应位置内嵌为居中图片（与文字混排自动拆分），图片从 `插图库/`/`illustrations/` 查找；找不到图片保留原文标记并告警。人工删掉标记后可提供插图信息文件（`--illustrations <文件>` 指定，缺省自动找输入目录里的 `插图信息.txt`/`插图信息.json`），**txt 与 JSON 两种格式自动识别**：
  - txt：`【插图: xxx】` 条目 + 下方描述行，`ch<编号>` 文件名或 `<编号>` 章节头（3 位数字行）决定归属章节
  - JSON：`[{"chapter": 41, "img": "ch041_xxx.jpg", "desc": "描述"}, ...]`（chapter 支持数字/字符串，缺省回退文件名 ch 编号）
  - 插图与描述（居中小号灰字，多行 `<br/>` 分隔）放到该章末尾；图片缺失/无法确定章节的条目跳过并警告
- **插图压缩**（`--image-quality <1-100>`）：把插图重编码为 JPEG 减小体积（需 `pip install Pillow`；压缩后未变小保留原图；实测 17 张 19MB 插图压到 3.4MB，EPUB 从 21MB 降到 6MB）

### 日志

所有后处理命令都会写日志到 `logs/postprocess.log`（追加），与下载器的 `logs/download.log` 平级区分；任一文件超过 1 MB 时会自动归档到 `logs/archive/<base>_<时间戳>.log`，历史可查又不杂乱。