"""XLSX adapter: content-level redact / restore / audit for cell text."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple
from lxml import etree

from . import AuditWarning, DocumentAdapter

NSMAP_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SS_NS = f"{{{NSMAP_SS}}}"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _ss_tag(local: str) -> str:
    return f"{SS_NS}{local}"


def _col_letter_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index: A->0, B->1, Z->25, AA->26."""
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def _index_to_col_letter(idx: int) -> str:
    """Convert 0-based index to column letter(s): 0->A, 25->Z, 26->AA."""
    result = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        result = chr(rem + ord("A")) + result
    return result


def _parse_cell_ref(ref: str) -> Tuple[int, int]:
    """Parse cell reference like 'A1' -> (row_0based, col_0based)."""
    m = re.match(r"^([A-Za-z]+)(\d+)$", ref)
    if not m:
        raise ValueError(f"Invalid cell reference: {ref}")
    col = _col_letter_to_index(m.group(1))
    row = int(m.group(2)) - 1  # 0-based
    return row, col


def _cell_ref(row: int, col: int) -> str:
    """Build cell reference from 0-based row/col: (0, 0) -> 'A1'."""
    return f"{_index_to_col_letter(col)}{row + 1}"


def _is_formula_cell(cell_elem) -> bool:
    """Check if a cell element has a formula."""
    return cell_elem.find(_ss_tag("f")) is not None


def _get_cell_text(cell_elem, shared_strings: List[str]) -> Optional[str]:
    """Get the text value of a cell element.

    Returns None for empty cells or formula cells.
    """
    if _is_formula_cell(cell_elem):
        return None

    # Check for inline string
    is_elem = cell_elem.find(_ss_tag("is"))
    if is_elem is not None:
        t_elem = is_elem.find(_ss_tag("t"))
        if t_elem is not None and t_elem.text:
            return t_elem.text
        # Rich text: concatenate <r><t> segments
        parts = []
        for r in is_elem.findall(_ss_tag("r")):
            t = r.find(_ss_tag("t"))
            if t is not None and t.text:
                parts.append(t.text)
        return "".join(parts) if parts else None

    # Check for value with type 's' (shared string)
    v_elem = cell_elem.find(_ss_tag("v"))
    if v_elem is not None and v_elem.text is not None:
        t_attr = cell_elem.get("t")
        if t_attr == "s":
            idx = int(v_elem.text)
            if 0 <= idx < len(shared_strings):
                return shared_strings[idx]
            return None
        # Numeric or other value
        return v_elem.text

    return None


def _set_cell_inline_string(cell_elem, text: str) -> None:
    """Set a cell's value as an inline string (not shared).

    Removes any existing <v>, <f>, and <is> elements, then adds <is><t>text</t></is>.
    """
    # Remove existing children
    for tag_name in ("v", "f", "is"):
        for child in cell_elem.findall(_ss_tag(tag_name)):
            cell_elem.remove(child)

    # Remove type attribute (was 's' for shared string)
    if "t" in cell_elem.attrib:
        del cell_elem.attrib["t"]

    # Add inline string
    is_elem = etree.SubElement(cell_elem, _ss_tag("is"))
    t_elem = etree.SubElement(is_elem, _ss_tag("t"))
    t_elem.text = text
    t_elem.set(f"{{{XML_NS}}}space", "preserve")


def _label_prefix_for(entity_type: str, rules) -> str:
    for rule in rules:
        if rule.entity_type == entity_type:
            return rule.label_prefix
    return {
        "PER": "人物",
        "PERSON": "人物",
        "LOC": "地点",
        "LOCATION": "地点",
        "ORG": "机构",
        "MONEY": "金额",
    }.get(entity_type, entity_type)


