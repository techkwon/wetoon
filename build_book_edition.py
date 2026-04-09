from __future__ import annotations

import html
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from build_ebook import (
    AUTHOR,
    DIST_DIR,
    EpubPage,
    LANGUAGE,
    TITLE,
    list_body_images,
    media_type_for_suffix,
    resolve_cover,
    verify_epub,
    verify_pdf,
)
from services.book_pdf import PageSize, PageSource, build_book_pdf as render_book_pdf, get_page_size

BOOK_SUFFIX = "-book"
def build_book_pdf(cover_path: Path, body_images: list[Path], output_path: Path) -> int:
    page_sources = [PageSource(image_path=image_path, label=image_path.stem) for image_path in body_images]
    return render_book_pdf(cover_path, page_sources, output_path, title=f"{TITLE} Book Edition", author="위툰")


def book_page_document(
    title: str,
    image_name: str,
    alt_text: str,
    page_size: PageSize,
    page_number: int | None,
    student_id: str | None,
    is_cover: bool,
) -> str:
    safe_title = html.escape(title)
    safe_alt = html.escape(alt_text)
    body_class = "book-page cover-page" if is_cover else "book-page"
    page_number_html = "" if page_number is None else f'    <div class="page-number">{page_number}</div>\n'
    student_id_html = "" if student_id is None else f'    <div class="student-id">{html.escape(student_id)}</div>\n'
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{LANGUAGE}">
  <head>
    <title>{safe_title}</title>
    <meta name="viewport" content="width={page_size.width},height={page_size.height}" />
    <link rel="stylesheet" type="text/css" href="../styles/book.css" />
  </head>
  <body class="{body_class}">
    <div class="page-surface">
      <img src="../images/{image_name}" alt="{safe_alt}" />
    </div>
{student_id_html}{page_number_html}  </body>
</html>
"""


def build_book_pages(cover_path: Path, body_images: list[Path], page_size: PageSize) -> list[EpubPage]:
    pages: list[EpubPage] = []
    cover_name = f"cover{cover_path.suffix.lower()}"
    pages.append(
        EpubPage(
            id_="page-cover",
            title="Cover",
            image_name=cover_name,
            image_bytes=cover_path.read_bytes(),
            image_media_type=media_type_for_suffix(cover_path),
            doc_name="cover.xhtml",
            doc_text=book_page_document("Cover", cover_name, "Cover", page_size, None, None, True),
            is_cover=True,
        )
    )

    for index, image_path in enumerate(body_images, start=1):
        image_name = image_path.name
        title = f"Page {index:03d}"
        pages.append(
            EpubPage(
                id_=f"page-{index:03d}",
                title=title,
                image_name=image_name,
                image_bytes=image_path.read_bytes(),
                image_media_type=media_type_for_suffix(image_path),
                doc_name=f"page-{index:03d}.xhtml",
                doc_text=book_page_document(
                    title,
                    image_name,
                    image_path.stem,
                    page_size,
                    index,
                    image_path.stem,
                    False,
                ),
                is_cover=False,
            )
        )
    return pages


def toc_document(pages: list[EpubPage]) -> str:
    items = "\n".join(
        f'        <li><a href="text/{page.doc_name}">{html.escape(page.title)}</a></li>'
        for page in pages
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{LANGUAGE}">
  <head>
    <title>Table of Contents</title>
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>{html.escape(TITLE)} Book Edition</h1>
      <ol>
{items}
      </ol>
    </nav>
  </body>
</html>
"""


def ncx_document(book_id: str, pages: list[EpubPage]) -> str:
    nav_points = []
    for index, page in enumerate(pages, start=1):
        nav_points.append(
            f"""    <navPoint id="navPoint-{index}" playOrder="{index}">
      <navLabel><text>{html.escape(page.title)}</text></navLabel>
      <content src="text/{page.doc_name}"/>
    </navPoint>"""
        )
    nav_map = "\n".join(nav_points)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_id}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(TITLE)} Book Edition</text></docTitle>
  <navMap>
{nav_map}
  </navMap>
