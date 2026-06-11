"""Restore redacted text using position-based reversal from map."""

from __future__ import annotations

import hashlib
from typing import Optional

from .io import BOM_UTF8


def _restored_bytes(restored: str, map_data: dict) -> bytes:
    raw = restored.encode("utf-8")
    if map_data.get("byte_metadata", {}).get("has_bom", False):
        raw = BOM_UTF8 + raw
    return raw


def restore(
    redacted_text: str,
    map_data: dict,
    redacted_file_sha256: Optional[str] = None,
) -> str:
    """Restore redacted text by reversing label replacements using position mapping.

    Uses redacted_start/redacted_end from occurrences. Does NOT do string lookup.
    Restores from end to start so earlier positions remain valid.

    Raises ValueError if SHA-256 mismatch is detected before restoration.
    """
    # Pre-check: verify redacted file matches map
    expected_redacted_sha = map_data.get("redacted_sha256", "")
    if redacted_file_sha256 and expected_redacted_sha:
        if redacted_file_sha256 != expected_redacted_sha:
            raise ValueError(
                f"SHA-256 mismatch: redacted file is {redacted_file_sha256[:16]}..., "
                f"but map expects {expected_redacted_sha[:16]}... "
                "The map file does not correspond to this redacted file. "
                "Restoration aborted to prevent data corruption."
            )

    # Build entity lookup: entity_id -> original
    entity_map = {}
    for entity in map_data.get("entities", []):
        entity_map[entity["id"]] = entity["original"]

    # Get occurrences sorted by redacted_start descending (end-to-start)
    occurrences = sorted(
        map_data.get("occurrences", []),
        key=lambda o: o["redacted_start"],
        reverse=True,
    )

    # Restore from end to start
    chars = list(redacted_text)
    for occ in occurrences:
        rs = occ["redacted_start"]
        re = occ["redacted_end"]
        entity_id = occ["entity_id"]
        original = entity_map.get(entity_id, "")
        # Replace the redacted span with original text
        chars[rs:re] = list(original)

    restored = "".join(chars)

    # Post-check: verify restored matches source
    expected_source_sha = map_data.get("source_sha256", "")
    if expected_source_sha:
        restored_sha = hashlib.sha256(_restored_bytes(restored, map_data)).hexdigest()
        if restored_sha != expected_source_sha:
            raise ValueError(
                f"Post-restoration SHA-256 mismatch: restored is {restored_sha[:16]}..., "
                f"but map source expects {expected_source_sha[:16]}... "
                "Restoration produced incorrect result."
            )

    return restored
