"""Seal/stamp detection using OpenCV red HSV threshold + contour analysis.

Best-effort: may miss seals, may false-positive. User can adjust/delete.

Detection pipeline:
1. Convert page image to HSV
2. Threshold red hue (H: 0-10 ∪ 170-180, S: 80-255, V: 80-255)
3. Morphological close to fill gaps
4. Find contours
5. Filter by: area > min_area, circularity > min_circularity
6. Return bounding boxes in page-normalized coordinates
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class SealBox:
    """A detected seal/stamp in page-normalized coordinates."""
    page: int
    x: float           # [0,1]
    y: float           # [0,1]
    width: float       # [0,1]
    height: float      # [0,1]
    confidence: float  # circularity score
    area_ratio: float  # area as fraction of page area


def _check_opencv() -> None:
    try:
        import importlib
        importlib.import_module("cv2")
    except ImportError:
        raise ImportError(
            "OpenCV is required for seal detection.\n"
            "Install with: pip install opencv-python-headless"
        )


def _circularity(contour) -> float:
    """Compute circularity of a contour: 4π·area / perimeter²."""
    import cv2
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if perimeter == 0:
        return 0
    return (4 * math.pi * area) / (perimeter * perimeter)


def detect_seals_in_image(
    image_path: str,
    page_number: int = 1,
    image_width: Optional[int] = None,
    image_height: Optional[int] = None,
    min_area_ratio: float = 0.001,     # min 0.1% of page area
    max_area_ratio: float = 0.15,      # max 15% of page area
    min_circularity: float = 0.4,      # fairly round
) -> List[SealBox]:
    """Detect red seals/stamps in an image.

    Args:
        image_path: Path to page image (PNG/JPG).
        page_number: 1-indexed page number.
        image_width: Image width in pixels (for normalization).
        image_height: Image height in pixels (for normalization).
        min_area_ratio: Minimum contour area as fraction of image area.
        max_area_ratio: Maximum contour area as fraction of image area.
        min_circularity: Minimum circularity score (0-1).

    Returns:
        List of SealBox in page-normalized coordinates.
    """
    _check_opencv()
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    h, w = img.shape[:2]
    if image_width is None:
        image_width = w
    if image_height is None:
        image_height = h

    total_area = w * h
    min_area = total_area * min_area_ratio
    max_area = total_area * max_area_ratio

    # Convert to HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Red hue: 0-10 and 170-180
    lower_red1 = np.array([0, 80, 80])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 80, 80])
    upper_red2 = np.array([180, 255, 255])

    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    red_mask = cv2.bitwise_or(mask1, mask2)

    # Morphological close to fill small gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    seals: List[SealBox] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue

        circ = _circularity(contour)
        if circ < min_circularity:
            continue

        # Bounding rect
        rx, ry, rw, rh = cv2.boundingRect(contour)

        # Normalize to [0,1]
        nx = rx / w
        ny = ry / h
        nw = rw / w
        nh = rh / h

        seals.append(SealBox(
            page=page_number,
            x=round(nx, 6),
            y=round(ry / h, 6),
            width=round(nw, 6),
            height=round(nh, 6),
            confidence=round(circ, 4),
            area_ratio=round(area / total_area, 6),
        ))

    # Sort by area (largest first)
    seals.sort(key=lambda s: s.area_ratio, reverse=True)
    return seals


def detect_seals_in_pdf(
    pdf_path: str,
    dpi: int = 200,
    **kwargs,
) -> Tuple[List[SealBox], dict]:
    """Detect seals in all pages of a PDF.

    Returns:
        (seal_boxes, manifest) with per-page metadata.
    """
    _check_opencv()
    from .adapters.pdf_adapter import render_pdf_pages
    import fitz

    result = render_pdf_pages(pdf_path, dpi=dpi)
    doc = fitz.open(pdf_path)

    all_seals: List[SealBox] = []
    pages_meta = []

    try:
        for i, page_img in enumerate(result.page_images):
            page = doc[i]
            page_w = page.rect.width
            page_h = page.rect.height

            seals = detect_seals_in_image(
                page_img.image_path,
                page_number=i + 1,
                image_width=page_img.width,
                image_height=page_img.height,
                **kwargs,
            )
            all_seals.extend(seals)

            pages_meta.append({
                "pageNumber": i + 1,
                "pageWidth": round(page_w, 2),
                "pageHeight": round(page_h, 2),
                "imageWidth": page_img.width,
                "imageHeight": page_img.height,
                "dpi": dpi,
                "sealsDetected": len(seals),
            })
    finally:
        doc.close()
        # Cleanup temp images
        import shutil
        temp_dir = Path(result.page_images[0].image_path).parent if result.page_images else None
        if temp_dir and temp_dir.name.startswith("legal_desens_pdf_"):
            shutil.rmtree(temp_dir, ignore_errors=True)

    manifest = {
        "sourceFile": str(Path(pdf_path).name),
        "totalPages": result.total_pages,
        "dpi": dpi,
        "pages": pages_meta,
        "totalSeals": len(all_seals),
    }

    return all_seals, manifest
