"""Apply redaction decisions directly to documents.

Bypasses auto-detection (regex/NER). Uses decisions from the review
workflow to redact only user-approved positions.

Guarantees:
- 'keep' decisions: text is never modified
- 'redact' decisions: text is always modified at the specified position
- Only decision-specified positions are modified (no global re-detection)
- Every 'redact' decision produces an entity in the output map
- Overlapping, missing block, or out-of-range decisions cause failure
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Type-aware partial mask (shared with frontend maskValue)
# ---------------------------------------------------------------------------

_MASK_TABLE = {
    "PHONE":      lambda o: o[:3] + "****" + o[-4:] if len(o) >= 11 else o[:1] + "***",
    "LANDLINE":   lambda o: o[:3] + "****" + o[-4:] if len(o) >= 8 else o[:1] + "***",
    "ID_CARD":    lambda o: o[:4] + "*" * (len(o) - 8) + o[-4:] if len(o) >= 15 else o[:3] + "*" * max(1, len(o) - 6) + o[-3:],
    "PERSON":     lambda o: o[0] + "*" * max(1, len(o) - 1),
    "ORG":        lambda o: o[:2] + "*" * max(2, len(o) - 4) + o[-2:] if len(o) > 4 else o[0] + "*" * max(1, len(o) - 1),
    "EMAIL":      lambda o: o[:o.index("@")] + "***" + o[o.index("@"):] if "@" in o else o[:2] + "***",
    "BANK_CARD":  lambda o: "*" * (len(o) - 4) + o[-4:] if len(o) >= 8 else "*" * max(1, len(o) - 2) + o[-2:],
    "MONEY":      lambda o: "****" + (o[-1] if o else ""),
}


def _mask_value(original: str, entity_type: str) -> str:
    if not original:
        return ""
    fn = _MASK_TABLE.get(entity_type)
    if fn:
        try:
            return fn(original)
        except Exception:
            pass
    if entity_type in ("DATE", "TIME"):
        return "".join(c if c in "年月日号时分秒" else "*" for c in original)
    return original[0] + "***"


# ---------------------------------------------------------------------------
# Decision application result (shared interface)
# ---------------------------------------------------------------------------

class DecisionApplicationResult:
    def __init__(self):
        self.entities: List[dict] = []
        self.occurrences: List[dict] = []
        self.applied: List[dict] = []
        self.failed: List[dict] = []

    @property
    def all_applied(self) -> bool:
        return len(self.failed) == 0

    @property
    def redact_requested(self) -> int:
        return len(self.applied) + len(self.failed)

    @property
    def redact_applied(self) -> int:
        return len(self.applied)


# ---------------------------------------------------------------------------
# Text file decisions
# ---------------------------------------------------------------------------

def apply_decisions_text(
    source_path: str,
    output_path: str,
    decisions: List[dict],
    blocks: List[dict],
) -> Tuple[dict, DecisionApplicationResult]:
    """Apply decisions to a text file.

    Returns (map_data, application_result).
    Every 'redact' decision must produce an entity. Overlaps cause failure.
    """
    result = DecisionApplicationResult()
    blocks_by_id = {b["id"]: b for b in blocks}

    source_bytes = Path(source_path).read_bytes()
    full_text = source_bytes.decode("utf-8-sig") if source_bytes[:3] == b'\xef\xbb\xbf' else source_bytes.decode("utf-8")

    redact_decisions = [d for d in decisions if d.get("action") == "redact"]
    spans = []

    for d in redact_decisions:
        block_id = d.get("blockId")
        block = blocks_by_id.get(block_id)
        if not block:
            result.failed.append({"decision_id": d.get("id"), "reason": f"block '{block_id}' not found in source map"})
            continue

        block_offset = block.get("char_offset", 0)
        block_text = block.get("text", "")
        local_start = d.get("start", 0)
        local_end = d.get("end", 0)

        if local_start < 0 or local_start >= local_end:
            result.failed.append({"decision_id": d.get("id"), "reason": f"invalid range [{local_start}:{local_end}]"})
            continue
        if local_end > len(block_text):
            result.failed.append({"decision_id": d.get("id"), "reason": f"end {local_end} exceeds block text length {len(block_text)}"})
            continue

        doc_start = block_offset + local_start
        doc_end = block_offset + local_end
        original = full_text[doc_start:doc_end]

        if not original.strip():
            result.failed.append({"decision_id": d.get("id"), "reason": "empty text at position"})
            continue

        entity_type = d.get("entityType", "")
        replacement = _mask_value(original, entity_type)
        spans.append((doc_start, doc_end, d, original, replacement))

    spans.sort(key=lambda s: s[0])
    for i in range(1, len(spans)):
        if spans[i][0] < spans[i - 1][1]:
            result.failed.append({
                "decision_id": spans[i][2].get("id"),
                "reason": f"overlaps with decision {spans[i-1][2].get('id')} at [{spans[i-1][0]}:{spans[i-1][1]}]"
            })

    if result.failed:
        return _empty_map(source_path), result

    parts = []
    cursor = 0
    for doc_start, doc_end, d, original, replacement in spans:
        parts.append(full_text[cursor:doc_start])
        red_start = sum(len(p) for p in parts)
        parts.append(replacement)
        red_end = sum(len(p) for p in parts)

        entity_id = f"decision_{d.get('id', len(result.entities))}"
        entity_type = d.get("entityType", "")
        result.entities.append({"id": entity_id, "entity_type": entity_type or "MANUAL", "original": original, "replacement": replacement, "engines": ["decision"]})
        result.occurrences.append({"entity_id": entity_id, "engine": "decision", "original_start": doc_start, "original_end": doc_end, "redacted_start": red_start, "redacted_end": red_end})
        result.applied.append({"decision_id": d.get("id"), "original_start": doc_start, "original_end": doc_end, "redacted_start": red_start, "redacted_end": red_end, "entity_id": entity_id})
        cursor = doc_end

    parts.append(full_text[cursor:])
    redacted_text = "".join(parts)
    Path(output_path).write_text(redacted_text, encoding="utf-8")

    source_sha = hashlib.sha256(source_bytes).hexdigest()
    redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
    return {
        "schema_version": "1.0", "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name, "source_sha256": source_sha,
        "redacted_sha256": redacted_sha, "entities": result.entities, "occurrences": result.occurrences,
    }, result


# ---------------------------------------------------------------------------
# DOCX decisions
# ---------------------------------------------------------------------------

def apply_decisions_docx(
    source_path: str,
    output_path: str,
    decisions: List[dict],
    blocks: List[dict],
) -> Tuple[dict, DecisionApplicationResult]:
    """Apply decisions to a DOCX file. Returns (map_data, application_result)."""
    from .adapters.docx_adapter import (
        _is_text_part, _paragraphs,
        _extract_paragraph_runs_text, rebuild_paragraph_preserve_format,
    )
    from lxml import etree
    import zipfile

    result = DecisionApplicationResult()
    blocks_by_id = {b["id"]: b for b in blocks}

    redact_decisions = [d for d in decisions if d.get("action") == "redact"]

    para_decisions: Dict[str, List[Tuple[dict, dict]]] = {}
    for d in redact_decisions:
        block_id = d.get("blockId")
        block = blocks_by_id.get(block_id)
        if not block:
            result.failed.append({"decision_id": d.get("id"), "reason": f"block '{block_id}' not found"})
            continue

        locator = block.get("sourceLocator", {})
        decision_locator = d.get("sourceLocator") or {}
        if decision_locator:
            locator_identity = (locator.get("part", "word/document.xml"), locator.get("paragraph_index"))
            decision_identity = (decision_locator.get("part", "word/document.xml"), decision_locator.get("paragraph_index"))
            if decision_identity != locator_identity:
                result.failed.append({"decision_id": d.get("id"), "reason": "decision sourceLocator does not match source map"})
                continue
        part = locator.get("part", "word/document.xml")
        para_idx = locator.get("paragraph_index")
        if para_idx is None:
            result.failed.append({"decision_id": d.get("id"), "reason": "missing paragraph_index in sourceLocator"})
            continue

        local_start = d.get("start", 0)
        local_end = d.get("end", 0)
        block_text = block.get("text", "")

        if local_start < 0 or local_start >= local_end:
            result.failed.append({"decision_id": d.get("id"), "reason": f"invalid range [{local_start}:{local_end}]"})
            continue
        if local_end > len(block_text):
            result.failed.append({"decision_id": d.get("id"), "reason": f"end {local_end} exceeds block text length {len(block_text)}"})
            continue

        key = f"{part}:{para_idx}"
        para_decisions.setdefault(key, []).append((d, block))

    if result.failed:
        return _empty_map(source_path), result

    with zipfile.ZipFile(source_path, "r") as zf:
        package_files = {n: zf.read(n) for n in zf.namelist()}

    text_trees = {name: etree.fromstring(data) for name, data in package_files.items() if _is_text_part(name)}

    for part_name, tree in text_trees.items():
        for para_idx, child in enumerate(_paragraphs(tree)):
            key = f"{part_name}:{para_idx}"
            decisions_for_para = para_decisions.get(key, [])
            if not decisions_for_para:
                continue

            para_text, run_metas = _extract_paragraph_runs_text(child)
            if not para_text.strip():
                for d, _ in decisions_for_para:
                    result.failed.append({"decision_id": d.get("id"), "reason": f"paragraph {para_idx} is empty"})
                continue

            sorted_ds = sorted(decisions_for_para, key=lambda x: x[0].get("start", 0))
            for i in range(1, len(sorted_ds)):
                prev_end = sorted_ds[i - 1][0].get("end", 0)
                curr_start = sorted_ds[i][0].get("start", 0)
                if curr_start < prev_end:
                    result.failed.append({"decision_id": sorted_ds[i][0].get("id"), "reason": f"overlaps with decision {sorted_ds[i-1][0].get('id')} in paragraph {para_idx}"})

            if result.failed:
                continue

            spans_for_para = []
            for d, block in decisions_for_para:
                local_start = d.get("start", 0)
                local_end = d.get("end", 0)
                expected_original = block.get("text", "")[local_start:local_end]
                original = para_text[local_start:local_end]
                if original != expected_original:
                    result.failed.append({"decision_id": d.get("id"), "reason": f"source locator mismatch in {part_name} paragraph {para_idx} at [{local_start}:{local_end}]"})
                    continue
                entity_type = d.get("entityType", "")
                replacement = _mask_value(original, entity_type)

                entity_id = f"decision_{d.get('id', len(result.entities))}"
                result.entities.append({"id": entity_id, "entity_type": entity_type or "MANUAL", "original": original, "replacement": replacement, "engines": ["decision"]})
                result.occurrences.append({"entity_id": entity_id, "engine": "decision", "original_start": local_start, "original_end": local_end, "paragraph_index": para_idx, "part": part_name})
                result.applied.append({"decision_id": d.get("id"), "entity_id": entity_id, "part": part_name, "paragraph": para_idx, "original_start": local_start, "original_end": local_end})

                spans_for_para.append({"start": local_start, "end": local_end, "replacement": replacement, "entity_id": entity_id})

            if spans_for_para:
                rebuild_paragraph_preserve_format(child, para_text, run_metas, spans_for_para)

    if result.failed:
        return _empty_map(source_path), result

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in package_files.items():
            if name in text_trees:
                zf.writestr(name, etree.tostring(text_trees[name], xml_declaration=True, encoding="UTF-8", standalone=True))
            else:
                zf.writestr(name, data)

    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    return {
        "schema_version": "1.0", "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name, "source_sha256": source_sha,
        "entities": result.entities, "occurrences": result.occurrences,
    }, result


# ---------------------------------------------------------------------------
# PDF text-layer decisions
# ---------------------------------------------------------------------------

def apply_decisions_pdf(
    source_path: str,
    output_path: str,
    decisions: List[dict],
    blocks: List[dict],
) -> Tuple[dict, DecisionApplicationResult]:
    """Apply decisions to a text-layer PDF using character-level coordinate mapping.

    For each 'redact' decision:
    1. Map block.text[i] → charMap[i] → precise page rectangle
    2. Save rectangles before apply_redactions()
    3. Apply redactions (white-out original text)
    4. Insert replacement text at saved rectangles

    One decision → one occurrence. Cross-line decisions have rectangles[].
    No page.search_for() is used — only charMap coordinates.

    Returns (map_data, application_result).
    """
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF required for PDF decisions export: pip install legal-desens[pdf]")

    result = DecisionApplicationResult()
    blocks_by_id = {b["id"]: b for b in blocks}

    # Validate all redact decisions before opening the document
    redact_decisions = [d for d in decisions if d.get("action") == "redact"]
    validated = []  # (decision, block, local_start, local_end, original, replacement, char_rects)

    for d in redact_decisions:
        block_id = d.get("blockId")
        block = blocks_by_id.get(block_id)
        if not block:
            result.failed.append({"decision_id": d.get("id"), "reason": f"block '{block_id}' not found"})
            continue

        char_map = block.get("charMap")
        if not char_map:
            result.failed.append({"decision_id": d.get("id"), "reason": f"block '{block_id}' has no charMap (not a text-layer PDF block)"})
            continue

        local_start = d.get("start", 0)
        local_end = d.get("end", 0)
        block_text = block.get("text", "")

        if local_start < 0 or local_start >= local_end:
            result.failed.append({"decision_id": d.get("id"), "reason": f"invalid range [{local_start}:{local_end}]"})
            continue
        if local_end > len(block_text):
            result.failed.append({"decision_id": d.get("id"), "reason": f"end {local_end} exceeds block text length {len(block_text)}"})
            continue
        if local_end > len(char_map):
            result.failed.append({"decision_id": d.get("id"), "reason": f"end {local_end} exceeds charMap length {len(char_map)}"})
            continue

        original = block_text[local_start:local_end]
        if not original.strip():
            result.failed.append({"decision_id": d.get("id"), "reason": "empty text at position"})
            continue

        # Extract character rectangles for this range
        char_rects = char_map[local_start:local_end]
        if len(char_rects) != (local_end - local_start):
            result.failed.append({"decision_id": d.get("id"), "reason": f"charMap length mismatch: expected {local_end - local_start}, got {len(char_rects)}"})
            continue

        # Validate every character has a valid rect
        for i, cr in enumerate(char_rects):
            if not cr or not cr.get("rect") or len(cr["rect"]) != 4:
                result.failed.append({"decision_id": d.get("id"), "reason": f"missing or invalid rect for char at offset {local_start + i}"})
                break
            if not cr.get("page"):
                result.failed.append({"decision_id": d.get("id"), "reason": f"missing page for char at offset {local_start + i}"})
                break

        if result.failed:
            continue

        entity_type = d.get("entityType", "")
        replacement = _mask_value(original, entity_type)
        validated.append((d, block, local_start, local_end, original, replacement, char_rects))

    if result.failed:
        return _empty_map(source_path), result

    # Check for overlapping decisions within the same block
    validated_by_block: Dict[str, List] = {}
    for item in validated:
        block_id = item[1]["id"]
        validated_by_block.setdefault(block_id, []).append(item)

    for block_id, items in validated_by_block.items():
        sorted_items = sorted(items, key=lambda x: x[2])  # sort by local_start
        for i in range(1, len(sorted_items)):
            prev_end = sorted_items[i - 1][3]
            curr_start = sorted_items[i][2]
            if curr_start < prev_end:
                result.failed.append({
                    "decision_id": sorted_items[i][0].get("id"),
                    "reason": f"overlaps with decision {sorted_items[i-1][0].get('id')} in block '{block_id}' at [{curr_start}:{prev_end}]"
                })

    if result.failed:
        return _empty_map(source_path), result

    # Open the source PDF
    doc = fitz.open(source_path)
    try:
        # Group decisions by page for efficient processing
        # Each decision may span multiple pages (cross-line)
        for d, block, local_start, local_end, original, replacement, char_rects in validated:
            entity_id = f"decision_{d.get('id', len(result.entities))}"
            entity_type = d.get("entityType", "")

            # Group char_rects by page to handle cross-line spans
            page_groups: Dict[int, List[dict]] = {}  # page_num → list of char_rects
            for cr in char_rects:
                pn = cr["page"]
                page_groups.setdefault(pn, []).append(cr)

            all_rects_for_occurrence = []

            for page_num, page_chars in page_groups.items():
                if page_num < 1 or page_num > len(doc):
                    result.failed.append({"decision_id": d.get("id"), "reason": f"page {page_num} out of range (1-{len(doc)})"})
                    break

                page = doc[page_num - 1]

                # Compute bounding rect for this page's portion
                min_x = min(c["rect"][0] for c in page_chars)
                min_y = min(c["rect"][1] for c in page_chars)
                max_x = max(c["rect"][2] for c in page_chars)
                max_y = max(c["rect"][3] for c in page_chars)
                cover_rect = fitz.Rect(min_x, min_y, max_x, max_y)

                # Get the portion of replacement text for this page
                # char_rects is already sliced from char_map[local_start:local_end],
                # so indices into char_rects are directly offsets into replacement.
                page_char_indices = []
                for i, cr in enumerate(char_rects):
                    if cr["page"] == page_num:
                        page_char_indices.append(i)

                if not page_char_indices:
                    continue

                page_start_idx = page_char_indices[0]
                page_end_idx = page_char_indices[-1] + 1
                page_replacement = replacement[page_start_idx:page_end_idx]

                # Save the rectangle BEFORE applying redactions
                all_rects_for_occurrence.append({
                    "page": page_num,
                    "rect": [min_x, min_y, max_x, max_y],
                })

                # Add redaction annotation (white fill)
                page.add_redact_annot(cover_rect, fill=(1, 1, 1))

            if result.failed:
                break

            # Apply redactions on all affected pages
            affected_pages = set(cr["page"] for cr in char_rects)
            for pn in affected_pages:
                if 1 <= pn <= len(doc):
                    doc[pn - 1].apply_redactions()

            # Insert replacement text at saved rectangles
            if len(all_rects_for_occurrence) == 1:
                # Single rectangle: full replacement goes here
                rect_info = all_rects_for_occurrence[0]
                pn = rect_info["page"]
                r = rect_info["rect"]
                page = doc[pn - 1]
                cover = fitz.Rect(r[0], r[1], r[2], r[3])

                rect_width = cover.width
                rect_height = cover.height
                cjk_count = sum(1 for c in replacement if ord(c) > 0x2E80)
                latin_count = len(replacement) - cjk_count
                est_char_width_ratio = (cjk_count + latin_count * 0.5) / max(1, len(replacement))
                fontsize = rect_height * 0.75
                if len(replacement) > 0:
                    est_text_width = fontsize * est_char_width_ratio * len(replacement)
                    if est_text_width > rect_width * 0.95:
                        fontsize = (rect_width * 0.95) / (est_char_width_ratio * len(replacement))
                fontsize = max(4, min(fontsize, rect_height * 0.85))
                page.insert_text(
                    (cover.x0, cover.y1 - fontsize * 0.2),
                    replacement,
                    fontname="china-s",
                    fontsize=fontsize,
                    color=(0, 0, 0),
                )
            else:
                # Multiple rectangles (cross-line): split replacement proportionally
                for rect_info in all_rects_for_occurrence:
                    pn = rect_info["page"]
                    r = rect_info["rect"]
                    page = doc[pn - 1]
                    cover = fitz.Rect(r[0], r[1], r[2], r[3])

                    # Find chars on this page to determine replacement portion
                    page_chars_in_rect = [i for i, cr in enumerate(char_rects) if cr["page"] == pn]
                    if not page_chars_in_rect:
                        continue
                    r_start = page_chars_in_rect[0]
                    r_end = page_chars_in_rect[-1] + 1
                    rect_replacement = replacement[r_start:r_end]

                    rect_width = cover.width
                    rect_height = cover.height
                    cjk_count = sum(1 for c in rect_replacement if ord(c) > 0x2E80)
                    latin_count = len(rect_replacement) - cjk_count
                    est_char_width_ratio = (cjk_count + latin_count * 0.5) / max(1, len(rect_replacement))
                    fontsize = rect_height * 0.75
                    if len(rect_replacement) > 0:
                        est_text_width = fontsize * est_char_width_ratio * len(rect_replacement)
                        if est_text_width > rect_width * 0.95:
                            fontsize = (rect_width * 0.95) / (est_char_width_ratio * len(rect_replacement))
                    fontsize = max(4, min(fontsize, rect_height * 0.85))
                    page.insert_text(
                        (cover.x0, cover.y1 - fontsize * 0.2),
                        rect_replacement,
                        fontname="china-s",
                        fontsize=fontsize,
                        color=(0, 0, 0),
                    )

            # Record entity, occurrence, applied
            result.entities.append({
                "id": entity_id, "entity_type": entity_type or "MANUAL",
                "original": original, "replacement": replacement, "engines": ["decision"],
            })
            result.occurrences.append({
                "entity_id": entity_id, "engine": "decision",
                "original_start": local_start, "original_end": local_end,
                "block_id": block["id"],
                "rectangles": all_rects_for_occurrence,
            })
            result.applied.append({
                "decision_id": d.get("id"), "entity_id": entity_id,
                "original_start": local_start, "original_end": local_end,
                "block_id": block["id"],
                "rectangles": all_rects_for_occurrence,
            })

        if result.failed:
            return _empty_map(source_path), result

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

        doc.save(output_path, garbage=4, clean=True, deflate=True)
    finally:
        doc.close()

    # Residual verification: check target rectangles, NOT global search
    audit_flags = _verify_pdf_residual(output_path, result, blocks_by_id)

    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    return {
        "schema_version": "1.0", "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name, "source_sha256": source_sha,
        "entities": result.entities, "occurrences": result.occurrences,
        "audit_flags": audit_flags,
    }, result


def _verify_pdf_residual(
    output_path: str,
    result: DecisionApplicationResult,
    blocks_by_id: dict,
) -> dict:
    """Verify redacted text removed, replacement written, and positions correct.

    Returns audit flags dict:
      { original_removed: bool, replacement_written: bool, position_verification: bool }

    Uses charMap-based rect verification, NOT global text search.
    """
    try:
        import fitz
    except ImportError:
        return {"original_removed": False, "replacement_written": False, "position_verification": False, "error": "PyMuPDF not available"}

    flags = {"original_removed": True, "replacement_written": True, "position_verification": True}

    doc = fitz.open(output_path)
    try:
        for applied in result.applied:
            entity_id = applied.get("entity_id")
            entity = next((e for e in result.entities if e["id"] == entity_id), None)
            if not entity:
                flags["position_verification"] = False
                continue

            original = entity.get("original", "")
            replacement = entity.get("replacement", "")
            if not original or len(original) < 2:
                continue

            rectangles = applied.get("rectangles", [])
            if not rectangles:
                flags["position_verification"] = False
                continue

            # Collect all pages involved
            involved_pages = set()
            for rect_info in rectangles:
                pn = rect_info.get("page", 0)
                if 1 <= pn <= len(doc):
                    involved_pages.add(pn)

            # 1. Original must NOT be extractable from target rectangles
            for rect_info in rectangles:
                pn = rect_info.get("page", 0)
                r = rect_info.get("rect", [])
                if pn < 1 or pn > len(doc) or len(r) != 4:
                    flags["position_verification"] = False
                    continue

                page = doc[pn - 1]
                rect = fitz.Rect(r[0], r[1], r[2], r[3])
                area_text = page.get_text("text", clip=rect).strip()

                if original in area_text:
                    flags["original_removed"] = False

            # 2. Replacement text verification: check page-level text
            # (rect-level extraction may not capture inserted text due to font rendering)
            if replacement and len(replacement) >= 2:
                rep_found = False
                for pn in involved_pages:
                    page_text = doc[pn - 1].get_text()
                    if replacement in page_text:
                        rep_found = True
                        break
                    # Also check partial match for masked text (e.g., "138****8000")
                    # Check if at least the mask chars are present
                    mask_chars = replacement.replace("*", "").replace("●", "")
                    if len(mask_chars) >= 2 and mask_chars in page_text:
                        rep_found = True
                        break
                if not rep_found:
                    # If replacement is all mask chars, check that area is non-empty
                    # (the text was written but may not be extractable as exact string)
                    all_mask = all(c in "*●" for c in replacement)
                    if all_mask:
                        # Check that the target area has some content
                        any_content = False
                        for rect_info in rectangles:
                            pn = rect_info.get("page", 0)
                            r = rect_info.get("rect", [])
                            if pn < 1 or pn > len(doc) or len(r) != 4:
                                continue
                            area_text = doc[pn - 1].get_text("text", clip=fitz.Rect(r[0], r[1], r[2], r[3])).strip()
                            if area_text:
                                any_content = True
                                break
                        if not any_content:
                            flags["replacement_written"] = False
                    else:
                        flags["replacement_written"] = False

    finally:
        doc.close()

    return flags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_map(source_path: str) -> dict:
    return {
        "schema_version": "1.0",
        "source_file": Path(source_path).name,
        "redacted_file": "",
        "source_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
        "entities": [],
        "occurrences": [],
    }


def _load_decisions(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_source_map(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
