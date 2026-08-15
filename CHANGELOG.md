# Changelog

### v0.8.13 - 2026-08-13

使用 `--volumes` 时，000 书籍信息补充**卷/篇数**行；epub 书籍信息页同步显示。

#### 新增

- `update_word_count_for_merge` 新增 `volumes` 参数：有卷配置时在「连载状态」行后插入/更新 `卷/篇数：N` 行；**无卷配置时删除已有的卷/篇数行**（用户取消分卷后不留残留）
- merge（`--volumes`）与 epub（`--volumes`）生成时自动写入；重复执行不产生重复行
- epub 书籍信息页：`_parse_book_info_file` 解析 `卷/篇数/卷数/分卷` 字段，`_build_book_info_body` 在连载状态后渲染

#### 000 书籍信息效果

```
连载状态：142章（2026年3月6日）
卷/篇数：5
字数：69.9万字
```

#### 验证

- 6 项全过：卷/篇数行存在且位置正确、无卷配置删除残留、epub 刷新与书籍信息页同步、重复执行无重复行
- 全量 17 套回归全过

### v0.8.12 - 2026-08-13

`merge` 新增**正文首行缩进**：`--indent` 给正文段落加两个全角空格（中文排版惯例）。

#### 新增

- `merge ... --indent`：正文段落前加两个全角空格 `　　` 缩进；以下内容**不缩进**：
  - `000 书籍信息.txt`（整段）
  - 章节标题行（每个章节文件首行）
  - 卷名行（`--volumes` 插入的）
- 默认关闭（不带 `--indent` 行为与旧版完全一致）

#### 验证

- 6 项全过：正文缩进、标题/卷名/000 不缩进、默认不缩进回归
- 全量 16 套回归全过

### v0.8.11 - 2026-08-13

`merge` 新增**卷名插入**：`merge --volumes <json>` 在每卷第一章前插入卷名行（与 epub 同格式配置，纯文本版的分卷标记）。

#### 新增

- `merge <目录1> [<目录2> ...] <输出.txt> --volumes volumes.json`：
  - 每卷范围内第一章前插入 `空行 + 卷名 + 空行`（独立成段，与章节间空行区分）
  - 卷配置格式与 epub `--volumes` 完全一致（`[{"name": "第一卷 示例卷名", "start": 1, "end": 17}]`），split 生成的 volumes.json 可直接复用
  - 000 书籍信息仍排最前；卷配置无效时中止合并
- 卷配置解析提取为模块级 `_load_volumes_file`（merge / epub 共用），`EpubBuilder._load_volumes` 委托给它

#### 用法

```bash
python txt_file_processing.py merge standardized/ corrected/ 全书.txt --volumes volumes.json
```

#### 验证

- 7 项全过：每卷名出现且独立成段、卷序正确、000 在最前、无卷配置行为不变、无效配置中止
- 全量 15 套回归全过

### v0.8.10 - 2026-08-13

`split` 拆卷后**自动生成 `000 书籍信息.txt`**（与 `format` 行为一致），卷系列拆完直接可用 epub 出书籍信息页。

#### 变更

- `VolumeSplitter.split()` 末尾（生成 volumes.json 之后）调用 `BookInfoGenerator(self.input_dir).generate(self.output_dir)`：
  - 输入目录上级能找到 `series_*_info.txt` → 套模板填充（书名/作者/连载平台/连载状态/字数/简介）
  - 找不到 → 空白占位模板（与 format 相同）
- 章节数/字数在后续 merge/epub 时仍会被 v0.8.5 的「每次生成重新统计」自动修正为实际值

#### 验证

- 真实数据：000 生成且字段齐全（书名/作者/平台/状态/字数/简介）
- split mock 加 T3b 断言；e2e spine/NCX 结构更新（书籍信息页居首）；全量 14 套回归全过

### v0.8.9 - 2026-08-13

无空格章节标记重排编号后**自动补空格**，输出统一为「编号 + 空格 + 章名」。

#### 变更

- `VolumeSplitter._renumber_segments`：原标记编号后是空格/冒号则保留原样；**无空格（作者漏写）时重排后在编号与章名之间补一个空格**，输出 `第二十二章 天使降临我身边？` 而非 `第二十二章天使降临我身边？`
- 文件名与文件首行同步修正；epub 标题解析（无空格规则）不受影响

#### 验证

- 真实数据：`003 第二十二章 天使降临我身边？.txt`（编号与章名间有空格）
- mock T4b 补空格专项 + 全量 14 套回归全过

### v0.8.8 - 2026-08-13

无空格章节标记判定调整：**长度限制改为可选开关（默认关闭）**，核心判定只靠「不含句号」。

#### 变更

- 无空格的 `第X章xxx` 行判定为章节标题：**核心条件 = 不含句号「。」**（标题是短语，可带？！；正文段落必有句号等句子终止符）——不再默认限制长度，兼容标题较长的网文
- 新增 `split --title-len-limit`（严格模式，默认关闭）：开启后额外要求整行 ≤ 20 字符，进一步防正文长句误判（代价：可能误伤长标题）
- `VolumeSplitter._parse_marker` / `_renumber_segments` 改为实例方法（访问开关）；epub 的章节标题解析调用保持默认行为

#### 验证

- 默认模式：29 字长标题（无句号）识别为章节；严格模式：长标题不识别、短标题仍识别
- 真实数据 142 章不变；全量 14 套回归全过

### v0.8.7 - 2026-08-13

修复：**作者漏写空格导致章节标记漏识别**（如「第二章天使降临我身边？」被并入上一章正文）。

#### 修复

- `VolumeSplitter._parse_marker` 放宽守卫：编号后跟空格/冒号/行尾 → 肯定是标记（不变）；**编号后直接跟文字**（作者漏写空格）时，整行 ≤ 20 字符（章节标题通常很短）也识别为章节标记，更长视为正文（保留「第三章的约定就这样被打破了…」这类正文行的误判防护）
- 真实数据 series_123456789 的 001 卷：`第二章天使降临我身边？`（无空格）现在被正确拆为独立章节，并参与后续编号重排（按顺序变为第二十二章）
- 副作用：该系列章节数 139 → 142（多拆出漏掉的章节），编号修正 49 → 41

#### 验证

- mock：无空格标题（`第十九章天使降临`）正确拆分且重排编号；长正文行（`第三章的约定…`）不误判；番外/阿拉伯编号/无标记文件回归
- 真实数据 e2e：142 章、卷1 子章数与 volumes.json 一致；全量 14 套回归全过

### v0.8.6 - 2026-08-13

`epub` 新增**插图压缩**：`--image-quality <1-100>` 把插图重编码为 JPEG 显著减小体积。

#### 新增

- **`--image-quality <1-100>`**：启用插图压缩（JPEG 重编码，需安装 Pillow）：
  - PNG / JPEG 均支持；`convert('RGB')` + `save(JPEG, quality=N, optimize=True)`
  - **压缩后未变小则保留原图**（纯色/小图不劣化）
  - 压缩后的文件名为 `<原名>_q<质量>.jpg`，正文 src 与 OPF manifest 同步使用新名（mime 按扩展名自动为 image/jpeg）
  - 同一张图多处引用只压缩一次（`_used_images` 去重）
- 未安装 Pillow 时跳过压缩并提示（`requirements.txt` 补充可选依赖注释）
- 质量越界（非 1-100）忽略并告警

#### 效果（真实数据 series_123456789，17 张插图）

