"""Prepare: unified preview + manifest generation for review workflow.

Generates a Markdown preview, manifest with source locators, and candidate
detection results without modifying the source document.

Supports: DOCX, text-layer PDF, scanned PDF (via OCR).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .profile import Profile, load_profile, resolve_profile_name
from .redact import (
    LabelAllocator,
    _build_occurrences,
    _remap_ner_types,
    _remaining_loc_to_address,
    _scan_time_expressions,
    scan_ner_with_warnings,
)
from .engine.merge import merge_spans
from .engine.regex import scan_regex
from .engine.span import Span
from .rules import Rule


def _gen_id(prefix: str = "blk") -> str:
    """Generate a short unique ID."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# DOCX preparation
# ---------------------------------------------------------------------------

def _prepare_docx(
    source_path: str,
    rules: List[Rule],
    profile: Profile,
    mode: str,
    model_dir: Optional[str] = None,
) -> Tuple[List[dict], str, str]:
    """Extract DOCX text blocks with source locators.

    Returns (blocks, full_text, document_kind).
    """
    from .adapters.docx_adapter import DOCXAdapter, _is_text_part

    adapter = DOCXAdapter()
    full_text, segments = adapter.extract_text(source_path)

    blocks = []
    offset = 0
    for seg in segments:
        text = seg["text"]
        block_id = _gen_id("blk")
        # Determine block kind
        part = seg["part"]
        if "header" in part or "footer" in part:
            kind = "paragraph"  # treat header/footer as paragraph
        elif "table" in part:
            kind = "table"
        else:
            kind = "paragraph"

        blocks.append({
            "id": block_id,
            "kind": kind,
            "text": text,
            "char_offset": offset,
            "sourceLocator": {
                "type": "docx",
                "part": part,
                "paragraph_index": seg["paragraph_index"],
            },
        })
        offset += len(text) + 1  # +1 for newline join

    return blocks, full_text, "docx"


# ---------------------------------------------------------------------------
# Text PDF preparation
# ---------------------------------------------------------------------------

