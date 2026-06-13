"""PDF → image adapter using PyMuPDF (fitz).

Renders each PDF page as a PNG image for downstream OCR processing.
Requires the optional [pdf] extra (pymupdf).
"""

from __future__ import annotations

import importlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class PDFPageImage:
    """A rendered PDF page image."""
    page_number: int  # 1-indexed
    image_path: str   # path to temporary PNG file
    width: int
    height: int


@dataclass
class PDFRenderResult:
    """Result of rendering a PDF to page images."""
    source_path: str
    total_pages: int
    page_images: List[PDFPageImage] = field(default_factory=list)
    dpi: int = 200


def _check_fitz_available() -> None:
    """Raise clear error if PyMuPDF (fitz) is not installed."""
    try:
        importlib.import_module("fitz")
    except ImportError:
        raise ImportError(
            "PyMuPDF is not installed. Install with:\n"
            "  pip install legal-desens[pdf]\n"
            "This will install PyMuPDF (AGPL licensed, opt-in for local use only)."
        )


def render_pdf_pages(
    pdf_path: str,
    dpi: int = 200,
    output_dir: Optional[str] = None,
) -> PDFRenderResult:
    """Render each PDF page as a PNG image.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for rendering (default 200).
        output_dir: Directory for temporary PNG files. If None, uses system temp.

    Returns:
        PDFRenderResult with page images ready for OCR.
    """
    _check_fitz_available()

    import fitz

    pdf_path_obj = Path(pdf_path)
    if not pdf_path_obj.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="legal_desens_pdf_")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path_obj))
    total_pages = len(doc)

    if total_pages == 0:
        doc.close()
        raise ValueError(f"PDF has no pages: {pdf_path}")

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    page_images: List[PDFPageImage] = []

    try:
        for page_idx in range(total_pages):
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=mat)

            image_name = f"page_{page_idx + 1:04d}.png"
            image_path = str(out_dir / image_name)
            pix.save(image_path)

            page_images.append(PDFPageImage(
                page_number=page_idx + 1,
                image_path=image_path,
                width=pix.width,
                height=pix.height,
            ))
    finally:
        doc.close()

    return PDFRenderResult(
        source_path=str(pdf_path_obj),
        total_pages=total_pages,
        page_images=page_images,
        dpi=dpi,
    )