| | 插图 | 整个 EPUB |
|---|---|---|
| 原样 | 19,079 KB | 21,497 KB |
| `--image-quality 75` | 3,450 KB（**-81.9%**） | 6,160 KB（**-71%**） |

#### 用法

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --image-quality 75
```

#### 验证

- 压缩 8 项全过：默认原样、压缩改名、变小、src/manifest 同步、有效 JPEG 且尺寸不变、纯色小图保留原图、越界忽略
- 全量 14 套回归全过

### v0.8.5 - 2026-08-13

**每次生成都重新统计书籍信息**：merge 与 epub 打包前按实际参与章节重算章节数与总字数，更新 000 书籍信息.txt（写回 corrected/），无需任何「是否修改过」的标志。

#### 变更

- `BookInfoGenerator.update_word_count_for_merge` 升级为完整刷新：
  - **字数**：按实际参与合并/打包的章节（配对去重、校正版优先）重算总字符数，更新「字数：X.X万字」行
  - **连载状态**：按实际章节重算「N章+M番外」（文件名含"番外"算番外），保留基底中的日期（YYYY年M月D日）
  - 其余字段（书名/作者/简介等）取自 mtime 最新的 000 基底
  - 刷新版写回优先级最高的源目录（通常是 corrected/）
- **epub 打包前也自动刷新**（`build()` 内调用，`search_parent=False` 只搜输入目录本身，避免误命中父目录其他系列的 000；merge 保留父目录搜索）
- 新增 `_collect_chapters_for_merge`（去重配对章节清单，字数/章节数/番外数共用）、`_count_chapters_for_merge`、`_find_book_info_direct`
- 效果：用户修改 corrected/ 内容后，任何一次 merge/epub 都会让书籍信息页/合并开头的 000 反映最新章节数与字数，不需要手动维护

#### 验证

- 重新生成场景 7 项全过：修改 corrected 后 merge/epub 章节数正确、字数按实际重算、书籍信息页同步
- mtime 基底 5 项全过；bookinfo/拆行/卷/样式/封面/插图等全量 13 套回归全过

### v0.8.4 - 2026-08-13

修复两个问题：微信读书中拆两行标题不换行；重新标准化后 000 书籍信息不更新。

#### 修复

1. **拆两行标题在微信读书不换行**：章节号/章名、卷号/卷名由 `<span>` + CSS `display:block` 改为**原生块级 `<div>`**（class 名不变）。微信读书等阅读器处理 EPUB 时会剥掉部分布局 CSS（如 display），span 会退回行内并成一行（只剩颜色/字号）；div 是原生块级元素，即使 CSS 被剥掉也天然换行。类名 `.chapter-num`/`.chapter-name`/`.volume-num`/`.volume-name` 不变，CSS 无需改动。
2. **重新 format 后 000 书籍信息不更新**：`merge --info` 与 epub 的 000 查找原来按目录优先级取第一个（corrected 里的旧 000 会挡住重新 format 生成的新 standardized/000）。改为**在多个候选 000 中取 mtime 最新**：
   - 重新 format 后的 standardized/000 时间新 → 新字段（章节数/连载状态/简介）作为基底，只刷新字数后写回 corrected/
   - 用户手改过 corrected/000（时间更新）→ 以用户手改内容为基底，保留手改字段
   - epub 只搜索输入目录本身（避免误命中父目录里其他系列的 000）

#### 验证

- div 拆分验证：章节标题/卷名正确输出两个 div（class 与文本正确）
- mtime 场景 5 项全过：旧 corrected + 新 standardized → 新字段生效、字数按实际合并刷新、用户手改保留
- 全量 11 套回归全过

### v0.8.3 - 2026-08-13

插图信息文件**同时支持 txt 与 JSON 两种格式**（按文件内容自动识别）。

#### 变更

- **JSON 格式**（结构严格、报错明确）：
  ```json
  [
      {"chapter": 41, "img": "ch041_up_22901790.jpg", "desc": "描述插画的信息"},
      {"chapter": "002", "img": "up_12345.png", "desc": "描述"}
  ]
  ```
  `chapter` 支持数字或 3 位字符串；缺省时回退文件名 `ch<编号>`；缺 `img`/章节无效的条目跳过并警告；`desc` 可多行
- **自动识别**：文件首字符为 `[`/`{` 时按 JSON 解析（失败则回退 txt 并警告）；否则按 txt 解析
- txt 解析改读 `utf-8-sig`（兼容带 BOM 的记事本文件）；自动查找扩展为 `插图信息.txt` / `插图信息.json` / `illustrations.json`
- `_parse_illustrations_txt` / `_parse_illustrations_json` 拆分，`_parse_illustrations_file` 负责格式分发

#### 验证

- JSON 格式 7 项全过：chapter 数字/字符串、ch 编号回退、描述多行 `<br/>`、非法条目跳过、非数组容错、伪 JSON 回退 txt
- txt 格式 12 项回归全过；全量 11 套回归全过

### v0.8.2 - 2026-08-13

`epub` 新增**插图支持**：正文残留的 `【插图: xxx】` 标记原位内嵌图片；人工删掉标记后可用「插图信息.txt」把插图放到对应章节末尾。

#### 新增

- **内嵌标记（默认）**：正文段落中的 `【插图: 文件名】`（全宽/半角冒号均可）在对应位置渲染为居中图片（`.illustration`），与文字混排的段落拆分为「文字 + 图片 + 文字」；图片从输入目录及父目录下的 `插图库/` 或 `illustrations/` 自动查找，打包进 `OEBPS/img/`；**找不到图片时保留原文标记并告警**，不让书悄悄少东西
- **插图信息文件**（人工校正删掉标记后的方案）：
  ```
  【插图: ch041_up_22901790.jpg】      ← ch<编号> 自动归属对应章节（pixiv 命名）
  描述插画的信息                         ← 图片下方居中显示（.illustration-desc，小号灰字）
  002                                  ← 可选章节头（3 位数字行，可单独成行）
  【插图: up_12345.png】               ← 无 ch 编号的条目按当前章节头归属
  描述
  ```
  - `--illustrations <文件>` 显式指定；不指定时自动查找输入目录中的 `插图信息.txt`（如 corrected/插图信息.txt）
  - 条目放到**对应章节末尾**；图片缺失/无法确定章节的条目跳过并警告
- OPF manifest 自动登记所有嵌入图片（mime 按扩展名）；无插图时行为与旧版一致

#### 用法

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --illustrations 插图信息.txt
```

#### 验证

- mock 12 项全过：内嵌独立/混排标记、图片进包与 manifest、章节头与 ch 编号两种归属、描述 class、缺失图片保留标记/跳过、自动识别 corrected/插图信息.txt、无插图回归
- 真实数据 series_123456789：17 张插图嵌入（ch040~ch059），041 章 2 个插图 div；全量 10 套回归全过

### v0.8.1 - 2026-08-13

`format` 命令的**输出目录改为可选**：只给输入目录时，默认输出到输入目录同级的 `standardized/`。

#### 变更

- `format <输入目录> [输出目录] [--punct]`：输出目录缺省时使用 `<输入目录上级>/standardized`（与三层流水线布局一致），并打印实际使用的输出路径
- 显式传输出目录的行为不变

### v0.8.0 - 2026-08-13

**封面支持**：下载器自动抓取系列封面；EPUB 自动加载封面，也可 `--cover` 指定图片。

#### 新增

- **下载器**（`pixiv_novel_scraper.py`）：
  - `download_series_cover(series_id, overview)`：从系列总览接口的 `cover.urls`（original → 480mw → 1200x1200 → 240x480 依次回退）下载封面到系列目录 `cover.<ext>`（按 URL 扩展名，默认 .jpg）
  - 已存在 `cover.*` 时跳过不重复下载；下载失败只告警，不影响正文流程
  - `download_series` 在总览获取成功后自动调用
- **EPUB**（`epub` 子命令）：
  - **自动识别封面**：查找输入目录及其父目录下的 `cover.*` / `封面.*`（jpg/png/gif/webp）——下载器保存的 `series_xxx/cover.jpg` 会被自动命中
  - **`--cover <图片路径>`**：显式指定封面（文件不存在时报错中止）
  - 封面页 `cover.xhtml` 位于 spine 第一位（书籍信息页之前），图片缩放自适应页面；目录（toc.ncx/nav.xhtml）顶部有「封面」条目
  - OPF 双规范兼容：manifest `properties="cover-image"`（EPUB3）+ `<meta name="cover">` 与 `<guide><reference type="cover">`（EPUB2）
- 无封面时不生成封面页（行为与旧版一致）

#### 用法

```bash
# 下载系列（自动下载封面到 series/series_<ID>/cover.jpg）
python cli.py series 123456789

# 打包（自动识别 series 目录下的 cover.*）
python txt_file_processing.py epub standardized/ corrected/ 全书.epub

# 或指定封面
python txt_file_processing.py epub standardized/ 全书.epub --cover 我的封面.png
```

#### 验证

- 封面 13 项全过：spine 首位、图片进包、img src、cover-image 属性与 MIME、EPUB2 meta/guide、NCX/nav 顶部条目、CSS、父目录自动识别、无封面不生成、不存在的 --cover 报错中止
- 全量 9 套回归全过

### v0.7.10 - 2026-08-13

修复：**无卷号的卷名在拆两行模式下掉回正文默认字号/颜色**。

#### 修复

- `_build_volume_html` 的单行回退路径（卷名不含 `第X卷/部/篇/集`/`番外篇`，或 `vol_split: false`）始终把卷名包进 `<span class="volume-name">`，使其继承 `.volume-name`（拆两行模式）或 `.volume-title`（单行模式）的字号/颜色——此前无卷号的卷名会以正文默认小字黑色显示
- 验证：无卷号卷名（山川篇等）渲染为 `.volume-name` span 且 CSS 含 `color: #8B0000`/`font-size: 2.5em`；卷样式 16 项 + 全量 8 套回归全过

### v0.7.9 - 2026-08-13

样式预设文件**拆分为 chapter / volume 两段**，卷名样式独立成段，由 `--vol-style` 单独调用（不再混在章标题预设里）。

#### 变更

- **`epub_styles.json` 两段结构**：
  ```json
  {
      "chapter": { "default": {...}, "split_title": {...} },
      "volume":  { "default": {...} }
  }
  ```
  `--title-style <名称>` 从 `chapter` 段取章标题样式；新增 `--vol-style <名称>` 从 `volume` 段取卷名样式；`--title-styles` 分两段列出
- 卷名样式字段（`vol_split` 默认 True / `vol_num_color` / `vol_num_size` / `vol_color` / `vol_size` / `vol_gap`）从章标题预设中移出，归入 `volume` 段；`EpubBuilder` 新增独立 `vol_style` 入参与 `DEFAULT_VOLUME_STYLE`，`_build_volume_html`/`_build_volume_css` 改用 `self.vol_style`
- `load_presets` 返回 `{"chapter": {...}, "volume": {...}}`；旧版扁平格式文件兼容读取（全部按 chapter 段处理并提示）
- 章节预设 `split_title` 不再包含卷名字段；`epub_styles.json` 已迁移为两段式

#### 用法

```bash
python txt_file_processing.py epub standardized/ 全书.epub \
    --title-style split_title --vol-style default
```

#### 验证

- 卷样式 16 项更新全过（volume 段解析、`vol_style` 入参、预设生效）
- CLI `--vol-style` 端到端：拆两行 + #555555 卷号生效
- 预设 9 项、样式/拆行/卷/书籍信息/拆卷/e2e 全量回归全过

### v0.7.8 - 2026-08-12

`epub` **卷名样式可配置**：默认拆两行（卷号小灰在上、卷名大号深红在下，中间留间距），字段并入样式预设。

#### 新增

- **卷名拆两行**（`vol_split`，**默认 True**）：`第一卷 示例卷名` 渲染为 `<span class="volume-num">第一卷</span>`（小号灰色）+ `<span class="volume-name">示例卷名</span>`（大号深红）
- **样式字段**（`epub_styles.json` 预设内，可自行编辑）：
  - `vol_split`：是否拆两行（默认 True；无法识别卷号的卷名如「示例系列（上）1-10章」自动回退单行）
  - `vol_num_color`（默认 `#555555`）/ `vol_num_size`（默认 `1.2em`）：卷号行颜色/字号
  - `vol_color`（默认 `#8B0000`）/ `vol_size`（默认 `2.5em`）：卷名行颜色/字号
  - `vol_gap`（默认 `0.6em`）：两行之间的间距
- 识别规则（`EpubBuilder._split_volume_title`）：`第X卷/部/篇/集` 与 `番外篇`；不匹配保持单行
- CSS 模板新增 `{volume_title_css}` 占位，由 `_build_volume_css()` 生成；`vol_split: false` 时字号/颜色直接作用于 `.volume-title`（行为与旧版一致）；颜色/字号/间距均有白名单正则校验
- `load_presets` 透传全部 vol_* 字段；`epub_styles.json` 与 `STYLE_SAMPLE` 示例已补充

#### 验证

- 卷样式 16 项全过：解析四种形态、默认拆两行 + 颜色/字号/间距/垂直居中、无卷号回退单行、关闭拆分自定义单行样式、预设透传与生效
- 真实数据回归：e2e（123456789 五卷拆两行）、无卷号卷名单行回退（123456789）；其余 7 套回归全过

### v0.7.7 - 2026-08-12

`split` 新增 `--name-only` 可选参数：文件名只保留章节名、不带章节号（默认仍含完整章节标题）；EPUB 章节标题改为优先取文件首行的章节标记行。

#### 变更

- **`split --name-only`**：文件名 `003 第3章 雪棠.txt` → `003 雪棠.txt`（`VolumeSplitter._chapter_name` 去掉 `第X章` 前缀；`番外：xxx` 保持原样；标题只有编号时回退完整标题）；**默认不带该参数时文件名仍含完整章节标题**（`003 第3章 雪棠.txt`）
- **epub 标题解析**（`EpubBuilder._resolve_chapter_title`）：章节文件首行若是 `第X章/番外` 标记行（如 split 拆卷输出），直接用它作为 EPUB 章节标题（h1/目录/NCX），并从正文剔除该行；否则仍用文件名推导标题（format 输出行为不变）。两种命名模式下 EPUB 标题都完整
- `_chapter_body` 增加 `skip_first` 参数

#### 验证

- split 11 项全过：默认模式（文件名含章节号）、--name-only 模式（只留章节名）、两种模式 volumes.json 一致、首行保留完整标题
- 拆卷 → epub 端到端 10 项全过（h1 = 文件首行「第一章 回家的诱惑」）
- 样式/拆行/卷/预设/书籍信息 5 套回归全过

### v0.7.6 - 2026-08-12

新增 `split` 子命令：**拆卷**——把 pixiv 系列中"一卷一个文件、卷内章节未划分"的原始下载内容拆成独立章节文件，并生成卷范围配置。

#### 新增

- **`split <原始目录> <输出目录> [--punct]`**（`VolumeSplitter` 类）：
  - 按文件名数字前缀顺序遍历卷文件，识别卷内章节标记行（独立成行、长度 ≤ 40）：
    `第一章 xxx` / `第11章 xxx` / `第一章：xxx`（中文/阿拉伯数字）+ `番外：xxx`
  - 标记行后必须跟空格/冒号/行尾，避免把「第三章内容」这类正文行误识别
  - 每个标记行拆出一个章节，导出为 `<3位全局编号> <章节标题>.txt`（标题行 + 段落空行，格式同 standardized）
  - **编号修正**：按出现顺序重排作者标号错误（重复/回退），以首个可解析标记编号为起点（中文风格保持中文、阿拉伯保持阿拉伯；番外不占编号）；如原文 第二十章/第十九章/第二十章 → 第二十章/第二十一章/第二十二章
  - 第一个标记之前的内容（卷标题/前言）跳过并记录；无卷内标记的文件整文件作为一个章节导出（不进卷）
  - 过滤 `series_*_summary.txt` / `_records` 等索引文件
- **自动生成 `volumes.json`**（输出目录的上级，即 series_xxx 目录）：每卷一条 `{"name": "第一卷 xxx", "start": 1, "end": 27}` 锚定全局章节范围，可直接 `epub --volumes` 使用
- 模块级辅助 `_int_to_chinese` / `_chinese_to_int` / `_sanitize_filename_part`；`BatchTxtFileFormatter._number_to_chinese` 委托到 `_int_to_chinese`（行为不变）

#### 用法（卷打包系列完整流程）

```bash
# 1) 拆卷：chapters -> standardized，并生成 series_xxx/volumes.json
python txt_file_processing.py split "series/series_123456789" "series/series_123456789/standardized" --punct

# 2) 人工校正（如需）后直接打包 EPUB
python txt_file_processing.py epub "series/series_123456789/standardized" "series/series_123456789/全书.epub" \
    --volumes "series/series_123456789/volumes.json" --title-style split_title
```

#### 验证

- mock 14 项全过：编号重排（20/19/20 → 20/21/22）、番外保持、阿拉伯编号卷（第11章起）、无标记文件整文件导出、全局连续编号、卷范围锚定、正文行假阳性排除
- 真实数据 series_123456789：139 章 / 5 卷 / 49 处编号修正，卷范围 1-27/28-57/58-81/82-120/121-139；series_123456789：58 章 / 5 卷 / 0 修正
- 拆卷 → epub 端到端 10 项全过：5 卷页 + 139 章、spine/NCX 嵌套与 playOrder、卷2 首章延续卷内编号（第一章 幕启）
- 样式/拆行/卷/预设/书籍信息 5 套回归全过

### v0.7.5 - 2026-08-12

`epub` 新增**书籍信息页**：打开书第一页即显示 000 书籍信息.txt 的内容，并进入目录。

#### 新增

- **书籍信息页**（`book_info.xhtml`）：有真实书籍信息来源（输入目录存在 `000 书籍信息.txt`，或回退到 pixiv info/metadata 成功）时，在书最前面生成独立页面，**按 000 书籍信息.txt 的段落格式渲染**：
  ```
  书籍信息                      （页面标题，居中 1.8em）
  <书名>                       （大号加粗，居中）
  作者：xxx
  连载平台：xxx
  连载状态：xxx
  字数：xxx
  简介：
  <简介每段一个段落>
  ```
  书名/作者优先取 `--title`/`--author` 覆盖值
- **目录同步**：`toc.ncx` / `nav.xhtml` 顶部都有「书籍信息」条目（playOrder 1，链接 `book_info.xhtml`）
- **有就加、没有就不加**：`_find_book_info` 改为返回 `(info, found)`；纯占位（无 000 文件、无 pixiv 信息）时不生成页面、不进目录、不进 spine
- 位置：spine 第一位，在卷页之前；章节计数/日志统计不含书籍信息页
- CSS 新增 `.book-info-page`（段落无首行缩进、居中、行距）与 `h1.book-info-title` / `.book-info-name`

#### 用法

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --volumes volumes.json --title-style split_title
# 打开书：书籍信息 → 卷页 → 章节；目录顶部也有「书籍信息」
```

#### 验证

- 12 项测试全过：spine/manifest 含 book_info 且居首、段落顺序与 000 模板一致（书名/作者/平台/状态/字数/简介两段）、书名段样式 class、NCX/nav 顶部条目与链接、无信息来源时不生成、卷场景下书籍信息在卷页之前
- 真实数据 74 章 + 3 卷页：页面渲染正确（含 corrected 刷新后的字数）；样式/拆行/卷/预设 4 套回归全过

### v0.7.4 - 2026-08-12

`epub` 章标题新增**拆两行模式**：章节号与章名分两行显示，两行各自可调颜色/字号，配置存于样式预设。

#### 新增

- **`split: true`**（样式预设字段，`epub_styles.json` 加载）：开启后章标题渲染为两行——
  `第一章`（`<span class="chapter-num">`，小号）+ `章名`（`<span class="chapter-name">`，大号）
- **两行独立样式**：`num_color` / `num_size` 控制章节号行（默认 `1em`、继承色），`color` / `size` 控制章名行；`align`/`underline` 作用于整个标题块
- **识别规则**（`EpubBuilder._split_title`）：`第X章/第X话/第X回`（中文或阿拉伯数字、含小数点，编号后须有空格）与 `番外：xxx`/`番外 xxx`；无法识别的标题（如"附录"）保持单行
- 内置示例预设 `split_title`（上行灰色 #555555 小号章节号 + 下行深红 1.4em 章名 + 下划线）；`--title-styles` 可查看
- 非 split 模式完全不变（回归兼容）；CSS 仅在 split 开启时输出 `.chapter-num`/`.chapter-name` 规则

#### 用法

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --title-style split_title
```

`epub_styles.json` 中自定义：

```json
"my_split": {
    "align": "center", "color": "#8B0000", "size": "1.4em",
    "underline": true, "split": true,
    "num_color": "#555555", "num_size": "1em",
    "desc": "拆两行：上行章节号，下行章名"
}
```

#### 验证

- 17 项测试全过：`_split_title` 六种形态解析（中文/阿拉伯/小数章号、番外冒号/空格、无法拆分、无空格不拆）、拆行 XHTML 结构、番外拆行、单行回退、CSS 规则、非 split 回归、CLI 端到端
- 真实数据 74 章：`第一章`/`番外` 均正确拆行；卷/篇 17 项、样式 16 项、预设 9 项回归全过

#### 修复

- **CSS 花括号失衡导致整份样式失效**：`style.css` 模板中 `h1.chapter-title` 的闭合 `}` 原先由模板补出，而 `_build_title_css()` 返回值里已含拆行 span 规则块，导致 `h1` 块永远未闭合、花括号失衡，阅读器丢弃整份样式表（表现：卷页样式丢失、拆两行不生效且章节号与章名间空格消失）。修复：闭合 `}` 移入 `_build_title_css()` 返回值，模板不再补 `}`；`_build_title_css` 输出的 h1 块 + 两个 span 块各自成对闭合。

### v0.7.3 - 2026-08-12

`epub` 命令新增**章标题样式预设**：样式存 JSON 文件，按名称一键调用。

#### 新增

- **`epub_styles.json`**（项目根目录，已随项目提供示例）：样式名 -> 设置对象：
  ```json
  {
      "calibre3": {
          "align": "left",
          "color": "#8B0000",
          "size": "1.2em",
          "underline": true,
          "desc": "左对齐、深红、1.2em、标题下划线（经典样式）"
      }
  }
  ```
  内置 `default`（旧版默认外观）与 `calibre3`（红色下划线）两个示例，用户可自行增删改名
- **`--title-style <名称>`**：按名称调用预设，一次输入永久复用
- **`--title-styles`**：列出全部预设（名称 + desc + 设置摘要），不打包；位置参数可省略
- **`--title-styles-file <路径>`**：指定自定义预设文件（默认项目根目录 `epub_styles.json`）
- **预设与显式参数叠加**：`--title-align`/`--title-color`/`--title-size`/`--title-underline`（新增 `--no-title-underline` 关闭下划线）优先级高于预设，只覆盖传入的项
- 文件不存在时自动生成示例模板；非法预设条目（align 非 center/left）跳过并警告；JSON 解析失败返回空并警告
- `EpubBuilder.load_presets(styles_file=None)` 类方法可独立调用（支持传入自定义路径，便于测试）

#### 用法

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --title-style calibre3
python txt_file_processing.py epub --title-styles                      # 查看全部预设
python txt_file_processing.py epub standardized/ 全书.epub --title-style bigcenter \
    --title-align left --no-title-underline                            # 预设基础上微调
```

#### 验证

- 9 项测试全过：模板缺失自动生成、自定义预设加载、预设生效、显式参数覆盖预设、非法预设跳过、非法 JSON 容错、CLI 列表/预设打包/缺失预设报错
- 回归：卷/篇 17 项、标题样式 16 项测试全过；CLI 位置参数兼容 merge 式调用（`epub a b out.epub`）

### v0.7.2 - 2026-08-12

`epub` 命令的**章标题样式可配置**：对齐、颜色、字号、下划线四项均可选。

#### 新增

- **四个 CLI 参数**（`EpubBuilder` 新增 `title_style` dict 入参，合并默认值只覆盖提供项）：
  - `--title-align {center|left}`：对齐方式（默认 `center`，与旧版一致）
  - `--title-color <颜色>`：CSS 颜色（默认继承正文黑色）
  - `--title-size <字号>`：CSS 字号（默认 `1.5em`）
  - `--title-underline`：标题下加 2px 实线（颜色同标题色；未设色默认 `#8B0000` 深红）
- **CSS 值安全校验**：颜色/字号用白名单正则校验，非法值（含 `;`、CSS 注入特征、非 em/px/pt/% 单位）忽略并警告；对齐方式非法回退 `center`
- CSS 模板化：`style.css` 的 `h1.chapter-title` 规则由 `_build_title_css()` 动态生成，其余排版规则不动

#### 用法（复刻 calibre3 风格）

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub \
    --title-align left --title-color "#8B0000" --title-size 1.2em --title-underline
```

生成的规则与用户提供的 `.calibre3` 一致：
`text-align: left; font-size: 1.2em; font-weight: bold; line-height: 1.5; text-indent: 0; color: #8B0000; border-bottom: #8B0000 solid 2px; padding-bottom: 0.5em; margin: 0 0 0.8em;`

#### 验证

- 16 项测试全过：默认样式与旧版一致（居中/1.5em/无颜色/无下划线）、calibre3 复刻 7 项规则全中、下划线无颜色时默认深红、非法对齐/颜色/字号被忽略并回退
- 真实数据 74 章打包验证 CSS 输出正确；卷/篇功能回归测试全过

### v0.7.1 - 2026-08-12

`epub` 命令新增**卷/篇支持**：比章节更高一级的分卷结构，独立占页 + 目录嵌套。

#### 新增

- **`--volumes <配置文件>`**：JSON 列表格式（沿用项目 JSON 惯例），手填后导入：
  ```json
  [
      {"name": "第一卷 示例卷名", "start": 1, "end": 17},
      {"name": "第二卷 示例卷名", "start": 18, "end": 35}
  ]
  ```
  - `name`：卷/篇标题；`start`/`end`：章节文件数字前缀范围（含端点），只写 `start` 视为单章
  - 按 `start` 排序；卷配置无效条目（缺 name / 范围非法）跳过并警告
  - 范围内无匹配章节的卷不生成卷页（警告）；游离章节（不属于任何卷）保持原顺序排在卷后
- **卷页**：每卷一个 `vol_<n>.xhtml`，独立占页（`page-break-before/after: always`），卷名垂直居中显示（`padding-top: 35%`），样式采用 `.volume-page` / `.volume-title`（2.5em 深红粗体）
- **目录嵌套**：`toc.ncx` 卷为一层 navPoint、章为其子 navPoint（playOrder 按阅读顺序父先子后）；`nav.xhtml` 卷为一级 `li`、章为嵌套 `<ol>`；游离章保持一级
- `content.opf` 的 manifest/spine 按阅读顺序包含卷页

#### 用法

```bash
python txt_file_processing.py epub standardized/ corrected/ 全书.epub --volumes volumes.json
```

#### 验证

- mock 5 章 + 2 卷 + 1 游离章：spine 顺序（卷页插在卷首章前、游离章居后）、卷页 XHTML/CSS、NCX/nav 嵌套层级、错误配置（非列表/文件缺失/无匹配章节）共 16 项全过
- 真实数据 series_123456789（74 章 + 2 卷 mock）：2 个卷页、spine 76 条（卷2 在第 21 位）、NCX 顶层 36（2 卷 + 34 游离章）、playOrder 1~76 升序无重复

### v0.7.0 - 2026-08-12

新增 `epub` 子命令：把章节目录直接打包为 EPUB 电子书（纯标准库实现，零新依赖）。

#### 新增

- **`epub <输入目录1> [<输入目录2> ...] <输出.epub>`**：与 `merge` 相同的多目录配对语义（按数字前缀，后列目录优先，校正版覆盖标准化版），一步出 EPUB。
- **打包结构**（参照 FanFicFare / WebToEpub / lncrawl 三个开源项目的手写方案，只用 `zipfile` + 字符串模板）：
  - `mimetype` 第一个写入且 `ZIP_STORED` 不压缩（规范硬性要求）
  - `META-INF/container.xml` + `OEBPS/content.opf`（元数据 + manifest + spine）
  - 双目录导航：`toc.ncx`（EPUB2 兼容）+ `nav.xhtml`（EPUB3 标准）
  - `style.css` 中文排版：首行缩进 2em、1.8 倍行距、两端对齐、宋体系衬线字体
  - 每章一个 `chap_<编号>.xhtml`（`<h1>` 章标题 + `<p>` 段落）
- **元数据自动映射**（`EpubBuilder._find_book_info`）：
  - 优先解析输入目录的 `000 书籍信息.txt`（书名/作者/简介/连载状态/字数，后列为优先级最高目录）
  - 其次回退 pixiv 系列 `info.txt` / `metadata.json`（复用 `BookInfoGenerator`）
  - 最后占位值；`--title` / `--author` 可显式覆盖
- **章标题去重**：章节正文首段若与文件名标题一致（`format` 注入的标题行），打包时丢弃该段，避免与 `<h1>` 重复显示。
- `dc:description`（简介）、`dc:language`（zh-CN）、`dcterms:modified` 时间戳、连载状态/字数写入 OPF 扩展 meta。

#### 用法

```bash
# 一步到位：校正版优先，未改的取标准化版
python txt_file_processing.py epub standardized/ corrected/ 全书.epub

# 单个目录（如 final/ 或原始 chapters/）
python txt_file_processing.py epub final/ 全书.epub

# 覆盖书名/作者（000 里是占位"未填"时有用）
python txt_file_processing.py epub standardized/ 全书.epub --title "书名" --author "作者"
```

#### 验证

- 真实数据 series_123456789（74 章）端到端打包，17 项结构检查全过：mimetype 首个且未压缩、全部 XML/XHTML 良构、OPF/NCX/nav 元数据与目录齐全、章标题去重正确。
- 多目录 mock：校正版优先、改名后 h1 用新标题、未改章节取标准化版。
- 原始下载目录（无 000）：回退 pixiv info 成功，无标题重复。

### v0.6.3 - 2026-08-07

`merge` 命令升级支持多输入目录，可直接「标准化 + 校正 → 单文件成书」，无需再走 `assemble` 中间步。

#### 变更

- **`merge` 接受多个输入目录**：`python txt_file_processing.py merge standardized/ corrected/ 全书.txt`
  - 按数字前缀（或无前缀的完整名）配对，**后面传入的目录优先级高**：同前缀章节取后者、前者被覆盖。
  - 单目录用法完全兼容旧版：`merge standardized/ 全书.txt`
- **`--info` 字数刷新适配多目录场景**：
  - 字数统计范围改为「所有输入目录按前缀配对去重后实际参与合并的章节」（不含 000）。
  - 刷新后的 000 写到优先级最高的源目录（即列表最后一个，如 corrected/），保证合并时不会被旧版本冲掉；
    其他源目录的 000 保持不变作为历史。
- `BookInfoGenerator` 的 `__init__` 接受 `source_dir` 字符串或列表；新增 `_count_chars_for_merge` 多目录去重统计方法。
- `TxtFileMerger.__init__` 参数从 `input_folder` 改为 `input_folders`（兼容字符串入参）；新增 `_collect_files` 按前缀合并多目录的文件清单。

#### 推荐用法

```bash
# 出成书 txt（推荐，一步到位）：校正版优先、未改的取标准化版，开头自动刷新字数 000
python txt_file_processing.py merge standardized/ corrected/ 全书.txt

# 只想合并单一目录
python txt_file_processing.py merge standardized/ 全书.txt

# 不要字数刷新
python txt_file_processing.py merge standardized/ corrected/ 全书.txt --no-info

# 仍需要分章成书目录作为最终产物（少见，可选）
python txt_file_processing.py assemble standardized/ corrected/ final/
```

### v0.6.2 - 2026-08-07

日志改为**固定文件名追加 + 超阈值自动归档**机制，避免每次运行产生零散文件，也避免无限增长。

#### 变更

- 新增共享模块 `log_setup.py`，统一提供 `configure_logging(base_dir, logger_name, filename)`；`cli.py` 和 `txt_file_processing.py` 都改为从这里导入。
- **固定文件追加**：`logs/download.log` 与 `logs/postprocess.log` 两个固定文件，每次运行追加写入，开头加 `===== <时间戳> =====` 作为会话分隔行，跨会话历史完整保留。
- **超阈值自动归档**：启动时若文件 > 1 MB，先 `shutil.move` 到 `logs/archive/<base>_<YYYYMMDD_HHMMSS>.log` 再开新文件。归档目录不存在会自动创建。历史有迹可循又不会与当前日志混在一起。
- 控制台仍走 `TqdmLoggingHandler`（无 tqdm 时回退 print），与进度条互不打断。
- `.gitignore` 新增 `logs/` 规则（按需取消注释以纳入版本管理）。

#### 目录布局

```
logs/
├── download.log           # 当前下载日志（追加）
├── postprocess.log        # 当前后处理日志（追加）
└── archive/
    ├── download_20260807_125206.log     # 历史归档
    └── postprocess_20260807_130000.log
```

### v0.6.1 - 2026-08-07

`merge` 命令新增按合并目录实际字数刷新 `000 书籍信息.txt` 的能力。

#### 新增

- **`merge --info`（默认开启）**：合并前根据 `input_folder` 内所有非 000 的 txt 实际字符数（过滤空白行后），重新统计总字数；只替换现有 `000 书籍信息.txt` 中的"字数：xxx万字"行，其余内容保持不变。
- 字数找来源会按顺序查：`input_folder` 本身 → 同级 `standardized/` 目录，都没有则跳过并 warning。
- 合并输出文件的开头按数字排序即 000 排最前，等于把这份已更新字数的 000 作为合并成书开头的书籍信息。
- 提供 `--no-info` 关闭此行为，仅做合并不更新。

#### 用法

```bash
# 默认 --info：先更新 000 字数再合并，开头是新版 000
python txt_file_processing.py merge "corrected/" "全书.txt"

# 不更新字数，按现状合并
python txt_file_processing.py merge "corrected/" "全书.txt" --no-info
```

### v0.6.0 - 2026-08-07

#### 字数统计修正

- **修正 `xxx_info.txt` 中"总字数"与网页显示不一致的问题**：以前用系列分页接口 (`/ajax/novel/series_content/<id>`) 的 `textCount` 字段累加，该值与 Pixiv 网页显示的统计口径不同，往往偏小。改为**下载完所有章节后，从 metadata.json 里逐章 `textCount`（来自单章详情接口）累加并覆盖 info.txt**，与网页一致。
- 实现：新增 `PixivNovelScraper._sum_word_count_from_metadata()`；`download_series` 在章节流程结束后比较两套统计值，不同时重写 info.txt 并打印纠正日志。

#### 新增「000 书籍信息.txt」自动生成

- **`format` 命令运行结束时在输出目录自动生成 `000 书籍信息.txt`**，统一替代原来的「编号为 0 的文件原样拷贝」分支（旧分支废除并打 warning）。
- 字段映射与模板格式：
  - 书名、作者、简介 → 从 `series_<ID>_info.txt` / `series_<ID>_metadata.json` 自动读取
  - 连载状态 `N章+M番外（YYYY年M月D日）` → 扫输出目录文件名含"番外"关键字的算番外，其余算正文；日期取 info.txt 的"更新时间"前 10 字
  - 字数 `X.X万字` → info.txt 的"总字数"÷10000，保留 1 位小数（与网页一致）
  - 连载平台 → 固为 `Pixiv`
  - 简介多行全部按"段落间空行"格式注入
- **找不到 pixiv 源时生成空白占位模板**：所有字段值为"未填"，由用户手填。
- 模板内置在 `BookInfoGenerator.TEMPLATE` / `BLANK_TEMPLATE` 中；项目根目录下用户提供的 `000 书籍信息.txt` 与 `000 书籍信息_模板.txt` 作为参考样本（脚本不直接读取，避免与默认模板冲突）。

#### 兼容性

- 用户若在 `chapters/` 里放了 `0 xxx.txt`，会被 `format` 跳过并提示"已改为脚本末尾自动生成 000 书籍信息.txt"，避免被中文章号注入。
- 旧版 `_revisions.json`、标准化目录里已有的 `0 xxx.txt` 不受影响；新运行会走新机制。

### v0.5.5 - 2026-08-07

校正阶段改了文件名也能正确配对：`diff` / `note` / `assemble` 三条命令的匹配键**默认从完整文件名改为文件名开头的数字编号**。

#### 行为变化

- **前缀配对**：新增模块级辅助 `_file_prefix` / `_build_prefix_index`，三条命令统一按文件名开头的数字前缀（如 `009`）配对。校正目录里把 `009 原标题.txt` 改成 `009 新标题.txt` 仍能与标准化目录的 `009 原标题.txt` 对齐比对、记录修订、合成。
- 无数字前缀的文件（如人工放进来的"附录.txt"）回退到完整文件名匹配，保持兼容。
- `RevisionsStore` 中的 `_revisions.json` 改用前缀编号作为 key，向后兼容旧的整文件名 key；`add` 的 filename 参数可写纯编号或完整名，内部统一规范化。

#### 输出增强

- `diff` 新增"仅改名但内容一致"识别（renamed_only），单独提示变更文件名但未改正文的章节；摘要行包含"X 篇改动，Y 篇未改（其中 Z 篇仅改名），..."。
- `assemble` 输出文件名优先取校正版命名（你改过标题的章节用新标题），未改的取标准化命名；`_source_map.txt` 中标记每条配对的改名轨迹 `009 原标题.txt -> 009 新标题.txt`。
- `note list` 按数字前缀排序输出，每条带 `(实际文件名)` 注解。

#### 兼容性

- 旧版 `_revisions.json`（key 为完整文件名）仍能被 `list` 读取；`remove` 同时尝试旧 key 形式，不丢失历史记录。
- `assemble` 默认用校正版命名输出，若你重命名后想保留原文件名，可手动整理校正目录。

### v0.5.4 - 2026-08-06

为「原始 → 标准化 → 校正」三层流水线工作流新增三个核心子命令，让下载后的人工校对+最终合成全流程可追溯。

#### 新增功能

- **`diff` 子命令**：目录级批量对比两个目录的 txt 文件。
  - 检测三类信息：内容有改动的文件（每处段落差异列出行号+第一个差异字符+两端原文）、仅在标准化目录存在的文件（未校正）、仅在校正目录存在的文件（新增）。
  - 控制台每文件默认预览前 3 条差异，避免刷屏；日志和报告文件保留全部。
  - 可选第三参数输出差异报告 txt；统计同时写入 `logs/postprocess_*.log`。
  - `TxtFileComparator.compare_file` 重构为复用新的 `_diff_paragraphs` 静态方法，原 CLI 行为保持不变。

- **`note` 子命令**：管理校正目录的修订说明 `_revisions.json`。
  - 四种动作：`add`（新增/覆盖一条）、`remove`（删除）、`list`（列出全部）、`clear`（清空）。
  - `add` 通过 `--msg "..."` 提供说明，自动写入文件 mtime 与更新时间戳。
  - 每条记录结构：`{"msg": "...", "mtime": "...", "updated_at": "..."}`，便于追溯每次校正动作。

- **`assemble` 子命令**：从标准化目录 + 校正目录合成最终目录。
  - 规则：校正目录里有的文件取校正版；校正目录没有、标准化目录有的取标准化版；校正目录独有（新增）也进入最终目录。
  - 自动跳过 `_revisions.json`，不进入最终目录。
  - 自动生成 `_source_map.txt` 记录每文件来源（校正/标准化），合成日志同写一份。

#### 推荐工作流

```bash
python txt_file_processing.py format "chapters" "standardized" --punct
# 人工在 corrected/ 里只放改过的文件
python txt_file_processing.py note  add "corrected" "043 xxx.txt" --msg "删除作者 PS"
python txt_file_processing.py diff  "standardized" "corrected" "diff_report.txt"
python txt_file_processing.py note  list "corrected"
python txt_file_processing.py assemble "standardized" "corrected" "final"
```

#### 文档

- `README.md` 新增「三层流水线工作流」章节，给出完整流程示例与三个新子命令要点；命令清单补充 `punct` 用法。

### v0.5.3 - 2026-08-06

后处理日志化：

- `txt_file_processing.py` 引入独立 logger `pixiv_novel_toolkit.postprocess`，所有命令运行时自动写日志到 `logs/postprocess_<时间戳>.log`，与下载器的 `download_*.log` 区分。
- **`format` 命令**：每个文件输出 `[索引] 原文件名 -> 新文件名 (类型)` 记录；类型分类为「正文 / 番外 / 信息 / 跳过」；同时附带标点转换统计 `“N ”N ！N ？N`；末尾汇总正文/番外/信息/跳过/未配对警告五项计数。
- **`punct` 命令**：日志包含输入/输出路径、英文双引号/感叹号/问号的原文数量与转换后 `“ ”` 个数、奇数引号警告。
- `convert_punctuation` 返回值由 `unpaired` 整数扩展为 `stats` 字典（含原文统计与配对详情），向后不兼容该函数 API；其余调用方已同步更新。
- 控制台日志走 `TqdmLoggingHandler`，与下载器一致，未来若引入进度条不会互相打断。

### v0.5.2 - 2026-08-06

新增功能：

- **标点转换**：`txt_file_processing.py` 新增 `punct` 子命令，将单个 txt 中的英文 `!` `?` `"` 转换为中文 `！` `？` `“` `”`；引号按全文奇偶配对（第 1 个 → 前引号，第 2 个 → 后引号，依次循环），检测到奇数个引号时打印警告避免静默错配。
- **批量格式化集成**：`format` 子命令新增 `--punct` 开关，开启后批量重命名+注入标题的同时做标点转换，免去单独跑一遍 `punct`。
- 单引号 `'` 不处理，避免与英文撇号（如 `don't`）产生冲突。

#### 用法示例

```bash
# 单文件，原文件覆盖
python txt_file_processing.py punct "chapters/043 xxx.txt"

# 单文件，输出到新文件
python txt_file_processing.py punct "input.txt" "output.txt"

# 批量格式化同时做标点转换
python txt_file_processing.py format "chapters/" "out/" --punct
```

### v0.5.1 - 2026-08-06

修复 v0.5.0 引入的两个进度条相关问题：

- **进度条被日志打断重绘**：将控制台日志 handler 改为 `TqdmLoggingHandler`，通过 `tqdm.write` 输出，进度条不再被每条日志推到下一行重绘，会保持在底部原地刷新；无 tqdm 时自动回退到 `print`。
- **跳过已存在的章节仍占用 1.5s 等待**：把章节间限速 sleep 从 `download_series` / `download_missing` 的循环外侧移到 `download_novel` 的"真正下载成功"路径内（`self.chapter_delay`）。早返回的 skip 路径不再触发 sleep，重跑已基本完成的系列时速度大幅提升。
- 顺带修正 CSV 批量下载从未做章节间限速的历史问题（现在和系列下载行为一致）。

### v0.5.0 - 2026-08-06

这是 v0.4.1 之后的一次较大整理版本，覆盖了项目结构、断点续传、命令行入口、日志与并发下载等多个方面，同时修正了若干历史遗留问题。

#### 主要变更

- **断点续传**：默认跳过本地已存在的章节文件，复跑系列/CSV 批量任务时不再重复下载；新增 `--force` 选项可强制覆盖。
- **命令行入口**：新增 `cli.py`，提供 `novel` / `csv` / `series` / `retry` 四个子命令；`pixiv_novel_scraper.py` 直接运行仍生效（委托到 `cli.main`），无参数时进入交互式菜单。
- **失败章节一键补跑**：新增 `retry` 子命令，根据现有 `*_records.csv` 扫描本地缺失的章节并自动重下；交互菜单新增对应入口。
- **日志体系**：scraper 中所有 `print` 改为 `logging` 调用，分级输出到控制台与 `logs/download_<时间戳>.log`；长任务事后追溯更方便。
- **进度条**：批量下载与补跑流程接入 `tqdm`（无 tqdm 时自动回退为普通迭代，保持可移植性）。
- **并发下载**：系列下载支持 `--workers N`，`N>1` 时启用 `ThreadPoolExecutor` 并发抓章节；索引文件（CSV / metadata / summary / catalog）改用 `threading.Lock` 串行写入以避免并发竞争；默认 `workers=1` 时行为与旧版一致。
- **后处理脚本入口**：`txt_file_processing.py` 新增 `if __name__ == "__main__"` 与 argparse 子命令 `merge` / `format` / `format-single` / `compare`，下载后人工纠错完可在命令行直接调用，无需手动开 REPL；同步提取 `interleave_blank_lines()` 公共函数消除三处重复代码。
- **元数据真值源拆分**：`save_summary_txt` 拆为 `save_metadata`（写 JSON 真值源）与 `regenerate_summary`（从 JSON 派生 txt），原方法保留为兼容入口；JSON 修改后可单独刷新 summary。
- **辅助函数提取**：`clean_filename` / `clean_html` / `parse_chapter_selection` / `extract_tag_names` 提到模块级，便于测试与复用；类内保留 thin wrapper 不破坏旧 API。

#### 目录与文件整理

- 删除历史遗留的 `records/` `metadata/` `summaries/` 三个旧目录；其中 `series_123456789` 与 `series_123456789` 的索引文件已迁移至对应 `series/series_<ID>/` 目录，未发生数据丢失。
- 插图目录由 `插图库` 改为 `illustrations`；检测到旧目录已存在时仍沿用旧路径，已下载内容无需手动迁移。
- 系列对照表 `series_catalog.csv` 移至 `series/_catalog.csv`，与作品数据集中管理。
- 新增 `requirements.txt`（`requests>=2.28`，`tqdm>=4.65`）与 `README.md`，方便第三方 clone 后上手；`.gitignore` 补充 `__pycache__/` 等条目。

#### 推荐 CLI 用法

```bash
python cli.py series 123456789                         # 下载全系列（跳过已存在章节）
python cli.py series 123456789 --chapters 11-21        # 按区间下载
python cli.py series 123456789 --workers 3             # 并发下载
python cli.py retry series 123456789                   # 一键补跑缺失章节
python cli.py novel 12345678 --chapter 04 --force     # 强制覆盖单章
python cli.py                                         # 进入交互菜单
python txt_file_processing.py merge "<dir>" "<out>"  # 合并章节
python txt_file_processing.py format "<in>" "<out>"   # 批量重命名+注入标题
```

#### 兼容性说明

- 现有 `pixiv_novel_scraper.py` 直接运行入口保留，脚本向下兼容。
- 旧调用 `scraper.clean html(...)` 等类方法仍可调用，但建议改用模块级函数。
- 旧插图目录不会被自动改名，新下载默认落到 `illustrations/` 但目录存在性优先级高于命名规则。

### v0.4.1 - 2026-05-17

- 为系列小说新增按指定章节下载功能，支持单章如 `11` 和区间如 `11-21`。
- 当使用指定章节下载时，保存的章节编号默认沿用系列中的原始章节号，便于和网页目录对应。
- 该功能同样适用于“仅更新 CSV 目录”模式。

- Added selective chapter download for series novels, supporting a single chapter such as `11` and a range such as `11-21`.
- When selective chapter download is used, saved chapter numbers now follow the original chapter positions in the series for easier alignment with the Pixiv directory.
- This behavior also applies to the “update CSV only” mode.

### v0.4.0 - 2026-05-17

- 在脚本目录新增 `series_catalog.csv`，自动记录系列 ID 与系列名称的对应关系。
- 为每个系列目录新增 `series_<系列ID>_info.txt`，汇总保存系列简介、更新时间、总字数、章节数、作者和标签等信息。
- 系列元数据优先从系列总览接口获取，失败时会回退到章节列表中可用的信息。

- Added `series_catalog.csv` in the script directory to maintain a mapping between series IDs and series titles.
- Added `series_<seriesID>_info.txt` to each series folder, containing the series description, update time, total word count, chapter count, author, and tags.
- Series metadata now prefers the dedicated overview endpoint and falls back to chapter-list metadata when necessary.

### v0.3.0 - 2026-05-17

- 调整输出结构为按作品归档，每个小说或系列都拥有独立目录。
- 新增 `chapters/` 子文件夹用于存放章节 `txt`，避免与 `csv`、`metadata`、`summary` 文件混在同一级目录。
- `records`、`metadata`、`summary` 文件现在直接保存在各自作品目录下，查阅和归档更加直观。

- Reorganized outputs by work, so each novel or series now has its own dedicated folder.
- Added a `chapters/` subfolder for chapter `txt` files to keep them visually separate from `csv`, `metadata`, and `summary` files.
- Record, metadata, and summary files are now stored directly inside each work directory for easier browsing and archiving.

### v0.2.1 - 2026-05-17

- 为小说详情、系列目录和插图相关请求增加了统一的超时重试机制，提升部分章节访问不稳定时的成功率。
- 针对读取超时、网络异常和 JSON 解析失败补充了更明确的错误提示，便于判断是接口慢响应还是返回数据异常。

- Added a unified retry mechanism for novel metadata, series metadata, and illustration-related requests to improve stability when some chapters respond slowly.
- Added clearer error messages for read timeouts, network failures, and JSON parsing failures so it is easier to tell whether the issue is slow API response or malformed returned data.

### v0.2.0 - 2026-05-17

- 修复了脚本直接运行时输出目录受当前工作目录影响的问题，现统一保存到脚本所在目录下。
- 新增 `novels/`、`series/`、`records/`、`metadata/` 和 `summaries/` 五类输出目录，便于整理生成文件。
- 单章下载现按小说 ID 保存到 `novels/novel_<小说ID>/` 目录中。
- 系列下载现按系列 ID 保存到 `series/series_<系列ID>/` 目录中，每个系列拥有独立子文件夹。
- CSV、元数据 JSON 和章节简介汇总改为按类型集中存放，并在文件名中带上对应的小说 ID 或系列 ID。

- Fixed the output path behavior so generated files are always saved relative to the script directory instead of the current working directory.
- Added five organized output directories: `novels/`, `series/`, `records/`, `metadata/`, and `summaries/`.
- Single-novel downloads are now stored under `novels/novel_<novelID>/`.
- Series downloads are now stored under `series/series_<seriesID>/`, with an isolated subfolder for each series.
- CSV records, JSON metadata, and summary text files are now grouped by file type and named with the related novel ID or series ID.

### v0.1.0 - 2026-05-17

- 丰富了模块、类和方法注释，使脚本更易理解，也更适合公开发布到 GitHub。
- 将原本偏随意的控制台输出调整为更清晰、更专业的状态提示。
- 新增 `__version__` 版本号元数据，便于后续发布和维护。
- 将 Pixiv Cookie 从源码内联内容迁移到外部 `pixiv_cookie.txt` 文件，便于本地维护。
- 进一步说明了系列分页、插图下载、CSV 更新和简介汇总等核心逻辑。
- 将主脚本文件由 `test3.py` 重命名为更语义化的 `pixiv_novel_scraper.py`。

- Expanded module, class, and method comments to make the script easier to understand and more suitable for public repository publication.
- Replaced casual console output with clearer, more professional status messages.
- Added `__version__` metadata for release tracking.
- Moved the Pixiv cookie from inline source code to an external `pixiv_cookie.txt` file for easier local maintenance.
- Clarified the purpose of series pagination, image downloading, CSV updates, and summary generation with richer inline documentation.
- Renamed the main script from `test3.py` to the more descriptive `pixiv_novel_scraper.py`.