def _prepare_text_pdf(
    source_path: str,
    rules: List[Rule],
    profile: Profile,
    mode: str,
    model_dir: Optional[str] = None,
) -> Tuple[List[dict], str, str]:
    """Extract text-layer PDF blocks with page-level source locators.

    Handles hybrid PDFs: pages with text layer use text extraction,
    pages without text layer fall through to OCR.

    For text pages, also extracts a charMap: one entry per character in
    block.text, each containing {page, rect: [x0,y0,x1,y1]}. Any
    character missing a coordinate causes a fail-closed error.

    Returns (blocks, full_text, document_kind).
    """
    try:
        import fitz
    except ImportError:
        raise ImportError(
            "PyMuPDF is required for PDF processing. Install with:\n"
            "  pip install legal-desens[pdf]"
        )

    doc = fitz.open(source_path)
    if doc.needs_pass:
        doc.close()
        raise ValueError("Encrypted PDF is not supported without a password")

    blocks = []
    full_parts = []
    offset = 0
    has_text_pages = False
    has_ocr_pages = False

    try:
        ocr_engine = None
        for page_number, page in enumerate(doc, start=1):
            page_text = page.get_text().strip()
            if page_text:
                has_text_pages = True
                # Extract character-level coordinates using dict
                # (rawdict returns empty text for some CJK fonts; dict is more reliable)
                raw = page.get_text("dict")
                # Build a flat list of (char, rect) from all spans in all blocks/lines
                char_entries = []  # list of {"char": str, "rect": [x0,y0,x1,y1]}
                for block in raw.get("blocks", []):
                    if block.get("type") != 0:  # 0 = text block
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            span_text = span.get("text", "")
                            span_bbox = span.get("bbox")  # [x0,y0,x1,y1]
                            if not span_text or not span_bbox:
                                continue
                            # Distribute bbox proportionally across characters
                            x0, y0, x1, y1 = span_bbox
                            char_width = (x1 - x0) / max(len(span_text), 1)
                            for i, ch in enumerate(span_text):
                                cx0 = x0 + i * char_width
                                cx1 = cx0 + char_width
                                char_entries.append({
                                    "char": ch,
                                    "rect": [cx0, y0, cx1, y1],
                                    "page": page_number,
                                })

                # Build block text by joining all char entries' text
                block_text = "".join(e["char"] for e in char_entries).strip()
                if not block_text:
                    continue

                # Validate: every character in block_text must have a coordinate
                # We rebuild charMap by matching characters from char_entries to block_text
                # Since strip() may remove leading/trailing whitespace, we need to
                # find the matching subsequence in char_entries
                block_chars = list(block_text)
                char_map = []
                ci = 0  # index into char_entries
                for bc in block_chars:
                    # Skip whitespace in char_entries to find matching char
                    while ci < len(char_entries) and char_entries[ci]["char"] != bc:
                        ci += 1
                    if ci < len(char_entries):
                        char_map.append({
                            "page": char_entries[ci]["page"],
                            "rect": char_entries[ci]["rect"],
                        })
                        ci += 1
                    else:
                        # Character not found in extracted entries — fail closed
                        raise ValueError(
                            f"PDF char coordinate mapping failed: char '{bc}' at "
                            f"offset {offset + len(char_map)} on page {page_number} "
                            f"has no bounding box"
                        )

                block_id = _gen_id("blk")
                blocks.append({
                    "id": block_id,
                    "kind": "paragraph",
                    "text": block_text,
                    "char_offset": offset,
                    "charMap": char_map,
                    "sourceLocator": {
                        "type": "pdf-text",
                        "page": page_number,
                    },
                })
                full_parts.append(block_text)
                offset += len(block_text) + 1
            else:
                has_ocr_pages = True
                from .engine.ocr import run_rapidocr, get_rapidocr_instance

                if ocr_engine is None:
                    ocr_engine = get_rapidocr_instance()
                zoom = 200 / 72.0
                matrix = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix)
                import tempfile
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        temp_path = tmp.name
                    pix.save(temp_path)
                    ocr_result = run_rapidocr(
                        temp_path,
                        confidence_threshold=0.5,
                        engine=ocr_engine,
                    )
                finally:
                    if temp_path:
                        Path(temp_path).unlink(missing_ok=True)

                for line_idx, line in enumerate(ocr_result.lines):
                    if not line.text.strip():
                        continue
                    block_id = _gen_id("blk")
                    blocks.append({
                        "id": block_id,
                        "kind": "paragraph",
                        "text": line.text,
                        "char_offset": offset,
                        "sourceLocator": {
                            "type": "pdf-scan",
                            "page": page_number,
                            "line_index": line_idx,
                            "polygon": getattr(line, "box", None),
                            "confidence": getattr(line, "confidence", None),
                        },
                    })
                    full_parts.append(line.text)
                    offset += len(line.text) + 1

        if has_text_pages and has_ocr_pages:
            doc_kind = "pdf-hybrid"
        elif has_ocr_pages:
            doc_kind = "pdf-scan"
        else:
            doc_kind = "pdf-text"
    finally:
        doc.close()

    full_text = "\n".join(full_parts)
    return blocks, full_text, doc_kind


# ---------------------------------------------------------------------------
# Scanned PDF / Image preparation
# ---------------------------------------------------------------------------

