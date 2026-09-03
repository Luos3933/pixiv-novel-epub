import unittest

from pixiv_novel_toolkit.epub.navigation import (
    image_mimetype,
    render_content_opf,
    render_nav_xhtml,
    render_toc_ncx,
)
from txt_file_processing import EpubBuilder


class EpubNavigationTests(unittest.TestCase):
    def setUp(self):
        self.spine = [
            {"kind": "vol", "id": "vol_1", "fname": "vol_1.xhtml", "title": "第一卷", "vol": 1},
            {"kind": "chap", "id": "chap_001", "fname": "chap_001.xhtml", "title": "第一章 A&B", "vol": 1},
            {"kind": "chap", "id": "chap_002", "fname": "chap_002.xhtml", "title": "第二章", "vol": None},
        ]

    def test_opf_contains_cover_images_and_escaped_metadata(self):
        opf = render_content_opf(
            "A&B",
            "作者",
            {"description": "简介", "status": "2章", "word_count": "1.0万字"},
            "urn:test",
            self.spine,
            cover_img_name="cover.png",
            used_images={"插图.webp": b"data"},
            modified="2026-09-02T00:00:00Z",
        )
        self.assertIn("A&amp;B", opf)
        self.assertIn('properties="cover-image"', opf)
        self.assertIn('href="img/插图.webp" media-type="image/webp"', opf)
        self.assertIn("2026-09-02T00:00:00Z", opf)
        self.assertEqual(image_mimetype("cover.jpeg"), "image/jpeg")

    def test_nested_navigation_and_legacy_wrappers(self):
        ncx = render_toc_ncx("书名", "urn:test", self.spine)
        nav = render_nav_xhtml(self.spine)
        builder = EpubBuilder([], "unused.epub")
        self.assertEqual(builder._toc_ncx("书名", "urn:test", self.spine), ncx)
        self.assertEqual(builder._nav_xhtml(self.spine), nav)
        self.assertIn("A&amp;B", ncx)
        self.assertIn("<ol>", nav)


if __name__ == "__main__":
    unittest.main()