</ncx>
"""


def opf_document(book_id: str, pages: list[EpubPage]) -> str:
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_items = [
        '    <item id="nav" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '    <item id="css" href="styles/book.css" media-type="text/css"/>',
    ]

    for page in pages:
        image_properties = ' properties="cover-image"' if page.is_cover else ""
        manifest_items.append(
            f'    <item id="{page.id_}-img" href="images/{page.image_name}" media-type="{page.image_media_type}"{image_properties}/>'
        )
        manifest_items.append(
            f'    <item id="{page.id_}" href="text/{page.doc_name}" media-type="application/xhtml+xml"/>'
        )

    manifest = "\n".join(manifest_items)
    spine_items = "\n".join(f'    <itemref idref="{page.id_}"/>' for page in pages)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="pub-id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">{book_id}</dc:identifier>
    <dc:title>{html.escape(TITLE)} Book Edition</dc:title>
    <dc:language>{LANGUAGE}</dc:language>
    <dc:creator>{html.escape(AUTHOR)}</dc:creator>
    <meta property="dcterms:modified">{modified}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">portrait</meta>
    <meta property="rendition:spread">auto</meta>
    <meta name="cover" content="page-cover-img"/>
  </metadata>
  <manifest>
{manifest}
  </manifest>
  <spine toc="ncx">
{spine_items}
  </spine>
</package>
"""


def stylesheet(page_size: PageSize) -> str:
    return f"""@page {{
  margin: 0;
}}

html, body {{
  margin: 0;
  padding: 0;
  width: {page_size.width}px;
  height: {page_size.height}px;
}}

body.book-page {{
  position: relative;
  overflow: hidden;
  background: rgb(245, 239, 229);
  color: rgb(99, 91, 80);
}}

.page-surface {{
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: 72px 88px 140px;
  display: flex;
  align-items: center;
  justify-content: center;
}}

.page-surface img {{
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  background: #fff;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.15);
}}

body.cover-page {{
  background: #111;
}}

body.cover-page .page-surface {{
  padding: 0;
}}

body.cover-page .page-surface img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-shadow: none;
}}

.page-number {{
  position: absolute;
  left: 0;
  right: 0;
  bottom: 46px;
  text-align: center;
  font-size: 28px;
  letter-spacing: 0.08em;
}}

.student-id {{
  position: absolute;
  top: 42px;
  right: 88px;
  font-size: 20px;
  letter-spacing: 0.04em;
}}
"""


def build_book_epub(cover_path: Path, body_images: list[Path], output_path: Path) -> int:
    page_size = get_page_size(cover_path)
    book_id = f"urn:uuid:{uuid.uuid4()}"
    pages = build_book_pages(cover_path, body_images, page_size)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr("OEBPS/styles/book.css", stylesheet(page_size))
        archive.writestr("OEBPS/toc.xhtml", toc_document(pages))
        archive.writestr("OEBPS/toc.ncx", ncx_document(book_id, pages))
        archive.writestr("OEBPS/content.opf", opf_document(book_id, pages))
        for page in pages:
            archive.writestr(f"OEBPS/images/{page.image_name}", page.image_bytes)
            archive.writestr(f"OEBPS/text/{page.doc_name}", page.doc_text)
    return len(pages)


def verify_book_epub(epub_path: Path, expected_spine: int) -> None:
    verify_epub(epub_path, expected_spine)
    with zipfile.ZipFile(epub_path) as archive:
        root = ET.fromstring(archive.read("OEBPS/content.opf"))
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        metadata = root.find("./opf:metadata", ns)
        if metadata is None:
            raise RuntimeError("EPUB metadata section missing")
        metadata_text = ET.tostring(metadata, encoding="unicode")
        if "pre-paginated" not in metadata_text:
            raise RuntimeError("EPUB is missing fixed-layout metadata")


def main() -> None:
    cover_path = resolve_cover()
    body_images = list_body_images(cover_path)
    DIST_DIR.mkdir(exist_ok=True)

    book_pdf_path = DIST_DIR / f"{TITLE}{BOOK_SUFFIX}.pdf"
    book_epub_path = DIST_DIR / f"{TITLE}{BOOK_SUFFIX}.epub"

    pdf_pages = build_book_pdf(cover_path, body_images, book_pdf_path)
    epub_pages = build_book_epub(cover_path, body_images, book_epub_path)
    verify_pdf(book_pdf_path, pdf_pages)
    verify_book_epub(book_epub_path, epub_pages)

    print(f"Cover: {cover_path.name}")
    print(f"Body images: {len(body_images)}")
    print(f"Book PDF: {book_pdf_path.name} ({pdf_pages} pages)")
    print(f"Book EPUB: {book_epub_path.name} ({epub_pages} spine pages)")


if __name__ == "__main__":
    main()