def _prepare_scanned_pdf(
    source_path: str,
    rules: List[Rule],
    profile: Profile,
    mode: str,
    model_dir: Optional[str] = None,
) -> Tuple[List[dict], str, str]:
    """OCR scanned PDF/image and extract blocks with polygon locators.

    Returns (blocks, full_text, document_kind).
    """
    from .engine.ocr import run_rapidocr, get_rapidocr_instance

    suffix = Path(source_path).suffix.lower()

    # If PDF, render pages to images first
    if suffix == ".pdf":
        try:
            from .adapters.pdf_adapter import render_pdf_pages
            render_result = render_pdf_pages(source_path, dpi=200)
            page_images = render_result.page_images
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for scanned PDF. Install with:\n"
                "  pip install legal-desens[pdf]"
            )
    else:
        # Single image file
        from .adapters.pdf_adapter import PDFPageImage
        page_images = [PDFPageImage(page_number=1, image_path=source_path, width=0, height=0)]

    ocr_engine = get_rapidocr_instance()
    blocks = []
    full_parts = []

    for page_img in page_images:
        ocr_result = run_rapidocr(
            page_img.image_path,
            confidence_threshold=0.5,
            engine=ocr_engine,
        )

        # Group OCR lines into blocks (each line or small group becomes a block)
        for line_idx, line in enumerate(ocr_result.lines):
            if not line.text.strip():
                continue

            block_id = _gen_id("blk")
            blocks.append({
                "id": block_id,
                "kind": "paragraph",
                "text": line.text,
                "char_offset": sum(len(p) + 1 for p in full_parts),
                "sourceLocator": {
                    "type": "pdf-scan",
                    "page": page_img.page_number,
                    "line_index": line_idx,
                    "polygon": getattr(line, "box", None),
                    "confidence": getattr(line, "confidence", None),
                },
            })
            full_parts.append(line.text)

    full_text = "\n".join(full_parts)
    return blocks, full_text, "pdf-scan"


# ---------------------------------------------------------------------------
# Candidate detection
# ---------------------------------------------------------------------------

def _detect_candidates(
    full_text: str,
    blocks: List[dict],
    rules: List[Rule],
    profile: Profile,
    mode: str = "regex-only",
    model_dir: Optional[str] = None,
) -> Tuple[List[dict], List[dict]]:
    """Run regex + NER detection and map spans to blocks.

    Returns (candidates, warnings).
    """
    # Run regex detection
    spans = scan_regex(full_text, rules)

    # Run NER if requested
    ner_warnings = []
    if mode != "regex-only":
        try:
            ner_spans, ner_warnings = scan_ner_with_warnings(full_text, model_dir)
            from .engine.ner_postprocess import postprocess_ner_spans
            ner_spans, postprocess_warnings = postprocess_ner_spans(
                ner_spans, full_text,
                validate_org=False, merge_address_parts=False,
            )
            ner_warnings.extend(postprocess_warnings)
            spans.extend(ner_spans)
            _remap_ner_types(spans)
        except (RuntimeError, FileNotFoundError) as e:
            ner_warnings.append({
                "type": "ner_unavailable",
                "message": f"NER detection skipped: {e}",
            })

    # TIME detection for profiles that redact it
    if profile.should_redact("TIME"):
        spans.extend(_scan_time_expressions(
            full_text,
            discovery_start=max((s.discovery_order for s in spans), default=-1) + 1,
        ))

    # Address merge
    if profile.address_merge:
        from .engine.address_merge import merge_addresses
        spans = merge_addresses(spans, full_text)
    spans = _remaining_loc_to_address(spans)

    # Bank account detection
    from .engine.bank_account import detect_bank_accounts
    bank_spans, bank_warnings = detect_bank_accounts(full_text, spans)
    spans.extend(bank_spans)
    ner_warnings.extend(bank_warnings)

    # Merge overlapping spans
    kept, discarded = merge_spans(spans)

    # Filter by profile
    redact_types = profile.redact_entity_types(s.entity_type for s in kept)
    kept = [s for s in kept if s.entity_type in redact_types]

    # Map spans to blocks
    block_char_offsets = {blk["id"]: blk["char_offset"] for blk in blocks}
    block_ids = sorted(block_char_offsets.keys(), key=lambda bid: block_char_offsets[bid])

    candidates = []
    for span in kept:
        # Find which block this span belongs to
        block_id = None
        local_start = span.start
        local_end = span.end

        for bid in block_ids:
            blk_offset = block_char_offsets[bid]
            blk = next(b for b in blocks if b["id"] == bid)
            blk_text = blk["text"]
            if span.start >= blk_offset and span.start < blk_offset + len(blk_text):
                block_id = bid
                local_start = span.start - blk_offset
                local_end = min(span.end - blk_offset, len(blk_text))
                break

        if block_id is None:
            # Span doesn't map to any block; skip
            continue

        candidates.append({
            "id": _gen_id("cand"),
            "blockId": block_id,
            "start": local_start,
            "end": local_end,
            "entityType": span.entity_type,
            "engine": span.engine,
            "confidence": getattr(span, "confidence", None),
            "sourceLocator": next(
                (blk["sourceLocator"] for blk in blocks if blk["id"] == block_id), {}
            ),
        })

    # Build warnings from discarded spans
    warnings = []
    for d in discarded:
        warnings.append({
            "type": "overlapped_span_discarded",
            "entity_type": d.entity_type,
            "start": d.start,
            "end": d.end,
            "text_preview": d.text[:20],
            "engine": d.engine,
        })
    warnings.extend(ner_warnings)

    return candidates, warnings


