"""CSV adapter: cell-level redaction with dialect/encoding/quote preservation.

Byte-safe round-trip: only cell text content is modified.
Preserves dialect (delimiter, quotechar, quoting), encoding (BOM), newline, field quoting.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from ..engine.regex import scan_regex
from ..engine.merge import merge_spans
from ..engine.span import Span
from ..profile import load_profile
from ..rules import Rule

BOM_UTF8 = b"\xef\xbb\xbf"


@dataclass
class CsvFile:
    """Represents a CSV file with its byte-level metadata."""
    raw: bytes
    text: str
    has_bom: bool
    newline: str  # "\r\n" or "\n"
    dialect: csv.Dialect
    rows: List[List[str]]  # parsed rows
    field_quoting: List[List[bool]]  # per-field quoting state (True = quoted in original)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


def _detect_newline(content: bytes) -> str:
    """Detect newline style from raw bytes."""
    if b"\r\n" in content:
        return "\r\n"
    return "\n"


def _parse_csv_with_quoting(text: str, dialect: csv.Dialect) -> Tuple[List[List[str]], List[List[bool]]]:
    """Parse CSV and track which fields are quoted in the original text.

    Returns (rows, field_quoting) where field_quoting[i][j] is True if
    field [i][j] was quoted in the original.
    """
    lines = text.splitlines()

    rows = []
    field_quoting = []
    quotechar = dialect.quotechar or '"'
    delimiter = dialect.delimiter or ","

    for line in lines:
        if not line.strip():
            rows.append([])
            field_quoting.append([])
            continue

        fields = []
        quoting = []
        i = 0
        while i < len(line):
            if line[i] == quotechar:
                # Quoted field
                quoting.append(True)
                j = i + 1
                while j < len(line):
                    if line[j] == quotechar:
                        if j + 1 < len(line) and line[j + 1] == quotechar:
                            j += 2  # escaped quote
                        else:
                            break
                    j += 1
                # Extract content between quotes
                content = line[i + 1:j].replace(quotechar + quotechar, quotechar)
                fields.append(content)
                i = j + 1
                if i < len(line) and line[i] == delimiter:
                    i += 1
            else:
                # Unquoted field
                quoting.append(False)
                j = line.find(delimiter, i)
                if j == -1:
                    j = len(line)
                fields.append(line[i:j])
                i = j + 1

        if line.endswith(delimiter):
            fields.append("")
            quoting.append(False)

        rows.append(fields)
        field_quoting.append(quoting)

    return rows, field_quoting


def read_csv(path: str) -> CsvFile:
    """Read a CSV file preserving byte-level characteristics."""
    raw = open(path, "rb").read()

    has_bom = raw[:3] == BOM_UTF8
    content_bytes = raw[3:] if has_bom else raw
    newline = _detect_newline(content_bytes)
    text = content_bytes.decode("utf-8")

    # Detect dialect using csv.Sniffer
    try:
        dialect = csv.Sniffer().sniff(text[:1024])
    except csv.Error:
        # Fallback to excel dialect
        dialect = csv.excel()

    # Parse rows and track field quoting
    rows, field_quoting = _parse_csv_with_quoting(text, dialect)

    return CsvFile(
        raw=raw,
        text=text,
        has_bom=has_bom,
        newline=newline,
        dialect=dialect,
        rows=rows,
        field_quoting=field_quoting,
    )


def _build_csv_line(fields: List[str], quoting: List[bool], dialect: csv.Dialect) -> str:
    """Build a CSV line preserving original quoting state for each field."""
    quotechar = dialect.quotechar or '"'
    delimiter = dialect.delimiter or ","
    escapechar = getattr(dialect, 'escapechar', None)
    doublequote = getattr(dialect, 'doublequote', True)

    parts = []
    for i, (field, is_quoted) in enumerate(zip(fields, quoting)):
        if is_quoted:
            # Preserve quoted style: escape quotes inside
            escaped = field
            if doublequote:
                escaped = escaped.replace(quotechar, quotechar + quotechar)
            elif escapechar:
                escaped = escaped.replace(quotechar, escapechar + quotechar)
            parts.append(f"{quotechar}{escaped}{quotechar}")
        else:
            # Unquoted: check if field contains delimiter/newline/quote
            needs_quote = delimiter in field or '\n' in field or quotechar in field
            if needs_quote:
                escaped = field
                if doublequote:
                    escaped = escaped.replace(quotechar, quotechar + quotechar)
                elif escapechar:
                    escaped = escaped.replace(quotechar, escapechar + quotechar)
                parts.append(f"{quotechar}{escaped}{quotechar}")
            else:
                parts.append(field)

    return delimiter.join(parts)


def write_csv(path: str, csv_file: CsvFile, redacted_rows: List[List[str]]) -> None:
    """Write CSV back preserving dialect, encoding, newline, and field quoting."""
    lines = []
    for i, (row, quoting) in enumerate(zip(redacted_rows, csv_file.field_quoting)):
        if not row:
            lines.append("")
            continue
        line = _build_csv_line(row, quoting, csv_file.dialect)
        lines.append(line)

    text = csv_file.newline.join(lines)
    if csv_file.text.endswith(csv_file.newline):
        text += csv_file.newline

    raw = text.encode("utf-8")
    if csv_file.has_bom:
        raw = BOM_UTF8 + raw

    with open(path, "wb") as f:
        f.write(raw)


def _redact_cell_text(
    text: str,
    rules: List[Rule],
    redact_fn: Callable,
    source_sha256: str,
    mode: str,
    level: str,
    model_dir: Optional[str],
) -> Tuple[str, dict, dict]:
    """Redact a single cell's text content.

    Returns (redacted_text, map_data, audit_data).
    """
    if not text.strip():
        return text, {"entities": [], "occurrences": []}, {"summary": {"total_entities": 0, "total_occurrences": 0}}

    redacted_text, map_data, audit_data = redact_fn(
        text, rules, source_sha256, mode, level, model_dir
    )
    return redacted_text, map_data, audit_data


def _merge_csv_maps(cell_maps: List[dict], cell_positions: List[Tuple[int, int]]) -> dict:
    """Merge per-cell maps into a single CSV-level map."""
    all_entities = []
    all_occurrences = []
    entity_id_map = {}  # old_id -> new_id

    for cell_idx, (cell_map, (row_idx, col_idx)) in enumerate(zip(cell_maps, cell_positions)):
        # Remap entity IDs to be globally unique
        for entity in cell_map.get("entities", []):
            old_id = entity["id"]
            new_id = f"R{row_idx}C{col_idx}_{old_id}"
            entity_id_map[old_id] = new_id

            all_entities.append({
                "id": new_id,
                "entity_type": entity["entity_type"],
                "original": entity["original"],
                "replacement": entity["replacement"],
                "engines": entity.get("engines", []),
            })

        for occ in cell_map.get("occurrences", []):
            old_eid = occ["entity_id"]
            new_eid = entity_id_map.get(old_eid, old_eid)
            all_occurrences.append({
                "entity_id": new_eid,
                "engine": occ.get("engine", "regex"),
                "original_start": occ["original_start"],
                "original_end": occ["original_end"],
                "redacted_start": occ["redacted_start"],
                "redacted_end": occ["redacted_end"],
                "locator": {
                    "type": "csv",
                    "row": row_idx,
                    "column": col_idx,
                },
            })

    return {
        "schema_version": "1.1",
        "document_type": "csv",
        "verification": "byte",
        "entities": all_entities,
        "occurrences": all_occurrences,
    }


def csv_redact(
    source_path: str,
    redacted_path: str,
    redact_fn: Callable,
    rules: List[Rule],
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
) -> Tuple[dict, dict]:
    """Redact a CSV file: only cell text content is modified.

    Preserves dialect, encoding, newline, field quoting.
    Returns (map_data, audit_data).
    """
    csv_file = read_csv(source_path)
    source_sha = csv_file.sha256

    redacted_rows = []
    cell_maps = []
    cell_positions = []
    total_entities = 0
    total_occurrences = 0
    all_warnings = []
    profile = getattr(redact_fn, "_profile", None)
    profile_name = profile.name if profile else None

    for row_idx, row in enumerate(csv_file.rows):
        redacted_row = []
        for col_idx, cell in enumerate(row):
            redacted_cell, cell_map, cell_audit = _redact_cell_text(
                cell, rules, redact_fn, source_sha, mode, level, model_dir
            )
            redacted_row.append(redacted_cell)

            if cell_map.get("entities"):
                if profile_name is None:
                    profile_name = cell_map.get("profile")
                cell_maps.append(cell_map)
                cell_positions.append((row_idx, col_idx))
                total_entities += len(cell_map.get("entities", []))
                total_occurrences += len(cell_map.get("occurrences", []))

            if cell_audit.get("warnings"):
                all_warnings.extend(cell_audit["warnings"])

        redacted_rows.append(redacted_row)

    # Write redacted CSV
    write_csv(redacted_path, csv_file, redacted_rows)

    # Compute redacted SHA
    redacted_raw = open(redacted_path, "rb").read()
    redacted_sha = hashlib.sha256(redacted_raw).hexdigest()

    # Build merged map
    if cell_maps:
        map_data = _merge_csv_maps(cell_maps, cell_positions)
    else:
        map_data = {
            "schema_version": "1.1",
            "document_type": "csv",
            "verification": "byte",
            "entities": [],
            "occurrences": [],
        }

    map_data["source_file"] = source_path
    map_data["redacted_file"] = redacted_path
    map_data["source_sha256"] = source_sha
    map_data["redacted_sha256"] = redacted_sha
    if profile is None and profile_name:
        try:
            profile = load_profile(profile_name)
        except FileNotFoundError:
            profile = None
    if profile_name is not None:
        map_data["profile"] = profile_name
    map_data["byte_metadata"] = {
        "encoding": "utf-8-sig" if csv_file.has_bom else "utf-8",
        "has_bom": csv_file.has_bom,
        "newline": csv_file.newline,
        "delimiter": csv_file.dialect.delimiter,
        "quotechar": csv_file.dialect.quotechar,
    }

    # Build audit
    by_type: Dict[str, int] = {}
    by_engine: Dict[str, int] = {}
    for o in map_data.get("occurrences", []):
        eid = o["entity_id"]
        for e in map_data.get("entities", []):
            if e["id"] == eid:
                t = e["entity_type"]
                by_type[t] = by_type.get(t, 0) + 1
                break
        eng = o.get("engine", "regex")
        by_engine[eng] = by_engine.get(eng, 0) + 1

    # Residual scan on redacted text
    redacted_text = csv_file.newline.join(
        csv_file.newline.join(row) for row in redacted_rows
    )
    residual = scan_regex(redacted_text, rules)
    if profile is not None:
        redact_types = profile.redact_entity_types(f.entity_type for f in residual)
        residual = [f for f in residual if f.entity_type in redact_types]

    audit_data = {
        "schema_version": "1.1",
        "document_type": "csv",
        "profile": profile_name,
        "summary": {
            "total_entities": total_entities,
            "total_occurrences": total_occurrences,
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
        "warnings": all_warnings,
    }

    return map_data, audit_data


def csv_restore(
    redacted_path: str,
    restored_path: str,
    map_data: dict,
) -> None:
    """Restore a redacted CSV using position-based reversal from map.

    Verifies redacted SHA-256 before restoration.
    """
    csv_file = read_csv(redacted_path)
    redacted_sha = csv_file.sha256

    # Pre-check: verify redacted file matches map
    expected_redacted_sha = map_data.get("redacted_sha256", "")
    if redacted_sha != expected_redacted_sha:
        raise ValueError(
            f"SHA-256 mismatch: redacted file is {redacted_sha[:16]}..., "
            f"but map expects {expected_redacted_sha[:16]}... "
            "The map file does not correspond to this redacted file. "
            "Restoration aborted to prevent data corruption."
        )

    # Build entity lookup: entity_id -> original
    entity_map = {}
    for entity in map_data.get("entities", []):
        entity_map[entity["id"]] = entity["original"]

    # Group occurrences by (row, col)
    cell_occurrences: Dict[Tuple[int, int], List[dict]] = {}
    for occ in map_data.get("occurrences", []):
        loc = occ.get("locator", {})
        if loc.get("type") != "csv":
            continue
        key = (loc["row"], loc["column"])
        if key not in cell_occurrences:
            cell_occurrences[key] = []
        cell_occurrences[key].append(occ)

    # Restore each cell
    restored_rows = []
    for row_idx, row in enumerate(csv_file.rows):
        restored_row = []
        for col_idx, cell in enumerate(row):
            key = (row_idx, col_idx)
            if key in cell_occurrences:
                # Sort occurrences by redacted_start descending (end-to-start)
                occs = sorted(
                    cell_occurrences[key],
                    key=lambda o: o["redacted_start"],
                    reverse=True,
                )
                chars = list(cell)
                for occ in occs:
                    rs = occ["redacted_start"]
                    re = occ["redacted_end"]
                    entity_id = occ["entity_id"]
                    original = entity_map.get(entity_id, "")
                    chars[rs:re] = list(original)
                restored_row.append("".join(chars))
            else:
                restored_row.append(cell)
        restored_rows.append(restored_row)

    # Write restored CSV
    write_csv(restored_path, csv_file, restored_rows)

    # Post-check: verify restored matches source
    source_sha = map_data.get("source_sha256", "")
    if source_sha:
        restored_raw = open(restored_path, "rb").read()
        restored_sha = hashlib.sha256(restored_raw).hexdigest()
        if restored_sha != source_sha:
            raise ValueError(
                f"Post-restoration SHA-256 mismatch: restored is {restored_sha[:16]}..., "
                f"but map source expects {source_sha[:16]}... "
                "Restoration produced incorrect result."
            )


def csv_audit(
    redacted_path: str,
    map_data: dict,
    rules: List[Rule],
) -> dict:
    """Audit a redacted CSV for residual sensitive data."""
    csv_file = read_csv(redacted_path)

    # Reconstruct redacted text for residual scan
    redacted_text = csv_file.newline.join(
        csv_file.newline.join(row) for row in csv_file.rows
    )
    residual = scan_regex(redacted_text, rules)
    profile_name = map_data.get("profile")
    if profile_name:
        try:
            profile = load_profile(profile_name)
        except FileNotFoundError:
            profile = None
        if profile is not None:
            redact_types = profile.redact_entity_types(f.entity_type for f in residual)
            residual = [f for f in residual if f.entity_type in redact_types]

    entities = map_data.get("entities", [])
    occurrences = map_data.get("occurrences", [])

    by_type: Dict[str, int] = {}
    by_engine: Dict[str, int] = {}
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
        "schema_version": "1.1",
        "document_type": "csv",
        "profile": profile_name,
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
        "warnings": [],
    }
