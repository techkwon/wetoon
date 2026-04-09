from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import fitz
from PIL import Image

PAPER_COLOR = (0.96, 0.94, 0.90)
SHADOW_COLOR = (0.85, 0.82, 0.78)
BORDER_COLOR = (0.86, 0.84, 0.80)
PAGE_NUMBER_COLOR = (0.45, 0.41, 0.36)


@dataclass(frozen=True)
class PageSize:
    width: int
    height: int


@dataclass(frozen=True)
class PageSource:
    image_path: Path
    label: str


def _resolve_label_font() -> Path | None:
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("malgun.ttf", "arial.ttf"):
        candidate = font_dir / name
        if candidate.exists():
            return candidate
    return None


LABEL_FONT_PATH = _resolve_label_font()


def rgba_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        base = Image.new("RGBA", image.size, (255, 255, 255, 255))
        base.alpha_composite(image.convert("RGBA"))
        return base.convert("RGB")
    return image.convert("RGB")


def get_page_size(cover_path: Path) -> PageSize:
    with Image.open(cover_path) as image:
        width, height = image.size
    return PageSize(width=width, height=height)


def image_to_png_bytes(path: Path) -> tuple[bytes, tuple[int, int]]:
    with Image.open(path) as image:
        rgb_image = rgba_to_rgb(image)
        buffer = io.BytesIO()
        rgb_image.save(buffer, format="PNG")
        return buffer.getvalue(), rgb_image.size


def fit_rect(image_size: tuple[int, int], bounds: fitz.Rect) -> fitz.Rect:
    image_width, image_height = image_size
    scale = min(bounds.width / image_width, bounds.height / image_height)
    width = image_width * scale
    height = image_height * scale
    x0 = bounds.x0 + (bounds.width - width) / 2
    y0 = bounds.y0 + (bounds.height - height) / 2
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _font_name(page: fitz.Page) -> str:
    if LABEL_FONT_PATH is not None:
        page.insert_font(fontname="book-ui-font", fontfile=str(LABEL_FONT_PATH))
        return "book-ui-font"
    return "helv"


def add_cover_page(document: fitz.Document, cover_path: Path, page_size: PageSize) -> None:
    page = document.new_page(width=page_size.width, height=page_size.height)
    page.insert_image(
        fitz.Rect(0, 0, page_size.width, page_size.height),
        filename=str(cover_path),
        keep_proportion=True,
    )


def add_body_page(
    document: fitz.Document,
    page_source: PageSource,
    page_size: PageSize,
    page_number: int,
) -> None:
    page = document.new_page(width=page_size.width, height=page_size.height)
    font_name = _font_name(page)
    page.draw_rect(
        fitz.Rect(0, 0, page_size.width, page_size.height),
        color=None,
        fill=PAPER_COLOR,
    )

    margin_x = page_size.width * 0.08
    margin_top = page_size.height * 0.06
    margin_bottom = page_size.height * 0.12
    content_box = fitz.Rect(
        margin_x,
        margin_top,
        page_size.width - margin_x,
        page_size.height - margin_bottom,
    )

    image_bytes, image_size = image_to_png_bytes(page_source.image_path)
    image_rect = fit_rect(image_size, content_box)
    shadow_rect = fitz.Rect(
        image_rect.x0 + 10,
        image_rect.y0 + 12,
        image_rect.x1 + 10,
        image_rect.y1 + 12,
    )
    page.draw_rect(shadow_rect, color=None, fill=SHADOW_COLOR)
    page.draw_rect(image_rect, color=BORDER_COLOR, fill=(1, 1, 1), width=1)
    page.insert_image(image_rect, stream=image_bytes, keep_proportion=True)
    if page_source.label.strip():
        page.insert_textbox(
            fitz.Rect(88, 42, page_size.width - 88, 86),
            page_source.label.strip(),
            align=2,
            fontsize=18,
            color=PAGE_NUMBER_COLOR,
            fontname=font_name,
        )
    page.insert_textbox(
        fitz.Rect(0, page_size.height - 90, page_size.width, page_size.height - 30),
        str(page_number),
        align=1,
        fontsize=24,
        color=PAGE_NUMBER_COLOR,
        fontname=font_name,
    )


def build_book_pdf(
    cover_path: Path,
    pages: Sequence[PageSource],
    output_path: Path,
    title: str | None = None,
    author: str | None = None,
) -> int:
    page_size = get_page_size(cover_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        add_cover_page(document, cover_path, page_size)
        for index, page_source in enumerate(pages, start=1):
            add_body_page(document, page_source, page_size, index)
        toc = [
            [1, page_source.label.strip(), index + 2]
            for index, page_source in enumerate(pages)
            if page_source.label.strip()
        ]
        if toc:
            document.set_toc(toc)
        metadata = document.metadata
        if title:
            metadata["title"] = title
        if author:
            metadata["author"] = author
            metadata["creator"] = author
            metadata["producer"] = author
        document.set_metadata(metadata)
        document.save(output_path, deflate=True, garbage=4)
    finally:
        document.close()
    return 1 + len(pages)
