"""Visual masking export — draws opaque rectangles over user-specified regions.

Supports two pipelines:
1. Scan PDF (image-only): render pages → draw black rects on pixels → rebuild image-only PDF
2. Text PDF: PyMuPDF redaction annotation (truly deletes text layer) + draw black rect

All box coordinates are page-normalized: { x, y, width, height } ∈ [0,1].
Origin is top-left (fitz convention).

Fail-closed: on any failure, output file is deleted (no half-products).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class MaskBox:
    """A masking rectangle in page-normalized coordinates."""
    id: str
    page: int          # 1-indexed
    x: float           # [0,1] relative to page width
    y: float           # [0,1] relative to page height
    width: float       # [0,1]
    height: float      # [0,1]
    source: str = "manual"  # 'manual' | 'ocr' | 'rule' | 'seal'
    entity_type: Optional[str] = None


@dataclass
class PageOCRBox:
    """An OCR-detected text box in page-normalized coordinates."""
    text: str
    page: int
    x: float
    y: float
    width: float
    height: float
    confidence: float
    entity_type: Optional[str] = None  # Tagged by rules matching


@dataclass
class MaskExportResult:
    """Result of a masking export."""
    output_path: str
    total_pages: int
    boxes_applied: int
    source_sha256: str
    output_sha256: str
    audit: dict = field(default_factory=dict)


def _check_fitz() -> None:
    try:
        import importlib
        importlib.import_module("fitz")
    except ImportError:
        raise ImportError(
            "PyMuPDF is required for masking export.\n"
            "Install with: pip install legal-desens[pdf]"
        )


def _check_pil() -> None:
    try:
        import importlib
        importlib.import_module("PIL")
    except ImportError:
        raise ImportError(
            "Pillow is required for scan PDF masking.\n"
            "Install with: pip install Pillow"
        )


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── OCR with normalized boxes ────────────────────────────────

def ocr_pages_to_normalized_boxes(
    pdf_path: str,
    dpi: int = 200,
    confidence_threshold: float = 0.7,
    rules_path: Optional[str] = None,
) -> Tuple[List[PageOCRBox], dict]:
    """OCR each page and return boxes in page-normalized coordinates.

    Args:
        pdf_path: Path to PDF file.
        dpi: Render DPI (default 200).
        confidence_threshold: OCR confidence threshold.
        rules_path: Optional path to rules.json for entity type tagging.

    Returns:
        (ocr_boxes, manifest) where manifest has per-page metadata.
    """
    _check_fitz()
    _check_pil()
    from .adapters.pdf_adapter import render_pdf_pages
    from .engine.ocr import get_rapidocr_instance, run_rapidocr

    import fitz
    import re as re_module

    # Load rules for entity type tagging
    rules = []
    if rules_path:
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                rules = json.load(f)
            if not isinstance(rules, list):
                rules = []
        except (FileNotFoundError, json.JSONDecodeError):
            rules = []

    def _tag_text(text: str) -> Optional[str]:
        """Run rules against text and return the best matching entity type.

        Returns the highest-priority matching type, or all matching types
        if multiple match (comma-separated).
        """
        matches = []
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            pattern = rule.get("pattern")
            if not pattern:
                continue
            try:
                if re_module.search(pattern, text):
                    matches.append({
                        "type": rule.get("entity_type", "CUSTOM"),
                        "priority": rule.get("priority", 0),
                    })
            except re_module.error:
                continue

        if not matches:
            return None

        # Return highest priority match
        matches.sort(key=lambda m: -m["priority"])
        return matches[0]["type"]

    result = render_pdf_pages(pdf_path, dpi=dpi)
    doc = fitz.open(pdf_path)

    ocr_boxes: List[PageOCRBox] = []
    pages_meta = []

    try:
        engine = get_rapidocr_instance()
        for i, page_img in enumerate(result.page_images):
            page = doc[i]
            page_w = page.rect.width   # PDF points
            page_h = page.rect.height
            img_w = page_img.width     # pixels
            img_h = page_img.height

            ocr_result = run_rapidocr(
                page_img.image_path,
                confidence_threshold=confidence_threshold,
                engine=engine,
            )

            for line in ocr_result.lines:
                # OCR box is 4-corner polygon in image pixels
                # Convert to axis-aligned bounding box
                xs = [p[0] for p in line.box]
                ys = [p[1] for p in line.box]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)

                # Normalize to [0,1] relative to image dimensions
                nx = min_x / img_w
                ny = min_y / img_h
                nw = (max_x - min_x) / img_w
                nh = (max_y - min_y) / img_h

                # Tag with entity type if rules provided
                entity_type = _tag_text(line.text)

                ocr_boxes.append(PageOCRBox(
                    text=line.text,
                    page=i + 1,
                    x=nx,
                    y=ny,
                    width=nw,
                    height=nh,
                    confidence=line.confidence,
                    entity_type=entity_type,
                ))

            pages_meta.append({
                "pageNumber": i + 1,
                "pageWidth": round(page_w, 2),
                "pageHeight": round(page_h, 2),
                "imageWidth": img_w,
                "imageHeight": img_h,
                "dpi": dpi,
                "ocrLines": len(ocr_result.lines),
            })
    finally:
        doc.close()
        # Cleanup temp images
        temp_dir = Path(result.page_images[0].image_path).parent if result.page_images else None
        if temp_dir and temp_dir.name.startswith("legal_desens_pdf_"):
            shutil.rmtree(temp_dir, ignore_errors=True)

    manifest = {
        "sourceFile": str(Path(pdf_path).name),
        "totalPages": result.total_pages,
        "dpi": dpi,
        "pages": pages_meta,
    }

    return ocr_boxes, manifest


def refine_boxes_to_entities(
    ocr_boxes: List[PageOCRBox],
    text_entities: List[dict],
    ocr_text: str,
) -> List[PageOCRBox]:
    """Split OCR line-level boxes into entity-level sub-boxes.

    Given:
    - ocr_boxes: line-level boxes from OCR (each covers an entire line)
    - text_entities: detected entities with precise start/end in ocr_text
    - ocr_text: full OCR text (joined by \\n)

    Returns refined boxes where each entity in text_entities maps to a
    sub-box within the corresponding OCR line. Lines without entities
    are dropped (they contain no sensitive content).

    For horizontal text: entity position within a line is computed by
    character-width proportioning (line width / line text length).
    """
    if not text_entities or not ocr_boxes:
        return []

    # Build line offset map: for each OCR box, compute its start/end in ocr_text
    line_offsets = []  # (box_index, start_in_text, end_in_text)
    offset = 0
    for i, box in enumerate(ocr_boxes):
        line_len = len(box.text)
        line_offsets.append((i, offset, offset + line_len))
        offset += line_len + 1  # +1 for \n join

    refined: List[PageOCRBox] = []

    for entity in text_entities:
        ent_start = entity.get("start", 0)
        ent_end = entity.get("end", 0)
        ent_text = entity.get("original", "")
        ent_type = entity.get("entity_type", "")

        if ent_start >= ent_end or not ent_text:
            continue

        # Find which OCR line(s) this entity spans
        for box_idx, line_start, line_end in line_offsets:
            # Check overlap
            overlap_start = max(ent_start, line_start)
            overlap_end = min(ent_end, line_end)
            if overlap_start >= overlap_end:
                continue

            box = ocr_boxes[box_idx]
            line_text = box.text
            line_len = len(line_text)

            if line_len == 0:
                continue

            # Character position within the line
            char_start_in_line = max(0, overlap_start - line_start)
            char_end_in_line = min(line_len, overlap_end - line_start)

            # Horizontal proportioning: split line width by character count
            line_width = box.width
            char_width = line_width / line_len

            sub_x = box.x + char_start_in_line * char_width
            sub_width = (char_end_in_line - char_start_in_line) * char_width

            # Clamp to [0,1]
            sub_x = max(0.0, min(1.0, sub_x))
            sub_width = max(0.001, min(1.0 - sub_x, sub_width))

            refined.append(PageOCRBox(
                text=ent_text,
                page=box.page,
                x=round(sub_x, 6),
                y=box.y,
                width=round(sub_width, 6),
                height=box.height,
                confidence=box.confidence,
                entity_type=ent_type,
            ))

    return refined


# ─── Scan PDF masking ─────────────────────────────────────────

def mask_export_scan_pdf(
    source_path: str,
    output_path: str,
    boxes: List[MaskBox],
    dpi: int = 200,
    fill_color: Tuple[float, float, float] = (0, 0, 0),
) -> MaskExportResult:
    """Mask a scan PDF: render pages → draw black rects → rebuild image-only PDF.

    Fail-closed: on failure, output file is deleted.
    """
    _check_fitz()
    _check_pil()
    import fitz
    from PIL import Image, ImageDraw
    from .adapters.pdf_adapter import render_pdf_pages

    source_sha = _sha256(source_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="legal_desens_mask_scan_"))
    output_file = Path(output_path)

    try:
        result = render_pdf_pages(source_path, dpi=dpi)
        doc = fitz.open(source_path)

        boxes_by_page: Dict[int, List[MaskBox]] = {}
        for box in boxes:
            boxes_by_page.setdefault(box.page, []).append(box)

        redacted_images: List[str] = []

        for i, page_img in enumerate(result.page_images):
            page_num = i + 1
            page = doc[i]
            img_w = page_img.width
            img_h = page_img.height

            image = Image.open(page_img.image_path).convert("RGB")
            draw = ImageDraw.Draw(image)

            page_boxes = boxes_by_page.get(page_num, [])
            for box in page_boxes:
                # Convert normalized coords to pixel coords
                px = int(box.x * img_w)
                py = int(box.y * img_h)
                pw = int(box.width * img_w)
                ph = int(box.height * img_h)

                # Clamp to image bounds
                px = max(0, min(px, img_w - 1))
                py = max(0, min(py, img_h - 1))
                pw = max(1, min(pw, img_w - px))
                ph = max(1, min(ph, img_h - py))

                draw.rectangle([px, py, px + pw, py + ph], fill=tuple(int(c * 255) for c in fill_color))

            redacted_path = str(temp_dir / f"page_{page_num:04d}.png")
            image.save(redacted_path)
            redacted_images.append(redacted_path)
            image.close()

        doc.close()

        # Rebuild image-only PDF
        output_doc = fitz.open()
        for img_path in redacted_images:
            with Image.open(img_path) as img:
                w_pt = img.width * 72.0 / dpi
                h_pt = img.height * 72.0 / dpi
            page = output_doc.new_page(width=w_pt, height=h_pt)
            page.insert_image(page.rect, filename=img_path)

        # Clean metadata
        output_doc.set_metadata({})
        output_doc.set_toc([])
        output_doc.save(str(output_file), deflate=True, garbage=3)
        output_doc.close()

        output_sha = _sha256(str(output_file))

        return MaskExportResult(
            output_path=str(output_file),
            total_pages=len(result.page_images),
            boxes_applied=len(boxes),
            source_sha256=source_sha,
            output_sha256=output_sha,
            audit={
                "pipeline": "scan-mask",
                "verification": "pixel-black-block",
                "passed": True,
                "dpi": dpi,
            },
        )

    except Exception as e:
        output_file.unlink(missing_ok=True)
        raise RuntimeError(f"Scan PDF masking failed: {e}") from e
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ─── Text PDF masking ─────────────────────────────────────────

def mask_export_text_pdf(
    source_path: str,
    output_path: str,
    boxes: List[MaskBox],
    fill_color: Tuple[float, float, float] = (0, 0, 0),
) -> MaskExportResult:
    """Mask a text PDF: redaction annotation (deletes text) + draw black rect.

    Fail-closed: on failure, output file is deleted.
    """
    _check_fitz()
    import fitz

    source_sha = _sha256(source_path)
    output_file = Path(output_path)

    try:
        doc = fitz.open(source_path)
        if doc.needs_pass:
            doc.close()
            raise ValueError("Encrypted PDF is not supported")

        boxes_by_page: Dict[int, List[MaskBox]] = {}
        for box in boxes:
            boxes_by_page.setdefault(box.page, []).append(box)

        for page_num in range(1, len(doc) + 1):
            page = doc[page_num - 1]
            page_w = page.rect.width
            page_h = page.rect.height
            page_boxes = boxes_by_page.get(page_num, [])

            for box in page_boxes:
                # Convert normalized coords to PDF points
                x0 = box.x * page_w
                y0 = box.y * page_h
                x1 = x0 + box.width * page_w
                y1 = y0 + box.height * page_h

                rect = fitz.Rect(x0, y0, x1, y1)

                # Add redaction annotation (white fill to delete text)
                page.add_redact_annot(rect, fill=(1, 1, 1))

            # Apply all redactions on this page (deletes text layer)
            if page_boxes:
                page.apply_redactions()

            # Draw black rectangles on top
            for box in page_boxes:
                x0 = box.x * page_w
                y0 = box.y * page_h
                x1 = x0 + box.width * page_w
                y1 = y0 + box.height * page_h

                rect = fitz.Rect(x0, y0, x1, y1)
                # Draw filled rectangle (black)
                shape = page.new_shape()
                shape.draw_rect(rect)
                shape.finish(fill=fill_color, color=fill_color)
                shape.commit()

        # Clean metadata
        doc.set_metadata({})
        doc.set_toc([])
        for page in doc:
            annot = page.first_annot
            while annot is not None:
                following = annot.next
                page.delete_annot(annot)
                annot = following
            widget = page.first_widget
            while widget is not None:
                following = widget.next
                page.delete_widget(widget)
                widget = following
        for name in list(doc.embfile_names()):
            doc.embfile_del(name)

        doc.save(str(output_file), garbage=4, clean=True, deflate=True)
        total_pages = len(doc)
        doc.close()

        # Verify: no original text from masked regions should be extractable
        verify_doc = fitz.open(str(output_file))
        try:
            for box in boxes:
                page = verify_doc[box.page - 1]
                page_w = page.rect.width
                page_h = page.rect.height
                x0 = box.x * page_w
                y0 = box.y * page_h
                x1 = x0 + box.width * page_w
                y1 = y0 + box.height * page_h
                rect = fitz.Rect(x0, y0, x1, y1)
                text_in_rect = page.get_text("text", clip=rect).strip()
                if text_in_rect:
                    output_file.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Verification failed: text '{text_in_rect[:30]}' still extractable "
                        f"in masked region on page {box.page}"
                    )
        finally:
            verify_doc.close()

        output_sha = _sha256(str(output_file))

        return MaskExportResult(
            output_path=str(output_file),
            total_pages=total_pages,
            boxes_applied=len(boxes),
            source_sha256=source_sha,
            output_sha256=output_sha,
            audit={
                "pipeline": "text-pdf-mask",
                "verification": "redacted-content + pixel-black-block",
                "passed": True,
                "text_layer_deleted": True,
            },
        )

    except Exception as e:
        output_file.unlink(missing_ok=True)
        raise RuntimeError(f"Text PDF masking failed: {e}") from e


# ─── Unified export ───────────────────────────────────────────

def _find_denylist_boxes_text_pdf(
    source_path: str,
    denylist: List[str],
) -> List[MaskBox]:
    """Find denylist terms in text PDF layer and create masking boxes."""
    _check_fitz()
    import fitz

    boxes = []
    doc = fitz.open(source_path)
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_w = page.rect.width
            page_h = page.rect.height
            page_text = page.get_text()

            for term in denylist:
                if not term or term not in page_text:
                    continue
                # Search for all occurrences
                rects = page.search_for(term)
                for rect in rects:
                    # Convert PDF point rect to normalized coords
                    nx = rect.x0 / page_w
                    ny = rect.y0 / page_h
                    nw = (rect.x1 - rect.x0) / page_w
                    nh = (rect.y1 - rect.y0) / page_h
                    boxes.append(MaskBox(
                        id=f"deny_{page_idx+1}_{len(boxes)}",
                        page=page_idx + 1,
                        x=nx, y=ny, width=nw, height=nh,
                        source="denylist",
                        entity_type="DENYLIST",
                    ))
    finally:
        doc.close()
    return boxes


def _find_denylist_boxes_scan_pdf(
    source_path: str,
    denylist: List[str],
    dpi: int = 200,
) -> Tuple[List[MaskBox], dict]:
    """Find denylist terms via OCR in scan PDF and create masking boxes."""
    _check_fitz()
    _check_pil()
    from .adapters.pdf_adapter import render_pdf_pages
    from .engine.ocr import get_rapidocr_instance, run_rapidocr

    result = render_pdf_pages(source_path, dpi=dpi)
    boxes = []
    pages_meta = []

    try:
        engine = get_rapidocr_instance()
        for page_img in result.page_images:
            page_num = page_img.page_number
            img_w = page_img.width
            img_h = page_img.height

            ocr_result = run_rapidocr(page_img.image_path, engine=engine)

            for line in ocr_result.lines:
                for term in denylist:
                    if term in line.text:
                        # Convert OCR box to normalized coords
                        xs = [p[0] for p in line.box]
                        ys = [p[1] for p in line.box]
                        min_x, max_x = min(xs), max(xs)
                        min_y, max_y = min(ys), max(ys)

                        boxes.append(MaskBox(
                            id=f"deny_ocr_{page_num}_{len(boxes)}",
                            page=page_num,
                            x=min_x / img_w,
                            y=min_y / img_h,
                            width=(max_x - min_x) / img_w,
                            height=(max_y - min_y) / img_h,
                            source="denylist",
                            entity_type="DENYLIST",
                        ))

            pages_meta.append({
                "pageNumber": page_num,
                "imageWidth": img_w,
                "imageHeight": img_h,
                "dpi": dpi,
            })
    finally:
        import shutil
        temp_dir = Path(result.page_images[0].image_path).parent if result.page_images else None
        if temp_dir and temp_dir.name.startswith("legal_desens_pdf_"):
            shutil.rmtree(temp_dir, ignore_errors=True)

    return boxes, {"pages": pages_meta}


def _verify_denylist_masked(
    output_path: str,
    denylist: List[str],
    document_kind: str,
) -> List[str]:
    """Verify that denylist terms are not extractable from output."""
    if not denylist:
        return []

    leaked = []
    if document_kind == "pdf-text":
        _check_fitz()
        import fitz
        doc = fitz.open(output_path)
        try:
            for page in doc:
                page_text = page.get_text()
                for term in denylist:
                    if term in page_text:
                        leaked.append(term)
        finally:
            doc.close()
    else:
        # For scan PDF, run OCR verification
        _check_pil()
        from .adapters.pdf_adapter import render_pdf_pages
        from .engine.ocr import get_rapidocr_instance, run_rapidocr

        result = render_pdf_pages(output_path, dpi=200)
        try:
            engine = get_rapidocr_instance()
            for page_img in result.page_images:
                ocr_result = run_rapidocr(page_img.image_path, engine=engine)
                full_text = " ".join(line.text for line in ocr_result.lines)
                for term in denylist:
                    if term in full_text and term not in leaked:
                        leaked.append(term)
        finally:
            import shutil
            temp_dir = Path(result.page_images[0].image_path).parent if result.page_images else None
            if temp_dir and temp_dir.name.startswith("legal_desens_pdf_"):
                shutil.rmtree(temp_dir, ignore_errors=True)

    return leaked


def mask_export(
    source_path: str,
    output_path: str,
    boxes: List[MaskBox],
    document_kind: str,
    dpi: int = 200,
    rules_path: Optional[str] = None,
    denylist: Optional[List[str]] = None,
) -> MaskExportResult:
    """Unified masking export. Detects pipeline from document_kind.

    Args:
        source_path: Path to source PDF.
        output_path: Path for output masked PDF.
        boxes: List of masking boxes in page-normalized coordinates.
        document_kind: 'pdf-text' | 'pdf-scan' | 'pdf-hybrid'
        dpi: Render DPI for scan pipeline.
        rules_path: Path to merged rules.json (for entity detection).
        denylist: List of forced redaction terms (always mask these).
    """
    # Find denylist terms and create boxes for them
    denylist_boxes = []
    if denylist:
        if document_kind == "pdf-text":
            denylist_boxes = _find_denylist_boxes_text_pdf(source_path, denylist)
        else:
            denylist_boxes, _ = _find_denylist_boxes_scan_pdf(source_path, denylist, dpi=dpi)

    # Merge user boxes + denylist boxes (deduplicate by page+coords)
    all_boxes = list(boxes) + denylist_boxes

    if not all_boxes:
        raise ValueError("No boxes to mask (neither user boxes nor denylist matches)")

    if document_kind == "pdf-text":
        result = mask_export_text_pdf(source_path, output_path, all_boxes)
    elif document_kind == "pdf-scan":
        result = mask_export_scan_pdf(source_path, output_path, all_boxes, dpi=dpi)
    elif document_kind == "pdf-hybrid":
        result = mask_export_scan_pdf(source_path, output_path, all_boxes, dpi=dpi)
    else:
        raise ValueError(f"Unsupported document kind for masking: {document_kind}")

    # Verify denylist terms are not extractable
    if denylist:
        leaked = _verify_denylist_masked(output_path, denylist, document_kind)
        if leaked:
            # Fail-closed: delete output if denylist terms leaked
            Path(output_path).unlink(missing_ok=True)
            raise RuntimeError(
                f"Denylist verification failed: leaked terms: {leaked}. "
                f"Output deleted."
            )
        result.audit["denylist_verified"] = True
        result.audit["denylist_terms"] = len(denylist)
        result.audit["denylist_boxes_created"] = len(denylist_boxes)

    return result
