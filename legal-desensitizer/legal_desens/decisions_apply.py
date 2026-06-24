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


def _load_decisions(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_source_map(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
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


class DecisionApplicationResult:
    """Result of applying decisions to a document."""

    def __init__(self):
        self.entities: List[dict] = []
        self.occurrences: List[dict] = []
        self.applied: List[dict] = []  # {decision_id, original_start, original_end, redacted_start, redacted_end, entity_id}
        self.failed: List[dict] = []   # {decision_id, reason}

    @property
    def all_applied(self) -> bool:
        return len(self.failed) == 0

    @property
    def redact_requested(self) -> int:
        return len(self.applied) + len(self.failed)

    @property
    def redact_applied(self) -> int:
        return len(self.applied)


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

    # Validate all redact decisions before modifying anything
    redact_decisions = [d for d in decisions if d.get("action") == "redact"]
    spans = []  # (doc_start, doc_end, decision, original, replacement)

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

        # Validate bounds
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

    # Check for overlaps
    spans.sort(key=lambda s: s[0])
    for i in range(1, len(spans)):
        if spans[i][0] < spans[i - 1][1]:
            result.failed.append({
                "decision_id": spans[i][2].get("id"),
                "reason": f"overlaps with decision {spans[i-1][2].get('id')} at [{spans[i-1][0]}:{spans[i-1][1]}]"
            })

    # If any failures, abort
    if result.failed:
        map_data = {
            "schema_version": "1.0",
            "source_file": Path(source_path).name,
            "redacted_file": "",
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "entities": [],
            "occurrences": [],
        }
        return map_data, result

    # Build redacted text
    parts = []
    cursor = 0

    for doc_start, doc_end, d, original, replacement in spans:
        parts.append(full_text[cursor:doc_start])
        red_start = sum(len(p) for p in parts)
        parts.append(replacement)
        red_end = sum(len(p) for p in parts)

        entity_id = f"decision_{d.get('id', len(result.entities))}"
        entity_type = d.get("entityType", "")

        result.entities.append({
            "id": entity_id,
            "entity_type": entity_type or "MANUAL",
            "original": original,
            "replacement": replacement,
            "engines": ["decision"],
        })
        result.occurrences.append({
            "entity_id": entity_id,
            "engine": "decision",
            "original_start": doc_start,
            "original_end": doc_end,
            "redacted_start": red_start,
            "redacted_end": red_end,
        })
        result.applied.append({
            "decision_id": d.get("id"),
            "original_start": doc_start,
            "original_end": doc_end,
            "redacted_start": red_start,
            "redacted_end": red_end,
            "entity_id": entity_id,
        })
        cursor = doc_end

    parts.append(full_text[cursor:])
    redacted_text = "".join(parts)

    Path(output_path).write_text(redacted_text, encoding="utf-8")

    source_sha = hashlib.sha256(source_bytes).hexdigest()
    redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()

    map_data = {
        "schema_version": "1.0",
        "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name,
        "source_sha256": source_sha,
        "redacted_sha256": redacted_sha,
        "entities": result.entities,
        "occurrences": result.occurrences,
    }
    return map_data, result


def apply_decisions_docx(
    source_path: str,
    output_path: str,
    decisions: List[dict],
    blocks: List[dict],
) -> Tuple[dict, DecisionApplicationResult]:
    """Apply decisions to a DOCX file.

    Returns (map_data, application_result).
    Every 'redact' decision must produce an entity.
    """
    from .adapters.docx_adapter import (
        _is_text_part, _paragraphs,
        _extract_paragraph_runs_text, rebuild_paragraph_preserve_format,
    )
    from lxml import etree
    import zipfile

    result = DecisionApplicationResult()
    blocks_by_id = {b["id"]: b for b in blocks}

    # Validate all redact decisions
    redact_decisions = [d for d in decisions if d.get("action") == "redact"]

    # Group by paragraph using sourceLocator
    para_decisions: Dict[str, List[Tuple[dict, dict]]] = {}  # "part:para_idx" → [(decision, block)]
    for d in redact_decisions:
        block_id = d.get("blockId")
        block = blocks_by_id.get(block_id)
        if not block:
            result.failed.append({"decision_id": d.get("id"), "reason": f"block '{block_id}' not found"})
            continue

        # The source map is authoritative. A client-supplied locator may be
        # echoed for traceability, but must never redirect a decision to a
        # different OOXML part or paragraph.
        locator = block.get("sourceLocator", {})
        decision_locator = d.get("sourceLocator") or {}
        if decision_locator:
            locator_identity = (
                locator.get("part", "word/document.xml"),
                locator.get("paragraph_index"),
            )
            decision_identity = (
                decision_locator.get("part", "word/document.xml"),
                decision_locator.get("paragraph_index"),
            )
            if decision_identity != locator_identity:
                result.failed.append({
                    "decision_id": d.get("id"),
                    "reason": "decision sourceLocator does not match source map",
                })
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
        map_data = {
            "schema_version": "1.0",
            "source_file": Path(source_path).name,
            "redacted_file": "",
            "source_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
            "entities": [],
            "occurrences": [],
        }
        return map_data, result

    # Read source DOCX
    with zipfile.ZipFile(source_path, "r") as zf:
        package_files = {n: zf.read(n) for n in zf.namelist()}

    text_trees = {
        name: etree.fromstring(data)
        for name, data in package_files.items()
        if _is_text_part(name)
    }

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

            # Check for overlaps within this paragraph
            sorted_ds = sorted(decisions_for_para, key=lambda x: x[0].get("start", 0))
            for i in range(1, len(sorted_ds)):
                prev_end = sorted_ds[i - 1][0].get("end", 0)
                curr_start = sorted_ds[i][0].get("start", 0)
                if curr_start < prev_end:
                    result.failed.append({
                        "decision_id": sorted_ds[i][0].get("id"),
                        "reason": f"overlaps with decision {sorted_ds[i-1][0].get('id')} in paragraph {para_idx}"
                    })

            if result.failed:
                continue

            spans_for_para = []
            for d, block in decisions_for_para:
                local_start = d.get("start", 0)
                local_end = d.get("end", 0)
                expected_original = block.get("text", "")[local_start:local_end]
                original = para_text[local_start:local_end]
                if original != expected_original:
                    result.failed.append({
                        "decision_id": d.get("id"),
                        "reason": (
                            f"source locator mismatch in {part_name} paragraph "
                            f"{para_idx} at [{local_start}:{local_end}]"
                        ),
                    })
                    continue
                entity_type = d.get("entityType", "")
                replacement = _mask_value(original, entity_type)

                entity_id = f"decision_{d.get('id', len(result.entities))}"
                result.entities.append({
                    "id": entity_id,
                    "entity_type": entity_type or "MANUAL",
                    "original": original,
                    "replacement": replacement,
                    "engines": ["decision"],
                })
                result.occurrences.append({
                    "entity_id": entity_id,
                    "engine": "decision",
                    "original_start": local_start,
                    "original_end": local_end,
                    "paragraph_index": para_idx,
                    "part": part_name,
                })
                result.applied.append({
                    "decision_id": d.get("id"),
                    "entity_id": entity_id,
                    "part": part_name,
                    "paragraph": para_idx,
                    "original_start": local_start,
                    "original_end": local_end,
                })

                spans_for_para.append({
                    "start": local_start,
                    "end": local_end,
                    "replacement": replacement,
                    "entity_id": entity_id,
                })

            if spans_for_para:
                rebuild_paragraph_preserve_format(
                    child, para_text, run_metas, spans_for_para,
                )

    if result.failed:
        map_data = {
            "schema_version": "1.0",
            "source_file": Path(source_path).name,
            "redacted_file": "",
            "source_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
            "entities": [],
            "occurrences": [],
        }
        return map_data, result

    # Write modified DOCX
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in package_files.items():
            if name in text_trees:
                zf.writestr(name, etree.tostring(text_trees[name], xml_declaration=True, encoding="UTF-8", standalone=True))
            else:
                zf.writestr(name, data)

    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    map_data = {
        "schema_version": "1.0",
        "source_file": Path(source_path).name,
        "redacted_file": Path(output_path).name,
        "source_sha256": source_sha,
        "entities": result.entities,
        "occurrences": result.occurrences,
    }
    return map_data, result
