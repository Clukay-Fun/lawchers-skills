"""Apply redaction decisions directly to documents.

Bypasses auto-detection (regex/NER). Uses decisions from the review
workflow to redact only user-approved positions.

Guarantees:
- 'keep' decisions: text is never modified
- 'redact' decisions: text is always modified at the specified position
- Only decision-specified positions are modified (no global re-detection)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _load_decisions(decisions_path: str) -> List[dict]:
    """Load decisions JSON file."""
    with open(decisions_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_source_map(map_path: str) -> dict:
    """Load source map JSON file."""
    with open(map_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mask_value(original: str, entity_type: str) -> str:
    """Generate type-aware partial mask (matches frontend maskValue)."""
    if not original:
        return ''
    chars = list(original)
    length = len(chars)

    if entity_type in ('PHONE', 'LANDLINE'):
        if length >= 11:
            return ''.join(chars[:3]) + '****' + ''.join(chars[-4:])
        if length >= 8:
            return ''.join(chars[:min(3, length - 4)]) + '****' + ''.join(chars[-4:])
        return chars[0] + '***'
    elif entity_type == 'ID_CARD':
        if length >= 15:
            return ''.join(chars[:4]) + '*' * (length - 8) + ''.join(chars[-4:])
        return ''.join(chars[:3]) + '*' * max(1, length - 6) + ''.join(chars[-3:])
    elif entity_type == 'PERSON':
        return chars[0] + '*' * max(1, length - 1)
    elif entity_type == 'ORG':
        if length > 4:
            return ''.join(chars[:2]) + '*' * max(2, length - 4) + ''.join(chars[-2:])
        return chars[0] + '*' * max(1, length - 1)
    elif entity_type == 'EMAIL':
        at_idx = original.find('@')
        if at_idx > 0:
            local = list(original[:at_idx])
            domain = original[at_idx:]
            return ''.join(local[:min(2, len(local))]) + '***' + domain
        return ''.join(chars[:2]) + '***'
    elif entity_type == 'BANK_CARD':
        if length >= 8:
            return '*' * (length - 4) + ''.join(chars[-4:])
        return '*' * max(1, length - 2) + ''.join(chars[-2:])
    elif entity_type == 'MONEY':
        return '****' + (chars[-1] if chars else '')
    elif entity_type in ('DATE', 'TIME'):
        result = ''
        for c in chars:
            result += c if c in '年月日号时分秒' else '*'
        return result
    else:
        return chars[0] + '***'


def _build_redact_spans(
    decisions: List[dict],
    blocks: List[dict],
    block_offsets: Dict[str, int],
    full_text: str,
) -> Tuple[List[dict], Dict[int, dict]]:
    """Convert decisions to document-level redaction spans.

    Returns (spans, decision_map) where spans have start/end/replacement
    at document level, and decision_map maps span index to decision.
    """
    blocks_by_id = {b["id"]: b for b in blocks}
    redact_decisions = [d for d in decisions if d.get("action") == "redact"]

    spans = []
    decision_map = {}

    for d in redact_decisions:
        block_id = d.get("blockId")
        block = blocks_by_id.get(block_id)
        if not block:
            continue

        block_offset = block.get("char_offset", block_offsets.get(block_id, 0))
        local_start = d.get("start", 0)
        local_end = d.get("end", 0)
        block_text = block.get("text", "")

        # Validate bounds
        if local_start < 0 or local_end > len(block_text) or local_start >= local_end:
            continue

        doc_start = block_offset + local_start
        doc_end = block_offset + local_end
        original = full_text[doc_start:doc_end]

        entity_type = d.get("entityType", "")
        replacement = _mask_value(original, entity_type)

        span_idx = len(spans)
        spans.append({
            "start": doc_start,
            "end": doc_end,
            "replacement": replacement,
            "entity_id": f"decision_{d.get('id', span_idx)}",
            "original": original,
        })
        decision_map[span_idx] = d

    # Sort by start for non-overlapping replacement
    spans.sort(key=lambda s: s["start"])
    return spans, decision_map


def apply_decisions_text(
    source_path: str,
    output_path: str,
    decisions: List[dict],
    blocks: List[dict],
) -> dict:
    """Apply decisions to a text file.

    Returns map_data dict with entities and occurrences.
    """
    source_bytes = Path(source_path).read_bytes()
    full_text = source_bytes.decode("utf-8-sig") if source_bytes[:3] == b'\xef\xbb\xbf' else source_bytes.decode("utf-8")

    block_offsets = {b["id"]: b.get("char_offset", 0) for b in blocks}
    spans, _ = _build_redact_spans(decisions, blocks, block_offsets, full_text)

    # Build redacted text by replacing spans
    parts = []
    cursor = 0
    occurrences = []
    entities = []

    for span in spans:
        if span["start"] < cursor:
            continue  # Skip overlapping
        parts.append(full_text[cursor:span["start"]])
        red_start = sum(len(p) for p in parts)
        parts.append(span["replacement"])
        red_end = sum(len(p) for p in parts)

        occurrences.append({
            "entity_id": span["entity_id"],
            "engine": "decision",
            "original_start": span["start"],
            "original_end": span["end"],
            "redacted_start": red_start,
            "redacted_end": red_end,
        })
        entities.append({
            "id": span["entity_id"],
            "entity_type": "MANUAL",
            "original": span["original"],
            "replacement": span["replacement"],
            "engines": ["decision"],
        })
        cursor = span["end"]

    parts.append(full_text[cursor:])
    redacted_text = "".join(parts)

    # Write output
    Path(output_path).write_text(redacted_text, encoding="utf-8")

    source_sha = hashlib.sha256(source_bytes).hexdigest()
    redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()

    return {
        "schema_version": "1.0",
        "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name,
        "source_sha256": source_sha,
        "redacted_sha256": redacted_sha,
        "entities": entities,
        "occurrences": occurrences,
    }


def apply_decisions_docx(
    source_path: str,
    output_path: str,
    decisions: List[dict],
    blocks: List[dict],
) -> dict:
    """Apply decisions to a DOCX file.

    Uses OOXML paragraph-level modification via the DOCX adapter.
    Returns map_data dict.
    """
    from .adapters.docx_adapter import (
        DOCXAdapter, _is_text_part, _paragraphs,
        _extract_paragraph_runs_text, _rebuild_paragraph_with_redactions,
    )
    from lxml import etree
    import zipfile

    # Build block → paragraph index mapping
    block_para_map: Dict[str, List[dict]] = {}
    for d in decisions:
        if d.get("action") != "redact":
            continue
        locator = d.get("sourceLocator", {})
        part = locator.get("part", "word/document.xml")
        para_idx = locator.get("paragraph_index")
        if para_idx is not None:
            key = f"{part}:{para_idx}"
            block_para_map.setdefault(key, []).append(d)

    # Read source DOCX
    with zipfile.ZipFile(source_path, "r") as zf:
        package_files = {n: zf.read(n) for n in zf.namelist()}

    text_trees = {
        name: etree.fromstring(data)
        for name, data in package_files.items()
        if _is_text_part(name)
    }

    all_entities = []
    all_occurrences = []
    entity_counters: Dict[str, int] = {}

    for part_name, tree in text_trees.items():
        for para_idx, child in enumerate(_paragraphs(tree)):
            key = f"{part_name}:{para_idx}"
            para_decisions = block_para_map.get(key, [])
            if not para_decisions:
                continue

            para_text, run_metas = _extract_paragraph_runs_text(child)
            if not para_text.strip():
                continue

            # Build spans from decisions
            spans_for_para = []
            for d in para_decisions:
                local_start = d.get("start", 0)
                local_end = d.get("end", 0)
                if local_start < 0 or local_end > len(para_text) or local_start >= local_end:
                    continue

                original = para_text[local_start:local_end]
                entity_type = d.get("entityType", "")
                replacement = _mask_value(original, entity_type)

                entity_id = f"decision_{d.get('id', len(all_entities))}"
                all_entities.append({
                    "id": entity_id,
                    "entity_type": entity_type or "MANUAL",
                    "original": original,
                    "replacement": replacement,
                    "engines": ["decision"],
                })
                all_occurrences.append({
                    "entity_id": entity_id,
                    "engine": "decision",
                    "original_start": local_start,
                    "original_end": local_end,
                    "paragraph_index": para_idx,
                    "part": part_name,
                })

                spans_for_para.append({
                    "start": local_start,
                    "end": local_end,
                    "replacement": replacement,
                    "entity_id": entity_id,
                })

            if spans_for_para:
                _rebuild_paragraph_with_redactions(
                    child, para_text, run_metas, spans_for_para,
                )

    # Write modified DOCX
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in package_files.items():
            if name in text_trees:
                zf.writestr(name, etree.tostring(text_trees[name], xml_declaration=True, encoding="UTF-8", standalone=True))
            else:
                zf.writestr(name, data)

    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    return {
        "schema_version": "1.0",
        "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name,
        "source_sha256": source_sha,
        "entities": all_entities,
        "occurrences": all_occurrences,
    }
