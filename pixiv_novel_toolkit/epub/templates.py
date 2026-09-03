"""EPUB XHTML、导航与 CSS 模板，以及内置样式默认值。"""

CHAPTER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h1 class="chapter-title">{title_html}</h1>
{body}
</body>
</html>"""

VOLUME_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{name}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="volume-page">
<div class="volume-title">{content}</div>
</body>
</html>"""

BOOK_INFO_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="book-info-page">
<h1 class="book-info-title">书籍信息</h1>
{body}
</body>
</html>"""

COVER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>封面</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="cover-page">
<div class="cover-image"><img src="{img}" alt="封面"/></div>
</body>
</html>"""

NAV_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>目录</title>
</head>
<body>
<nav epub:type="toc" id="toc">
<h1>目录</h1>
<ol>
{items}
</ol>
</nav>
</body>
</html>"""

NCX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
<head>
<meta name="dtb:uid" content="{uid}"/>
<meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/>
<meta name="dtb:maxPageNumber" content="0"/>
</head>
<docTitle><text>{title}</text></docTitle>
<navMap>
{points}
</navMap>
</ncx>"""

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>"""

CSS = """body {{
    font-family: "Source Han Serif SC", "Noto Serif CJK SC", "SimSun", serif;
    line-height: 1.8;
    margin: 5% 6%;
    text-align: justify;
}}
h1.chapter-title {{
{chapter_title_css}
p {{
    text-indent: 2em;
    margin: 0 0 0.6em 0;
}}
.volume-page {{
    margin: 0;
    padding: 0;
    page-break-before: always;
    page-break-after: always;
}}
{volume_title_css}
.book-info-page p {{
    text-indent: 0;
    text-align: center;
    margin: 0 0 1.2em 0;
}}
.book-info-page .book-info-name {{
    font-size: 1.4em;
    font-weight: bold;
    margin: 0 0 1.5em 0;
}}
h1.book-info-title {{
    text-align: center;
    font-size: 1.8em;
    margin: 0 0 2em 0;
}}
.cover-page {{
    margin: 0;
    padding: 0;
    text-align: center;
}}
.cover-page .cover-image img {{
    max-width: 100%;
    max-height: 100%;
}}
.illustration {{
    text-align: center;
    margin: 1.5em 0;
    text-indent: 0;
}}
.illustration img {{
    max-width: 90%;
    height: auto;
}}
.illustration .illustration-desc {{
    font-size: 0.85em;
    color: #666666;
    margin-top: 0.5em;
    text-indent: 0;
}}"""

DEFAULT_TITLE_STYLE = {
    "align": "center",
    "color": "",
    "size": "1.5em",
    "underline": False,
    "split": False,
    "num_color": "",
    "num_size": "1em",
}

DEFAULT_VOLUME_STYLE = {
    "vol_split": True,
    "vol_num_color": "#555555",
    "vol_num_size": "1.2em",
    "vol_color": "#8B0000",
    "vol_size": "2.5em",
    "vol_gap": "0.6em",
}

STYLE_SAMPLE = {
    "chapter": {
        "default": {
            "align": "center",
            "color": "",
            "size": "1.5em",
            "underline": False,
            "desc": "默认章节样式：居中、1.5em、黑色、无下划线",
        },
        "split_title": {
            "align": "center",
            "color": "#8B0000",
            "size": "1.4em",
            "underline": True,
            "split": True,
            "num_color": "#555555",
            "num_size": "1em",
            "desc": "章节号与章名拆两行：上行小号灰色章节号，下行大号深红章名",
        },
    },
    "volume": {
        "default": {
            "vol_split": True,
            "vol_num_color": "#555555",
            "vol_num_size": "1.2em",
            "vol_color": "#8B0000",
            "vol_size": "2.5em",
            "vol_gap": "0.6em",
            "desc": "默认卷名样式：拆两行，卷号小灰、卷名大号深红",
        },
    },
}

