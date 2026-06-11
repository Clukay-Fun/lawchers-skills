"""Redaction engine: replace spans with labels, produce map + audit."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .engine.merge import merge_spans
from .engine.regex import scan_regex
from .engine.span import Span
from .rules import Rule


def scan_ner_with_warnings(text: str, model_dir: Optional[str] = None) -> Tuple[List[Span], List[dict]]:
    """Run NER and return (spans, decode_warnings)."""
    from .engine.ner import NEREngine
    engine = NEREngine(model_dir)
    return engine.scan(text)


def _label_prefix_for(entity_type: str, rules: List[Rule]) -> str:
    for r in rules:
        if r.entity_type == entity_type:
            return r.label_prefix
    return entity_type


class LabelAllocator:
    """Assigns sequential labels per entity_type. Same (type, original) reuses label."""

    def __init__(self, rules: List[Rule]):
        self._rules = rules
        self._counter: Dict[str, int] = {}
        self._cache: Dict[Tuple[str, str], str] = {}
        self._entities: List[dict] = []
        self._entity_index: Dict[Tuple[str, str], str] = {}  # (type, original) -> entity_id

    def get_label(self, entity_type: str, original: str) -> Tuple[str, str]:
        """Return (entity_id, replacement_label). Reuses if already allocated."""
        key = (entity_type, original)
        if key in self._cache:
            return self._cache[key]

        prefix = _label_prefix_for(entity_type, self._rules)
        count = self._counter.get(entity_type, 0) + 1
        self._counter[entity_type] = count

        entity_id = f"{entity_type}_{count}"
        label = f"{prefix}{count}"

        self._cache[key] = (entity_id, label)
        self._entities.append({
            "id": entity_id,
            "entity_type": entity_type,
            "original": original,
            "replacement": label,
            "engines": [],
        })
        self._entity_index[key] = entity_id
        return entity_id, label

    def add_engine(self, entity_type: str, original: str, engine: str) -> None:
        key = (entity_type, original)
        eid = self._entity_index[key]
        for e in self._entities:
            if e["id"] == eid:
                if engine not in e["engines"]:
                    e["engines"].append(engine)
                break

    @property
    def entities(self) -> List[dict]:
        return list(self._entities)


def _build_occurrences(kept_spans: List[Span], allocator: LabelAllocator, text: str) -> Tuple[List[dict], str]:
    """Build redacted text and occurrence records.

    Returns (occurrences, redacted_text).
    Occurrences record both original and redacted positions.
    """
    # Build replacement plan: for each span, get its label and engine
    replacements: List[Tuple[int, int, str, str, str]] = []  # (start, end, entity_id, label, engine)
    for span in kept_spans:
        entity_id, label = allocator.get_label(span.entity_type, span.text)
        allocator.add_engine(span.entity_type, span.text, span.engine)
        replacements.append((span.start, span.end, entity_id, label, span.engine))

    # Sort by start ascending for position-based replacement
    replacements_asc = sorted(replacements, key=lambda r: r[0])

    redacted_parts: List[str] = []
    occurrences: List[dict] = []
    pos = 0

    for start, end, entity_id, label, engine in replacements_asc:
        if start < pos:
            continue
        redacted_parts.append(text[pos:start])
        red_start = sum(len(p) for p in redacted_parts)
        redacted_parts.append(label)
        red_end = sum(len(p) for p in redacted_parts)

        occurrences.append({
            "entity_id": entity_id,
            "engine": engine,
            "original_start": start,
            "original_end": end,
            "redacted_start": red_start,
            "redacted_end": red_end,
        })
        pos = end

    redacted_parts.append(text[pos:])
    redacted_text = "".join(redacted_parts)

    return occurrences, redacted_text


def redact(
    text: str,
    rules: List[Rule],
    source_sha256: str,
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
) -> Tuple[str, dict, dict]:
    """Redact text using regex rules and optionally NER.

    Returns (redacted_text, map_dict, audit_dict).
    """
    # Scan
    spans = scan_regex(text, rules)
    ner_warnings: List[dict] = []
    if mode != "regex-only":
        ner_spans, ner_warnings = scan_ner_with_warnings(text, model_dir)
        spans.extend(ner_spans)

    # Merge
    kept, discarded = merge_spans(spans)

    # Allocate labels
    allocator = LabelAllocator(rules)

    # Build redacted text and occurrences
    occurrences, redacted_text = _build_occurrences(kept, allocator, text)

    redacted_sha256 = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()

    # Build map
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_file = ""
    redacted_file = ""

    map_data = {
        "schema_version": "1.0",
        "source_file": source_file,
        "redacted_file": redacted_file,
        "source_sha256": source_sha256,
        "redacted_sha256": redacted_sha256,
        "level": level,
        "mode": mode,
        "created_at": now,
        "entities": allocator.entities,
        "occurrences": occurrences,
    }

    # Build audit
    by_type: Dict[str, int] = {}
    by_engine: Dict[str, int] = {}
    for o in occurrences:
        eid = o["entity_id"]
        for e in allocator.entities:
            if e["id"] == eid:
                t = e["entity_type"]
                by_type[t] = by_type.get(t, 0) + 1
                break
        eng = o["engine"]
        by_engine[eng] = by_engine.get(eng, 0) + 1

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
    # Include NER decode warnings (e.g. illegal_transition)
    warnings.extend(ner_warnings)

    # Residual scan: re-run regex on redacted text
    residual_findings = scan_regex(redacted_text, rules)

    audit_data = {
        "schema_version": "1.0",
        "summary": {
            "total_entities": len(allocator.entities),
            "total_occurrences": len(occurrences),
            "by_entity_type": by_type,
            "by_engine": by_engine,
        },
        "residual_scan": {
            "passed": len(residual_findings) == 0,
            "findings": [
                {
                    "entity_type": f.entity_type,
                    "start": f.start,
                    "end": f.end,
                    "text_preview": f.text[:20],
                }
                for f in residual_findings
            ],
        },
        "warnings": warnings,
    }

    return redacted_text, map_data, audit_data
