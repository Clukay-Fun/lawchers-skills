"""OCR engine adapter — wraps RapidOCR for image/scanned document text extraction."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class OCRLine:
    """A single recognized text line with bounding box and confidence."""
    text: str
    box: List[List[float]]  # 4 corner points [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    confidence: float


@dataclass
class OCRResult:
    """Full OCR output: concatenated text, per-line details, and warnings."""
    text: str
    lines: List[OCRLine]
    warnings: List[dict] = field(default_factory=list)


CONFIDENCE_THRESHOLD = 0.7


def _check_rapidocr_available() -> None:
    """Raise clear error if rapidocr_onnxruntime is not installed."""
    try:
        importlib.import_module("rapidocr_onnxruntime")
    except ImportError:
        raise ImportError(
            "RapidOCR is not installed. Install with:\n"
            "  pip install legal-desens[ocr]\n"
            "This will install rapidocr_onnxruntime (lightweight, ONNX-based)."
        )


def _check_docling_available() -> None:
    """Raise clear error if docling is not installed."""
    try:
        importlib.import_module("docling")
    except ImportError:
        raise ImportError(
            "Docling is not installed. Install with:\n"
            "  pip install legal-desens[parse-docling]\n"
            "This will install docling with PyTorch dependencies (heavy)."
        )


def run_rapidocr(image_path: str, confidence_threshold: float = CONFIDENCE_THRESHOLD) -> OCRResult:
    """Run RapidOCR on an image file.

    Args:
        image_path: Path to image file (.png, .jpg, .jpeg, .tiff, .bmp)
        confidence_threshold: Lines below this threshold generate warnings.

    Returns:
        OCRResult with concatenated text, per-line details, and low-confidence warnings.
    """
    _check_rapidocr_available()

    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, _elapsed = engine(str(image_path))

    if result is None:
        return OCRResult(text="", lines=[], warnings=[])

    lines: List[OCRLine] = []
    text_parts: List[str] = []
    warnings: List[dict] = []

    for item in result:
        box, text_str, conf = item[0], item[1], item[2]
        ocr_line = OCRLine(text=text_str, box=box, confidence=conf)
        lines.append(ocr_line)
        text_parts.append(text_str)

        if conf < confidence_threshold:
            warnings.append({
                "type": "low_confidence_ocr",
                "text_preview": text_str[:50],
                "confidence": round(conf, 4),
                "threshold": confidence_threshold,
                "box": box,
            })

    concatenated = "\n".join(text_parts)
    return OCRResult(text=concatenated, lines=lines, warnings=warnings)


def run_docling_parse(input_path: str) -> Tuple[str, dict]:
    """Run Docling to parse a document into Markdown + metadata.

    This is the heavy parser path — requires the parse-docling extra.

    Args:
        input_path: Path to document (PDF, DOCX, etc.)

    Returns:
        (markdown_text, metadata_dict)
    """
    _check_docling_available()

    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(input_path)
    md = result.document.export_to_markdown()

    metadata = {
        "parser": "docling",
        "source_file": str(Path(input_path).name),
    }
    return md, metadata
