"""PDF → image adapter using PyMuPDF (fitz).

Renders each PDF page as a PNG image for downstream OCR processing.
Requires the optional [pdf] extra (pymupdf).
"""

from __future__ import annotations

import importlib
import hashlib
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple


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


def redact_text_pdf(
    source_path: str,
    redacted_path: str,
    rules,
    redact_fn,
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
) -> Tuple[dict, dict]:
    """Permanently remove sensitive text from a text-layer PDF."""
    _check_fitz_available()
    import fitz

    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    doc = fitz.open(source_path)
    if doc.needs_pass:
        doc.close()
        raise ValueError("Encrypted PDF is not supported without a password")

    all_entities = []
    all_occurrences = []
    all_warnings = []
    entity_index = {}
    entity_counts = {}
    profile_name = getattr(redact_fn, "_profile_name", None)
    located_count = 0

    try:
        if not any(page.get_text().strip() for page in doc):
            raise ValueError(
                "PDF has no usable text layer. Use 'redact-scan' with [pdf]+[ocr]."
            )

        for page_number, page in enumerate(doc, start=1):
            page_text = page.get_text()
            if not page_text.strip():
                continue
            page_labels = []
            _redacted, page_map, page_audit = redact_fn(
                page_text,
                rules,
                hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                mode,
                level,
                model_dir,
            )
            if profile_name is None:
                profile_name = page_map.get("profile")
            page_entities = {e["id"]: e for e in page_map.get("entities", [])}

            page_occurrences = page_map.get("occurrences", [])
            occurrence_engines = {}
            for occurrence in page_occurrences:
                occurrence_engines.setdefault(
                    occurrence["entity_id"], occurrence.get("engine", "unknown")
                )

            for page_entity_id, entity in page_entities.items():
                if page_entity_id not in occurrence_engines:
                    continue
                original = entity["original"]
                rectangles = page.search_for(original)
                if not rectangles:
                    raise RuntimeError(
                        f"Unable to locate a detected {entity['entity_type']} on PDF page {page_number}"
                    )

                key = (entity["entity_type"], original)
                if key not in entity_index:
                    entity_type = entity["entity_type"]
                    entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
                    entity_id = f"{entity_type}_{entity_counts[entity_type]}"
                    entity_index[key] = entity_id
                    all_entities.append({
                        "id": entity_id,
                        "entity_type": entity_type,
                        "original": original,
                        "replacement": entity["replacement"],
                        "engines": list(entity.get("engines", [])),
                    })
                entity_id = entity_index[key]

                for rect in rectangles:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page_labels.append((rect, entity["replacement"]))
                    located_count += 1
                    all_occurrences.append({
                        "entity_id": entity_id,
                        "engine": occurrence_engines[page_entity_id],
                        "page": page_number,
                        "rectangles": [list(rect)],
                    })

            if page_occurrences:
                page.apply_redactions()
                for rect, replacement in page_labels:
                    page.insert_text(
                        (rect.x0, rect.y1 - 2),
                        replacement,
                        fontname="china-s",
                        fontsize=max(4, min(10, rect.height * 0.75)),
                        color=(0, 0, 0),
                    )

            for warning in page_audit.get("warnings", []):
                all_warnings.append({**warning, "page": page_number})

        if all_occurrences and located_count == 0:
            raise RuntimeError("PDF redaction located no sensitive text")

        # Hidden containers must not retain identifying content.
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

        doc.save(redacted_path, garbage=4, clean=True, deflate=True)
    finally:
        doc.close()

    # Reopen and enforce the residual gate across extractable PDF containers.
    output = fitz.open(redacted_path)
    try:
        searchable = "\n".join(page.get_text() for page in output)
        searchable += "\n" + "\n".join(str(v) for v in output.metadata.values())
        searchable += "\n" + "\n".join(str(row) for row in output.get_toc())
        searchable += "\n" + "\n".join(output.embfile_names())
        residual_originals = [
            e["original"] for e in all_entities if e["original"] and e["original"] in searchable
        ]
    finally:
        output.close()
    if residual_originals:
        Path(redacted_path).unlink(missing_ok=True)
        raise RuntimeError("Sensitive text remains in redacted PDF; output removed")

    redacted_sha = hashlib.sha256(Path(redacted_path).read_bytes()).hexdigest()
    by_type = {}
    by_engine = {}
    for occurrence in all_occurrences:
        entity = next(e for e in all_entities if e["id"] == occurrence["entity_id"])
        by_type[entity["entity_type"]] = by_type.get(entity["entity_type"], 0) + 1
        engine = occurrence["engine"]
        by_engine[engine] = by_engine.get(engine, 0) + 1

    map_data = {
        "schema_version": "1.1",
        "document_type": "pdf",
        "pipeline": "text-pdf-redaction",
        "verification": "redacted-content",
        "restore_supported": False,
        "source_file": Path(source_path).name,
        "redacted_file": Path(redacted_path).name,
        "source_sha256": source_sha,
        "redacted_sha256": redacted_sha,
        "profile": profile_name,
        "level": level,
        "mode": mode,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entities": all_entities,
        "occurrences": all_occurrences,
    }
    audit_data = {
        "schema_version": "1.1",
        "document_type": "pdf",
        "verification": {"type": "redacted-content", "passed": True},
        "restore_supported": False,
        "summary": {
            "total_entities": len(all_entities),
            "total_occurrences": len(all_occurrences),
            "by_entity_type": by_type,
            "by_engine": by_engine,
        },
        "residual_scan": {"passed": True, "findings": []},
        "warnings": all_warnings,
    }
    return map_data, audit_data
