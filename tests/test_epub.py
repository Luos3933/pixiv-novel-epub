import tempfile
import unittest
import zipfile
from pathlib import Path

from pixiv_novel_toolkit.epub.builder import EpubBuilder as PackageEpubBuilder
from txt_file_processing import EpubBuilder


class EpubBuilderTests(unittest.TestCase):
    def test_legacy_import_reexports_package_builder(self):
        self.assertIs(EpubBuilder, PackageEpubBuilder)

    def test_builds_minimal_epub_with_required_zip_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "standardized"
            chapters.mkdir()
            (chapters / "000 书籍信息.txt").write_text(
                "书名：测试书\n\n作者：测试作者\n\n连载状态：1章\n\n"
                "字数：2\n\n简介：\n测试简介\n",
                encoding="utf-8",
            )
            (chapters / "001 第一章 开始.txt").write_text(
                "第一章 开始\n\n正文\n",
                encoding="utf-8",
            )
            output = root / "book.epub"

            result = EpubBuilder(str(chapters), str(output)).build()

            self.assertEqual(result, str(output))
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertEqual(names[0], "mimetype")
                self.assertEqual(archive.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
                self.assertIn("OEBPS/content.opf", names)
                self.assertIn("OEBPS/nav.xhtml", names)
                self.assertIn("OEBPS/chap_001.xhtml", names)
                chapter = archive.read("OEBPS/chap_001.xhtml").decode("utf-8")
                self.assertIn("第一章 开始", chapter)
                self.assertIn("正文", chapter)


if __name__ == "__main__":
    unittest.main()
