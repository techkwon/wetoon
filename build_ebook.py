from __future__ import annotations

import html
import io
import math
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
TITLE = "wetoon"
AUTHOR = "Unknown"
LANGUAGE = "ko"
EPUB_TARGET_ASPECT = 3.0
COVER_NAMES = [
    "표지.png",
    "표지.jpg",
    "표지.jpeg",
    "cover.png",
    "cover.jpg",
    "cover.jpeg",
]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class EpubPage:
    id_: str
    title: str
    image_name: str
    image_bytes: bytes
    image_media_type: str
    doc_name: str
    doc_text: str
    is_cover: bool = False


def natural_key(value: str) -> list[object]:
    parts = re.split(r"(\d+)", value)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def resolve_cover() -> Path:
    for name in COVER_NAMES:
        candidate = ROOT / name
        if candidate.exists():
            return candidate

    other_candidates = sorted(
        [
            path
            for path in ROOT.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            and ("cover" in path.stem.lower() or "표지" in path.stem)
        ],
        key=lambda path: natural_key(path.stem),
    )
    if other_candidates:
        return other_candidates[0]

    raise FileNotFoundError("표지 이미지가 없습니다. '표지.png' 또는 'cover.png' 파일이 필요합니다.")


def list_body_images(cover_path: Path) -> list[Path]:
    body_images = sorted(
        [
            path
            for path in ROOT.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and path != cover_path
        ],
        key=lambda path: natural_key(path.stem),
    )
    if not body_images:
        raise FileNotFoundError("본문 이미지가 없습니다.")
    return body_images


def rgba_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        base = Image.new("RGBA", image.size, (255, 255, 255, 255))
        base.alpha_composite(image.convert("RGBA"))
        return base.convert("RGB")
    return image.convert("RGB")