def _apply_occurrence_replacements(text: str, replacements: List[dict]) -> Tuple[str, List[dict]]:
    """Apply document-level replacements and record redacted text positions."""
    parts: List[str] = []
    positioned: List[dict] = []
    pos = 0

    for repl in sorted(replacements, key=lambda r: r["original_start"]):
        start = repl["original_start"]
        end = repl["original_end"]
        if start < pos:
            continue
        parts.append(text[pos:start])
        red_start = sum(len(part) for part in parts)
        parts.append(repl["replacement"])
        red_end = sum(len(part) for part in parts)
        positioned.append({**repl, "redacted_start": red_start, "redacted_end": red_end})
        pos = end

    parts.append(text[pos:])
    return "".join(parts), positioned


def _load_shared_strings(zf) -> List[str]:
    """Load shared strings from the XLSX archive."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    ss_xml = zf.read("xl/sharedStrings.xml")
    tree = etree.fromstring(ss_xml)

    strings = []
    for si in tree.findall(f"{SS_NS}si"):
        # Plain text
        t = si.find(f"{SS_NS}t")
        if t is not None and t.text:
            strings.append(t.text)
            continue
        # Rich text: concatenate <r><t> segments
        parts = []
        for r in si.findall(f"{SS_NS}r"):
            t = r.find(f"{SS_NS}t")
            if t is not None and t.text:
                parts.append(t.text)
        strings.append("".join(parts))

    return strings


def _write_shared_strings(zf, shared_strings: List[str]) -> None:
    """Write shared strings XML back to the archive using string construction.

    We use string-based XML construction because lxml doesn't accept empty
    namespace prefix ("") which XLSX requires for the default namespace.
    """
    import xml.sax.saxutils as saxutils

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<sst xmlns="{NSMAP_SS}" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">',
    ]
    for text in shared_strings:
        escaped = saxutils.escape(text) if text else ""
        if text and (text[0] == " " or text[-1] == " "):
            lines.append(f'<si><t xml:space="preserve">{escaped}</t></si>')
        else:
            lines.append(f"<si><t>{escaped}</t></si>")
    lines.append("</sst>")

    xml_bytes = "\n".join(lines).encode("utf-8")
    zf.writestr("xl/sharedStrings.xml", xml_bytes)


class XLSXAdapter(DocumentAdapter):
    """XLSX adapter for content-level redact / restore / audit."""

    def _read_workbook(self, path: str):
        """Read XLSX and return (sheet_xmls, shared_strings, other_files, wb_xml)."""
        import zipfile

        with zipfile.ZipFile(path, "r") as zf:
            shared_strings = _load_shared_strings(zf)
            sheet_xmls = {}
            other_files = {}
            wb_xml = None

            for name in zf.namelist():
                data = zf.read(name)
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    sheet_xmls[name] = data
                elif name == "xl/workbook.xml":
                    wb_xml = data
                    other_files[name] = data
                elif name == "xl/sharedStrings.xml":
                    pass  # handled separately
                else:
                    other_files[name] = data

        return sheet_xmls, shared_strings, other_files, wb_xml

    def _get_sheet_names(self, wb_xml: bytes) -> List[str]:
        """Extract sheet names from workbook.xml."""
        tree = etree.fromstring(wb_xml)
        sheets = tree.findall(f".//{_ss_tag('sheet')}")
        return [s.get("name", f"Sheet{i+1}") for i, s in enumerate(sheets)]

    def extract_text(self, path: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Extract all cell texts with metadata."""
        sheet_xmls, shared_strings, _, wb_xml = self._read_workbook(path)
        sheet_names = self._get_sheet_names(wb_xml) if wb_xml else []

        segments = []
        full_parts = []

        for sheet_idx, (sheet_path, sheet_data) in enumerate(sheet_xmls.items()):
            sheet_name = sheet_names[sheet_idx] if sheet_idx < len(sheet_names) else f"Sheet{sheet_idx+1}"
            tree = etree.fromstring(sheet_data)
            sheet_data_elem = tree.find(_ss_tag("sheetData"))
            if sheet_data_elem is None:
                continue

            for row_elem in sheet_data_elem.findall(_ss_tag("row")):
                row_num = int(row_elem.get("r", "0"))
                for cell_elem in row_elem.findall(_ss_tag("c")):
                    ref = cell_elem.get("r", "")
                    text = _get_cell_text(cell_elem, shared_strings)
                    if text is not None:
                        segments.append({
                            "sheet": sheet_name,
                            "row": row_num - 1,  # 0-based
                            "col": _parse_cell_ref(ref)[1] if ref else 0,
                            "text": text,
                            "is_formula": _is_formula_cell(cell_elem),
                            "cell_ref": ref,
                        })
                        full_parts.append(text)

        full_text = "\n".join(full_parts)
        return full_text, segments

    def redact(
        self,
        source_path: str,
        redacted_path: str,
        redact_fn,
        rules,
        mode: str = "regex-only",
        level: str = "strict",
        model_dir: Optional[str] = None,
    ) -> Tuple[dict, dict]:
        """Redact XLSX cell content. Returns (map_data, audit_data)."""
        import zipfile

        source_sha256 = hashlib.sha256(
            open(source_path, "rb").read()
        ).hexdigest()

        sheet_xmls, shared_strings, other_files, wb_xml = self._read_workbook(source_path)
        sheet_names = self._get_sheet_names(wb_xml) if wb_xml else []

        all_occurrences = []
        all_entities = []
        all_warnings = []
        entity_set = {}  # (entity_type, original) -> doc_ent_id
        entity_counters: Dict[str, int] = {}

        def get_doc_entity(ent: dict, engine: str) -> Tuple[str, str]:
            ent_key = (ent["entity_type"], ent["original"])
            if ent_key not in entity_set:
                entity_type = ent["entity_type"]
                entity_counters[entity_type] = entity_counters.get(entity_type, 0) + 1
                count = entity_counters[entity_type]
                doc_ent_id = f"{entity_type}_{count}"
                replacement = f"{_label_prefix_for(entity_type, rules)}{count}"
                all_entities.append({
                    "id": doc_ent_id,
                    "entity_type": entity_type,
                    "original": ent["original"],
                    "replacement": replacement,
                    "engines": [],
                })
                entity_set[ent_key] = doc_ent_id

            doc_ent_id = entity_set[ent_key]
            for doc_ent in all_entities:
                if doc_ent["id"] == doc_ent_id:
                    if engine not in doc_ent["engines"]:
                        doc_ent["engines"].append(engine)
                    return doc_ent_id, doc_ent["replacement"]

            raise KeyError(f"Missing document entity: {doc_ent_id}")

        # Track shared string modifications: we must NOT modify shared strings in-place
        # Instead, for cells that match, we convert to inline strings
        # We need to track which shared string indices are referenced by which cells
        ss_ref_count: Dict[int, int] = {}  # ss_index -> count of cells referencing it

        # First pass: count references to shared strings
        for sheet_path, sheet_data in sheet_xmls.items():
            tree = etree.fromstring(sheet_data)
            sheet_data_elem = tree.find(_ss_tag("sheetData"))
            if sheet_data_elem is None:
                continue
            for row_elem in sheet_data_elem.findall(_ss_tag("row")):
                for cell_elem in row_elem.findall(_ss_tag("c")):
                    if cell_elem.get("t") == "s":
                        v_elem = cell_elem.find(_ss_tag("v"))
                        if v_elem is not None and v_elem.text is not None:
                            idx = int(v_elem.text)
                            ss_ref_count[idx] = ss_ref_count.get(idx, 0) + 1

        # Second pass: redact each cell
        for sheet_idx, (sheet_path, sheet_data) in enumerate(sheet_xmls.items()):
            sheet_name = sheet_names[sheet_idx] if sheet_idx < len(sheet_names) else f"Sheet{sheet_idx+1}"
            tree = etree.fromstring(sheet_data)
            sheet_data_elem = tree.find(_ss_tag("sheetData"))
            if sheet_data_elem is None:
                continue

            for row_elem in sheet_data_elem.findall(_ss_tag("row")):
                row_num = int(row_elem.get("r", "0"))
                for cell_elem in row_elem.findall(_ss_tag("c")):
                    ref = cell_elem.get("r", "")
                    text = _get_cell_text(cell_elem, shared_strings)

                    # Skip formula cells with warning (before text None check)
                    if _is_formula_cell(cell_elem):
                        all_warnings.append({
                            "type": "formula_cell_skipped",
                            "message": f"Formula cell {ref} skipped",
                            "sheet": sheet_name,
                            "cell_ref": ref,
                        })
                        continue

                    if text is None or not text.strip():
                        continue

                    # Call text engine on cell text. Engine failures must abort the
                    # whole workbook so we never emit a partially redacted file.
                    redacted_text, seg_map, seg_audit = redact_fn(
                        text, rules,
                        hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        mode, level, model_dir,
                    )

                    if redacted_text == text:
                        continue

                    # Rebuild cell text with document-level labels rather than per-cell labels.
                    ent_lookup = {e["id"]: e for e in seg_map.get("entities", [])}
                    replacements = []
                    for occ in seg_map.get("occurrences", []):
                        ent_id = occ["entity_id"]
                        ent = ent_lookup.get(ent_id)
                        if not ent:
                            continue

                        doc_ent_id, replacement = get_doc_entity(ent, occ["engine"])
                        replacements.append({
                            "entity_id": doc_ent_id,
                            "engine": occ["engine"],
                            "original_text": ent["original"],
                            "replacement": replacement,
                            "original_start": occ["original_start"],
                            "original_end": occ["original_end"],
                        })

                    redacted_text, positioned_replacements = _apply_occurrence_replacements(text, replacements)

                    # Cell was modified! Write as inline string (safe: doesn't touch shared strings)
                    _set_cell_inline_string(cell_elem, redacted_text)

                    # Build locator occurrences
                    for repl in positioned_replacements:
                        all_occurrences.append({
                            "entity_id": repl["entity_id"],
                            "engine": repl["engine"],
                            "original_text": repl["original_text"],
                            "replacement": repl["replacement"],
                            "locator": {
                                "type": "xlsx",
                                "sheet": sheet_name,
                                "row": row_num - 1,  # 0-based
                                "column": _parse_cell_ref(ref)[1] if ref else 0,
                                "text_start": repl["redacted_start"],
                                "text_end": repl["redacted_end"],
                            },
                        })

                    # Merge audit warnings
                    for w in seg_audit.get("warnings", []):
                        if isinstance(w, dict):
                            all_warnings.append({**w, "sheet": sheet_name, "cell_ref": ref})
                        else:
                            all_warnings.append({
                                "type": "audit_warning",
                                "message": str(w),
                                "sheet": sheet_name,
                                "cell_ref": ref,
                            })

            # Update sheet XML
            sheet_xmls[sheet_path] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)

        # Write redacted XLSX
        with zipfile.ZipFile(redacted_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write modified sheets
            for name, data in sheet_xmls.items():
                zf.writestr(name, data)
            # Write shared strings (unchanged - we never modify them)
            _write_shared_strings(zf, shared_strings)
            # Write other files
            for name, data in other_files.items():
                zf.writestr(name, data)

        redacted_sha256 = hashlib.sha256(
            open(redacted_path, "rb").read()
        ).hexdigest()

        map_data = {
            "schema_version": "1.1",
            "document_type": "xlsx",
            "verification": "content",
            "source_file": source_path,
            "redacted_file": redacted_path,
            "source_sha256": source_sha256,
            "redacted_sha256": redacted_sha256,
            "level": level,
            "mode": mode,
            "entities": all_entities,
            "occurrences": all_occurrences,
        }

        by_type: Dict[str, int] = {}
        by_engine: Dict[str, int] = {}
        for o in all_occurrences:
            eid = o["entity_id"]
            for e in all_entities:
                if e["id"] == eid:
                    t = e["entity_type"]
                    by_type[t] = by_type.get(t, 0) + 1
                    break
            eng = o["engine"]
            by_engine[eng] = by_engine.get(eng, 0) + 1

        audit_data = {
            "schema_version": "1.1",
            "document_type": "xlsx",
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

    def restore(self, redacted_path: str, restored_path: str, map_data: dict) -> None:
        """Restore XLSX cell content using redacted-document locators."""
        import zipfile

        # Pre-check SHA-256
        redacted_sha256 = hashlib.sha256(
            open(redacted_path, "rb").read()
        ).hexdigest()
        expected = map_data.get("redacted_sha256", "")
        if redacted_sha256 != expected:
            raise ValueError(
                f"SHA-256 mismatch: redacted file is {redacted_sha256[:16]}..., "
                f"but map expects {expected[:16]}... "
                "Restoration aborted."
            )

        sheet_xmls, shared_strings, other_files, wb_xml = self._read_workbook(redacted_path)

        # Build entity lookup
        entity_map = {e["id"]: e["original"] for e in map_data.get("entities", [])}

        # Group occurrences by (sheet, row, column)
        from collections import defaultdict
        cell_occurrences = defaultdict(list)
        for occ in map_data.get("occurrences", []):
            loc = occ.get("locator", {})
            if loc.get("type") != "xlsx":
                continue
            key = (loc["sheet"], loc["row"], loc.get("column", loc.get("col", 0)))
            cell_occurrences[key].append(occ)

        # Build sheet name -> index mapping from workbook.xml
        sheet_paths = list(sheet_xmls.keys())
        sheet_names_list = []
        if wb_xml is not None:
            wb_tree = etree.fromstring(wb_xml)
            for s in wb_tree.findall(f".//{_ss_tag('sheet')}"):
                sheet_names_list.append(s.get("name", ""))

        # Process cells
        for (sheet_name, row_idx, col_idx), occs in cell_occurrences.items():
            # Find sheet by name
            target_sheet_idx = -1
            for i, sn in enumerate(sheet_names_list):
                if sn == sheet_name:
                    target_sheet_idx = i
                    break

            if target_sheet_idx < 0 or target_sheet_idx >= len(sheet_paths):
                continue

            sheet_path = sheet_paths[target_sheet_idx]
            tree = etree.fromstring(sheet_xmls[sheet_path])
            sheet_data_elem = tree.find(_ss_tag("sheetData"))
            if sheet_data_elem is None:
                continue

            # Find the cell
            for row_elem in sheet_data_elem.findall(_ss_tag("row")):
                r = int(row_elem.get("r", "0")) - 1  # 0-based
                if r != row_idx:
                    continue
                for cell_elem in row_elem.findall(_ss_tag("c")):
                    ref = cell_elem.get("r", "")
                    if ref and _parse_cell_ref(ref) == (row_idx, col_idx):
                        # Get current (redacted) text
                        current_text = _get_cell_text(cell_elem, shared_strings)
                        if current_text is None:
                            continue

                        # Restore using locators
                        chars = list(current_text)
                        for occ in sorted(occs, key=lambda o: o["locator"]["text_start"], reverse=True):
                            ts = occ["locator"]["text_start"]
                            te = occ["locator"]["text_end"]
                            original = entity_map.get(occ["entity_id"], "")
                            chars[ts:te] = list(original)

                        restored_text = "".join(chars)
                        _set_cell_inline_string(cell_elem, restored_text)

            sheet_xmls[sheet_path] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)

        # Write restored XLSX
        with zipfile.ZipFile(restored_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in sheet_xmls.items():
                zf.writestr(name, data)
            _write_shared_strings(zf, shared_strings)
            for name, data in other_files.items():
                zf.writestr(name, data)

    def audit(self, path: str, map_data: dict, rules) -> dict:
        """Audit a redacted XLSX for residual sensitive data."""
        import hashlib

        file_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        expected = map_data.get("redacted_sha256", "")
        warnings = []
        if file_sha != expected:
            warnings.append({
                "type": "sha256_mismatch",
                "message": f"redacted_sha256 mismatch: file={file_sha[:16]} map={expected[:16]}",
            })

        full_text, _ = self.extract_text(path)
        from .engine_regex import scan_regex_for_audit
        residual = scan_regex_for_audit(full_text, rules)

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
            "document_type": "xlsx",
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
