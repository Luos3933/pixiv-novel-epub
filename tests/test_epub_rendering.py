import unittest

from pixiv_novel_toolkit.epub.rendering import (
    build_book_info_body,
    build_chapter_title_css,
    build_chapter_title_html,
    build_volume_css,
    build_volume_title_html,
)
from txt_file_processing import EpubBuilder


class EpubRenderingTests(unittest.TestCase):
    def test_split_title_html_escapes_content(self):
        style = {"split": True}
        html = build_chapter_title_html("第一章 A&B", style)
        self.assertIn('class="chapter-num">第一章', html)
        self.assertIn('class="chapter-name">A&amp;B', html)

    def test_volume_html_and_css(self):
        style = {
            "vol_split": True,
            "vol_num_color": "#555555",
            "vol_num_size": "1.2em",
            "vol_color": "#8B0000",
            "vol_size": "2.5em",
            "vol_gap": "0.6em",
        }
        html = build_volume_title_html("第一卷 开始", style)
        css = build_volume_css(style)
        self.assertIn("volume-num", html)
        self.assertIn("volume-name", html)
        self.assertIn("font-size: 2.5em", css)

    def test_legacy_builder_delegates_to_rendering(self):
        builder = EpubBuilder([], "unused.epub", title_style={"split": True})
        self.assertEqual(
            builder._build_title_html("第一章 开始"),
            build_chapter_title_html("第一章 开始", builder.title_style),
        )
        self.assertEqual(
            builder._build_title_css(),
            build_chapter_title_css(builder.title_style),
        )

    def test_book_info_body_escapes_maker_and_description(self):
        info = {"word_count": "1.0万字", "description": "A&B", "maker": "旧"}
        body = build_book_info_body(info, "书名", "作者", maker="A<B")
        self.assertIn("EPUB制作：A&lt;B", body)
        self.assertIn("A&amp;B", body)


if __name__ == "__main__":
    unittest.main()