def load_pdf_page(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return rgba_to_rgb(image).copy()


def build_pdf(cover_path: Path, body_images: Iterable[Path], output_path: Path) -> int:
    pages = [load_pdf_page(cover_path)]
    pages.extend(load_pdf_page(path) for path in body_images)
    first_page, rest_pages = pages[0], pages[1:]
    try:
        first_page.save(output_path, save_all=True, append_images=rest_pages)
    finally:
        for page in pages:
            page.close()
    return 1 + len(list(body_images))


def media_type_for_suffix(path: Path) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    return mapping[path.suffix.lower()]


def crop_for_epub(path: Path, stem: str) -> list[tuple[str, bytes, str, str]]:
    with Image.open(path) as image:
        width, height = image.size
        ratio = height / width
        chunk_count = max(1, math.ceil(ratio / EPUB_TARGET_ASPECT))
        chunk_height = math.ceil(height / chunk_count)
        pages: list[tuple[str, bytes, str, str]] = []

        if chunk_count == 1:
            return [
                (
                    f"{stem}{path.suffix.lower()}",
                    path.read_bytes(),
                    media_type_for_suffix(path),
                    stem,
                )
            ]

        rgba_image = image.convert("RGBA")
        for index in range(chunk_count):
            top = index * chunk_height
            bottom = min(height, (index + 1) * chunk_height)
            cropped = rgba_image.crop((0, top, width, bottom))
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            pages.append(
                (
                    f"{stem}-{index + 1:02d}.png",
                    buffer.getvalue(),
                    "image/png",
                    f"{stem}-{index + 1:02d}",
                )
            )
        return pages


def page_document(title: str, image_name: str, alt_text: str) -> str:
    safe_title = html.escape(title)
    safe_alt = html.escape(alt_text)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{LANGUAGE}">
  <head>
    <title>{safe_title}</title>
    <link rel="stylesheet" type="text/css" href="../styles/book.css" />
  </head>
  <body class="image-page">
    <img src="../images/{image_name}" alt="{safe_alt}" />
  </body>
</html>
"""


def build_epub_pages(cover_path: Path, body_images: list[Path]) -> list[EpubPage]:
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
            doc_text=page_document("Cover", cover_name, "Cover"),
            is_cover=True,
        )
    )

    page_number = 1
    for body_path in body_images:
        base_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", body_path.stem)
        for image_name, image_bytes, image_media_type, chunk_label in crop_for_epub(body_path, base_stem):
            title = f"Page {page_number:03d}"
            doc_name = f"page-{page_number:03d}.xhtml"
            pages.append(
                EpubPage(
                    id_=f"page-{page_number:03d}",
                    title=title,
                    image_name=image_name,
                    image_bytes=image_bytes,
                    image_media_type=image_media_type,
                    doc_name=doc_name,
                    doc_text=page_document(title, image_name, chunk_label),
                    is_cover=False,
                )
            )
            page_number += 1
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
      <h1>{html.escape(TITLE)}</h1>
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
  <docTitle><text>{html.escape(TITLE)}</text></docTitle>
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

    spine_items = "\n".join(f'    <itemref idref="{page.id_}"/>' for page in pages)
    manifest = "\n".join(manifest_items)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="pub-id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">{book_id}</dc:identifier>
    <dc:title>{html.escape(TITLE)}</dc:title>
    <dc:language>{LANGUAGE}</dc:language>
    <dc:creator>{html.escape(AUTHOR)}</dc:creator>
    <meta property="dcterms:modified">{modified}</meta>
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


def stylesheet() -> str:
    return """html, body {
  margin: 0;
  padding: 0;
}

body.image-page {
  background: #000;
}

body.image-page img {
  display: block;
  width: 100%;
  height: auto;
}
"""


def build_epub(cover_path: Path, body_images: list[Path], output_path: Path) -> int:
    book_id = f"urn:uuid:{uuid.uuid4()}"
    pages = build_epub_pages(cover_path, body_images)
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
        archive.writestr("OEBPS/styles/book.css", stylesheet())
        archive.writestr("OEBPS/toc.xhtml", toc_document(pages))
        archive.writestr("OEBPS/toc.ncx", ncx_document(book_id, pages))
        archive.writestr("OEBPS/content.opf", opf_document(book_id, pages))
        for page in pages:
            archive.writestr(f"OEBPS/images/{page.image_name}", page.image_bytes)
            archive.writestr(f"OEBPS/text/{page.doc_name}", page.doc_text)
    return len(pages)


def verify_pdf(pdf_path: Path, expected_pages: int) -> None:
    with fitz.open(pdf_path) as document:
        actual_pages = len(document)
        if actual_pages != expected_pages:
            raise RuntimeError(f"PDF page count mismatch: expected {expected_pages}, got {actual_pages}")


def verify_epub(epub_path: Path, expected_spine: int) -> None:
    with zipfile.ZipFile(epub_path) as archive:
        names = archive.namelist()
        required = {
            "mimetype",
            "META-INF/container.xml",
            "OEBPS/content.opf",
            "OEBPS/toc.xhtml",
            "OEBPS/toc.ncx",
            "OEBPS/styles/book.css",
        }
        missing = required - set(names)
        if missing:
            raise RuntimeError(f"EPUB missing files: {sorted(missing)}")
        if names[0] != "mimetype":
            raise RuntimeError("EPUB mimetype entry is not first")

        root = ET.fromstring(archive.read("OEBPS/content.opf"))
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        spine_count = len(root.findall("./opf:spine/opf:itemref", ns))
        if spine_count != expected_spine:
            raise RuntimeError(f"EPUB spine count mismatch: expected {expected_spine}, got {spine_count}")


def main() -> None:
    cover_path = resolve_cover()
    body_images = list_body_images(cover_path)
    DIST_DIR.mkdir(exist_ok=True)
    pdf_path = DIST_DIR / f"{TITLE}.pdf"
    epub_path = DIST_DIR / f"{TITLE}.epub"

    pdf_pages = build_pdf(cover_path, body_images, pdf_path)
    epub_pages = build_epub(cover_path, body_images, epub_path)
    verify_pdf(pdf_path, pdf_pages)
    verify_epub(epub_path, epub_pages)

    print(f"Cover: {cover_path.name}")
    print(f"Body images: {len(body_images)}")
    print(f"PDF: {pdf_path.name} ({pdf_pages} pages)")
    print(f"EPUB: {epub_path.name} ({epub_pages} spine pages)")


if __name__ == "__main__":
    main()
