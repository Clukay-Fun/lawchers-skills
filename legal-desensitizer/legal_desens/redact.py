"""Redaction engine: replace spans with labels, produce map + audit."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
import re

from .engine.address_merge import merge_addresses
from .engine.bank_account import detect_bank_accounts
from .engine.merge import merge_spans
from .engine.org_gate import apply_org_gate
from .engine.regex import scan_regex
from .engine.span import Span
from .profile import Profile
from .rules import Rule


def scan_ner_with_warnings(text: str, model_dir: Optional[str] = None) -> Tuple[List[Span], List[dict]]:
    """Run NER and return (spans, decode_warnings)."""
    from .engine.ner import NEREngine
    engine = NEREngine(model_dir)
    return engine.scan(text)


# NER entity type → canonical type (before profile processing)
_NER_TYPE_MAP = {
    "PER": "PERSON",
    "LOC": "LOC",  # Keep LOC for address merge; converted to ADDRESS after
    "LOCATION": "LOC",
}

_TIME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"(?:[0-3][0-9]{3})[年./\-－—](?:0?[1-9]|1[0-2])"
    r"(?:[月./\-－—](?:0?[1-9]|[12][0-9]|3[01])日?)?"
    r"|(?:19|20)[0-9]{2}年?"
    r"|(?:19|20)[0-9]{6}"
    r")"
    r"(?![A-Za-z0-9])"
)


def _remap_ner_types(spans: List[Span]) -> List[Span]:
    """Remap NER entity types to canonical forms."""
    for span in spans:
        if span.engine == "ner" and span.entity_type in _NER_TYPE_MAP:
            span.entity_type = _NER_TYPE_MAP[span.entity_type]
    return spans


def _label_prefix_for(entity_type: str, rules: List[Rule]) -> str:
    for r in rules:
        if r.entity_type == entity_type:
            return r.label_prefix
    return {
        "PER": "人物",
        "PERSON": "人物",
        "LOC": "地点",
        "LOCATION": "地点",
        "ORG": "机构",
        "LANDLINE": "电话",
        "BANK_ACCOUNT": "银行账号",
        "BANK_BRANCH": "银行信息",
        "MONEY": "金额",
        "ADDRESS": "地址",
    }.get(entity_type, entity_type)


class LabelAllocator:
    """Assigns labels per entity_type. Supports numbered and bracket_unnumbered styles."""

    def __init__(self, rules: List[Rule], profile: Optional[Profile] = None):
        self._rules = rules
        self._profile = profile
        self._counter: Dict[str, int] = {}
        self._cache: Dict[Tuple[str, str], str] = {}
        self._entities: List[dict] = []
        self._entity_index: Dict[Tuple[str, str], str] = {}  # (type, original) -> entity_id

    def get_label(self, entity_type: str, original: str) -> Tuple[str, str]:
        """Return (entity_id, replacement_label). Reuses if already allocated."""
        key = (entity_type, original)
        if key in self._cache:
            return self._cache[key]

        count = self._counter.get(entity_type, 0) + 1
        self._counter[entity_type] = count

        entity_id = f"{entity_type}_{count}"

        # Determine label based on profile style
        if self._profile and self._profile.label_style == "bracket_unnumbered":
            profile_label = self._profile.get_label_text(entity_type)
            if profile_label:
                label = profile_label  # e.g. "【姓名】"
            else:
                # Fallback for unknown types
                prefix = _label_prefix_for(entity_type, self._rules)
                label = f"【{prefix}】"
        else:
            # Legacy numbered style
            prefix = _label_prefix_for(entity_type, self._rules)
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
        eid = self._entity_index.get(key)
        if eid is None:
            return
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


def _profile_aware_residual_scan(
    text: str,
    rules: List[Rule],
    profile: Profile,
) -> List[Span]:
    """Residual scan that only checks entity_types the profile marks for redaction."""
    all_findings = scan_regex(text, rules)
    redact_types = profile.redact_entity_types()
    return [f for f in all_findings if f.entity_type in redact_types]


def _scan_time_expressions(text: str, discovery_start: int = 0) -> List[Span]:
    """Detect common date/time expressions for profiles that redact TIME."""
    spans: List[Span] = []
    order = discovery_start
    for match in _TIME_PATTERN.finditer(text):
        spans.append(Span(
            entity_type="TIME",
            start=match.start(),
            end=match.end(),
            text=match.group(),
            engine="regex",
            rule_id="time_profile",
            priority=80,
            discovery_order=order,
        ))
        order += 1
    return spans


def _remaining_loc_to_address(spans: List[Span]) -> List[Span]:
    """Treat unmerged LOC spans as ADDRESS so single-fragment addresses are not leaked."""
    for span in spans:
        if span.entity_type == "LOC":
            span.entity_type = "ADDRESS"
    return spans


def redact(
    text: str,
    rules: List[Rule],
    source_sha256: str,
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
    profile: Optional[Profile] = None,
    allowlist: Optional[Set[str]] = None,
    denylist: Optional[Set[str]] = None,
) -> Tuple[str, dict, dict]:
    """Redact text using regex rules and optionally NER.

    Args:
        text: Input text to redact.
        rules: Desensitization rules.
        source_sha256: SHA-256 of source text.
        mode: "regex-only" or "regex+ner".
        level: Legacy level param (used in map output).
        model_dir: Path to NER model directory.
        profile: Profile defining redact/preserve policy. If None, defaults to labor behavior.
        allowlist: Set of terms that should NOT be redacted (case-insensitive).
                   Only applies to NER-derived types (ORG/ADDRESS), not structural PII.
        denylist: Set of terms that MUST be redacted (case-insensitive).
                  Overrides allowlist and ORG gate.

    Returns (redacted_text, map_dict, audit_dict).
    """
    from .engine.allowlist import is_structural_pii
    from .profile import load_profile

    if profile is None:
        profile = load_profile("labor")

    # Scan
    spans = scan_regex(text, rules)
    ner_warnings: List[dict] = []
    if mode != "regex-only":
        ner_spans, ner_warnings = scan_ner_with_warnings(text, model_dir)
        spans.extend(ner_spans)
        _remap_ner_types(spans)
    if profile.should_redact("TIME"):
        spans.extend(_scan_time_expressions(
            text,
            discovery_start=max((s.discovery_order for s in spans), default=-1) + 1,
        ))

    # Address merge: combine adjacent LOC fragments before merge_spans
    if profile.address_merge:
        spans = merge_addresses(spans, text)
    spans = _remaining_loc_to_address(spans)

    # Context-aware BANK_ACCOUNT detection
    # First, let regex find what it can (money, phone, id_card etc.)
    # Then use context-aware heuristics for bare long digits
    bank_spans, bank_warnings = detect_bank_accounts(text, spans)
    spans.extend(bank_spans)

    # Merge
    kept, discarded = merge_spans(spans)

    # Filter by profile: only redact types that profile marks as "redact"
    redact_types = profile.redact_entity_types()
    kept_for_redact = [s for s in kept if s.entity_type in redact_types]

    # Org abbreviation dictionary: find abbreviated org names after full names are found
    if profile.org_abbrev_dict:
        from .engine.abbrev import find_abbreviations
        org_full_names = [
            s.text for s in kept_for_redact
            if s.entity_type in ("ORG",)
        ]
        abbrev_spans = find_abbreviations(text, org_full_names, kept_for_redact)
        if abbrev_spans:
            kept_for_redact.extend(abbrev_spans)
            # Re-merge to resolve any new overlaps
            kept_for_redact, extra_discarded = merge_spans(kept_for_redact)
            discarded.extend(extra_discarded)

    # Apply ORG gate: secondary validation for ORG entities
    # Precedence: denylist > allowlist > ORG gate > default (no redact + warning)
    org_gate_warnings = []
    if mode != "regex-only":
        # Separate ORG spans from other spans
        org_spans = [s for s in kept_for_redact if s.entity_type == "ORG"]
        non_org_spans = [s for s in kept_for_redact if s.entity_type != "ORG"]

        # Apply ORG gate
        passed_orgs, filtered_orgs, gate_warnings = apply_org_gate(
            org_spans, text, allowlist=allowlist, denylist=denylist,
        )

        # Only keep ORG spans that passed the gate
        kept_for_redact = non_org_spans + passed_orgs
        org_gate_warnings = gate_warnings

        # Add filtered ORGs to discarded for audit
        for span in filtered_orgs:
            discarded.append(span)

    # Apply allowlist to ADDRESS spans (if applicable)
    if allowlist and mode != "regex-only":
        from .engine.allowlist import is_allowlist_applicable
        address_spans = [s for s in kept_for_redact if s.entity_type == "ADDRESS"]
        non_address_spans = [s for s in kept_for_redact if s.entity_type != "ADDRESS"]

        filtered_addresses = []
        for span in address_spans:
            if span.text.lower() in {a.lower() for a in allowlist}:
                # Allowlisted ADDRESS should not be redacted
                org_gate_warnings.append({
                    "type": "address_allowlisted",
                    "entity_type": "ADDRESS",
                    "start": span.start,
                    "end": span.end,
                    "text": span.text,
                    "message": f"命中 allowlist，不脱敏: '{span.text}'",
                    "suggested_action": "建议 allowlist",
                })
                discarded.append(span)
            else:
                filtered_addresses.append(span)

        kept_for_redact = non_address_spans + filtered_addresses

    # Allocate labels
    allocator = LabelAllocator(rules, profile=profile)

    # Build redacted text and occurrences
    occurrences, redacted_text = _build_occurrences(kept_for_redact, allocator, text)

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
        "profile": profile.name,
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
    if mode != "regex-only":
        warnings.append({
            "type": "best_effort_notice",
            "message": (
                "NER is an optional best-effort enhancement, not a safety guarantee. "
                "Company names, address fragments, and model-specific entity types may be missed."
            ),
        })
    # Include NER decode warnings (e.g. illegal_transition)
    warnings.extend(ner_warnings)
    # Include bank account context warnings
    warnings.extend(bank_warnings)
    # Include ORG gate warnings
    warnings.extend(org_gate_warnings)

    # Residual scan: profile-aware — only check types the profile marks for redact
    residual_findings = _profile_aware_residual_scan(redacted_text, rules, profile)

    audit_data = {
        "schema_version": "1.0",
        "profile": profile.name,
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
    if mode != "regex-only":
        audit_data["best_effort"] = True

    return redacted_text, map_data, audit_data