# ---------------------------------------------------------------------------
# Main prepare entry point
# ---------------------------------------------------------------------------

def prepare(
    source_path: str,
    rules: List[Rule],
    level: str = "strict",
    mode: str = "regex-only",
    model_dir: Optional[str] = None,
    profile: Optional[Profile] = None,
) -> Tuple[dict, str, str]:
    """Prepare a document for review: extract blocks, detect candidates.

    Args:
        source_path: Path to source document.
        rules: Desensitization rules.
        level: Redaction level (strict/labor).
        mode: "regex-only" or "regex+ner".
        model_dir: Path to NER model directory.
        profile: Profile for redaction policy.

    Returns:
        (manifest, preview_md, source_map_json_string)
        - manifest: the full PreviewManifest dict
        - preview_md: Markdown preview text
        - source_map_json: JSON string of the source map
    """
    if profile is None:
        profile_name = resolve_profile_name(None, level)
        profile = load_profile(profile_name)

    source_path_obj = Path(source_path)
    source_sha256 = hashlib.sha256(source_path_obj.read_bytes()).hexdigest()
    ext = source_path_obj.suffix.lower()

    # Detect format and extract blocks
    if ext == ".docx":
        blocks, full_text, document_kind = _prepare_docx(
            source_path, rules, profile, mode, model_dir
        )
    elif ext == ".pdf":
        blocks, full_text, document_kind = _prepare_text_pdf(
            source_path, rules, profile, mode, model_dir
        )
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
        blocks, full_text, document_kind = _prepare_scanned_pdf(
            source_path, rules, profile, mode, model_dir
        )
    else:
        # Treat as text
        text = source_path_obj.read_text(encoding="utf-8")
        blocks = [{
            "id": _gen_id("blk"),
            "kind": "paragraph",
            "text": text,
            "char_offset": 0,
            "sourceLocator": {"type": "text", "file": source_path_obj.name},
        }]
        full_text = text
        document_kind = "text"

    # Detect candidates
    candidates, warnings = _detect_candidates(
        full_text, blocks, rules, profile, mode, model_dir
    )

    # Generate preview markdown
    preview_parts = []
    for block in blocks:
        if block["kind"] == "heading":
            preview_parts.append(f"\n{block['text']}\n")
        elif block["kind"] == "page-break":
            preview_parts.append(f"\n---\n")
        elif block["kind"] == "table":
            preview_parts.append(f"\n{block['text']}\n")
        else:
            preview_parts.append(block["text"])
    preview_md = "\n".join(preview_parts)

    # Build source map (for export pipeline to locate positions in original)
    source_map = {
        "schema_version": "1.0",
        "source_sha256": source_sha256,
        "document_kind": document_kind,
        "blocks": [
            {
                "id": blk["id"],
                "sourceLocator": blk["sourceLocator"],
                "char_offset": blk["char_offset"],
                "text": blk["text"],
                "text_length": len(blk["text"]),
                **({"charMap": blk["charMap"]} if "charMap" in blk else {}),
            }
            for blk in blocks
        ],
    }

    # Build manifest
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "schemaVersion": "1.0",
        "sourceSha256": source_sha256,
        "documentKind": document_kind,
        "createdAt": now,
        "blocks": blocks,
        "candidates": candidates,
        "warnings": warnings,
    }

    source_map_json = json.dumps(source_map, ensure_ascii=False, indent=2)

    return manifest, preview_md, source_map_json
