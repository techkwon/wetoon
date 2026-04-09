from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAPER_COLOR = Color(0.96, 0.94, 0.90)
SHADOW_COLOR = Color(0.85, 0.82, 0.78)
BORDER_COLOR = Color(0.86, 0.84, 0.80)
PAGE_NUMBER_COLOR = Color(0.45, 0.41, 0.36)


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


def _register_font() -> str:
    font_name = "Helvetica"
    if LABEL_FONT_PATH is None:
        return font_name
    try:
        pdfmetrics.registerFont(TTFont("BookUIFont", str(LABEL_FONT_PATH)))
        return "BookUIFont"
    except Exception:
        return font_name


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


def _load_image(path: Path) -> tuple[ImageReader, tuple[int, int]]:
    with Image.open(path) as image:
        rgb_image = rgba_to_rgb(image)
        size = rgb_image.size
        return ImageReader(rgb_image), size


def _fit_rect(
    image_size: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    image_width, image_height = image_size
    x0, y0, x1, y1 = bounds
    bounds_width = x1 - x0
    bounds_height = y1 - y0
    scale = min(bounds_width / image_width, bounds_height / image_height)
    width = image_width * scale
    height = image_height * scale
    left = x0 + (bounds_width - width) / 2
    bottom = y0 + (bounds_height - height) / 2
    return left, bottom, width, height


def _draw_cover_page(pdf: canvas.Canvas, cover_path: Path, page_size: PageSize) -> None:
    image, _ = _load_image(cover_path)
    pdf.drawImage(image, 0, 0, width=page_size.width, height=page_size.height, preserveAspectRatio=True, mask="auto")
    pdf.showPage()


def _draw_body_page(
    pdf: canvas.Canvas,
    page_source: PageSource,
    page_size: PageSize,
    page_number: int,
    font_name: str,
) -> None:
    pdf.setFillColor(PAPER_COLOR)
    pdf.rect(0, 0, page_size.width, page_size.height, stroke=0, fill=1)

    margin_x = page_size.width * 0.08
    margin_top = page_size.height * 0.06
    margin_bottom = page_size.height * 0.12
    bounds = (
        margin_x,
        margin_bottom,
        page_size.width - margin_x,
        page_size.height - margin_top,
    )

    image_reader, image_size = _load_image(page_source.image_path)
    image_left, image_bottom, image_width, image_height = _fit_rect(image_size, bounds)

    pdf.setFillColor(SHADOW_COLOR)
    pdf.rect(image_left + 10, image_bottom - 12, image_width, image_height, stroke=0, fill=1)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setStrokeColor(BORDER_COLOR)
    pdf.setLineWidth(1)
    pdf.rect(image_left, image_bottom, image_width, image_height, stroke=1, fill=1)
    pdf.drawImage(
        image_reader,
        image_left,
        image_bottom,
        width=image_width,
        height=image_height,
        preserveAspectRatio=True,
        mask="auto",
    )

    pdf.setFillColor(PAGE_NUMBER_COLOR)
    if page_source.label.strip():
        pdf.setFont(font_name, 18)
        pdf.drawRightString(page_size.width - 88, page_size.height - 58, page_source.label.strip())

    pdf.setFont(font_name, 24)
    pdf.drawCentredString(page_size.width / 2, 48, str(page_number))

    if page_source.label.strip():
        bookmark_name = f"page-{page_number}"
        pdf.bookmarkPage(bookmark_name)
        pdf.addOutlineEntry(page_source.label.strip(), bookmark_name, level=0, closed=False)

    pdf.showPage()


def build_book_pdf(
    cover_path: Path,
    pages: Sequence[PageSource],
    output_path: Path,
    title: str | None = None,
    author: str | None = None,
) -> int:
    page_size = get_page_size(cover_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = _register_font()
    pdf = canvas.Canvas(str(output_path), pagesize=(page_size.width, page_size.height), pageCompression=1)
    if title:
        pdf.setTitle(title)
    if author:
        pdf.setAuthor(author)
        pdf.setCreator(author)
        pdf.setProducer(author)

    _draw_cover_page(pdf, cover_path, page_size)
    for index, page_source in enumerate(pages, start=1):
        _draw_body_page(pdf, page_source, page_size, index, font_name)
    pdf.save()
    return 1 + len(pages)
