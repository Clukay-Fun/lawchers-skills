"""Audit command: post-hoc residual scan and map validation."""

from __future__ import annotations

import hashlib
from typing import List, Optional

from .engine.regex import scan_regex
from .profile import Profile
from .rules import Rule


def audit(
    redacted_text: str,
    map_data: dict,
    rules: List[Rule],
    profile: Optional[Profile] = None,
) -> dict:
    """Audit a redacted text against its map and current rules.

    Performs:
    - Profile-aware residual scan: only checks entity_types the profile marks for redact
    - Map structure validation
    - Map/file SHA-256 consistency check
    """
    warnings: List[str] = []

    # Residual scan — profile-aware
    all_residual = scan_regex(redacted_text, rules)
    if profile is not None:
        redact_types = profile.redact_entity_types(f.entity_type for f in all_residual)
        residual = [f for f in all_residual if f.entity_type in redact_types]
    else:
        residual = all_residual

    # Validate map structure
    if "entities" not in map_data:
        warnings.append("map_missing_entities")
    if "occurrences" not in map_data:
        warnings.append("map_missing_occurrences")
    if "source_sha256" not in map_data:
        warnings.append("map_missing_source_sha256")
    if "redacted_sha256" not in map_data:
        warnings.append("map_missing_redacted_sha256")

    # Validate redacted text SHA matches map
    actual_redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
    expected_redacted_sha = map_data.get("redacted_sha256", "")
    sha_match = actual_redacted_sha == expected_redacted_sha
    if not sha_match:
        warnings.append(
            f"redacted_sha256_mismatch: file={actual_redacted_sha[:16]} map={expected_redacted_sha[:16]}"
        )

    # Summary from map
    entities = map_data.get("entities", [])
    occurrences = map_data.get("occurrences", [])

    by_type: dict = {}
    by_engine: dict = {}
    for o in occurrences:
        eid = o.get("entity_id", "")
        for e in entities:
            if e["id"] == eid:
                t = e.get("entity_type", "UNKNOWN")
                by_type[t] = by_type.get(t, 0) + 1
                break
        eng = o.get("engine", "unknown")
        by_engine[eng] = by_engine.get(eng, 0) + 1

    return {
        "schema_version": "1.0",
        "profile": profile.name if profile else None,
        "summary": {
            "total_entities": len(entities),
            "total_occurrences": len(occurrences),
            "by_entity_type": by_type,
            "by_engine": by_engine,
        },
        "residual_scan": {
            "passed": len(residual) == 0,
            "findings": [
                {
                    "entity_type": f.entity_type,
                    "start": f.start,
                    "end": f.end,
                    "text_preview": f.text[:20],
                }
                for f in residual
            ],
        },
        "warnings": warnings,
    }
