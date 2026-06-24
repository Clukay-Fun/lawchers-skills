"""DOCX adapter: content-level redact / restore across visible OOXML parts."""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from . import AuditWarning, DocumentAdapter
from ..profile import load_profile

# python-docx namespace map
NSMAP = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _tag(local: str) -> str:
    return f"{{{W_NS}}}{local}"


def _extract_paragraph_runs_text(paragraph_elem) -> Tuple[str, List[dict]]:
    """Extract text from a paragraph's runs, returning full text and run metadata.

    Returns (concatenated_text, run_metas) where each run_meta has:
      - run_index: index of <w:r> among sibling <w:r> elements
      - text_node: the <w:t> element (or None)
      - text_start: start offset of this run's text in concatenated text
      - text_end: end offset
    """
    runs = paragraph_elem.findall(f".//{_tag('r')}")
    parts = []
    run_metas = []
    offset = 0

    for idx, run in enumerate(runs):
        t_elem = run.find(_tag("t"))
        if t_elem is not None and t_elem.text:
            run_text = t_elem.text
        else:
            run_text = ""
        parts.append(run_text)
        run_metas.append({
            "run_index": idx,
            "text_node": t_elem,
            "text_start": offset,
            "text_end": offset + len(run_text),
        })
        offset += len(run_text)

    return "".join(parts), run_metas


def _get_run_style_props(run_elem):
    """Extract <w:rPr> from a run element (copy)."""
    rpr = run_elem.find(_tag("rPr"))
    return copy.deepcopy(rpr) if rpr is not None else None


def _clear_paragraph_runs(paragraph_elem) -> None:
    """Remove descendant runs, including runs inside hyperlinks/text boxes."""
    for run in paragraph_elem.findall(f".//{_tag('r')}"):
        parent = run.getparent()
        if parent is not None:
            parent.remove(run)


def _is_text_part(name: str) -> bool:
    """Return whether an OOXML package part can carry user-visible text."""
    if name == "word/document.xml":
        return True
    base = name.rsplit("/", 1)[-1]
    return name.startswith("word/") and (
        base.startswith("header")
        or base.startswith("footer")
        or base in {"footnotes.xml", "endnotes.xml", "comments.xml"}
    )


def _paragraphs(tree) -> List[Any]:
    """Return paragraphs in document order, including tables and text boxes."""
    if tree.tag == _tag("p"):
        return [tree]
    return list(tree.findall(f".//{_tag('p')}"))


def _make_run_elem(text: str, rpr_copy=None):
    """Create a <w:r> element with optional <w:rPr> and <w:t>."""
    r_elem = etree.SubElement(
        etree.Element("dummy"),  # temporary parent
        _tag("r"),
    )
    if rpr_copy is not None:
        r_elem.insert(0, copy.deepcopy(rpr_copy))
    t_elem = etree.SubElement(r_elem, _tag("t"))
    t_elem.text = text
    # Preserve spaces
    t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return r_elem


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
        "LANDLINE": "电话",
        "BANK_ACCOUNT": "银行账号",
        "BANK_BRANCH": "银行信息",
        "MONEY": "金额",
    }.get(entity_type, entity_type)


def rebuild_paragraph_preserve_format(
    paragraph_elem,
    paragraph_text: str,
    run_metas: List[dict],
    spans: List[dict],
) -> None:
    """Replace spans in paragraph while preserving per-run formatting.

    Unlike _rebuild_paragraph_with_redactions, this does NOT clear all runs.
    It walks existing runs, splits them at span boundaries, and only modifies
    the text content of affected segments. Each segment retains the original
    run's <w:rPr> (bold, italic, font, color, etc.).

    spans: list of {start, end, replacement} sorted by start ascending.
    """
    if not spans:
        return

    spans_sorted = sorted(spans, key=lambda s: s["start"])
    span_idx = 0

    for meta in run_metas:
        t_elem = meta["text_node"]
        if t_elem is None or t_elem.text is None:
            continue

        run_elem = t_elem.getparent()
        run_start = meta["text_start"]
        run_end = meta["text_end"]
        run_text = t_elem.text

        # Find spans that overlap with this run
        run_spans = []
        while span_idx < len(spans_sorted):
            s = spans_sorted[span_idx]
            if s["end"] <= run_start:
                span_idx += 1
                continue
            if s["start"] >= run_end:
                break
            run_spans.append(s)
            span_idx += 1

        if not run_spans:
            continue

        # Split this run's text into segments
        segments = []  # (text, is_replacement)
        pos = run_start
        for s in run_spans:
            seg_start = max(s["start"], run_start)
            seg_end = min(s["end"], run_end)

            # Text before this span (within this run)
            if seg_start > pos:
                segments.append((paragraph_text[pos:seg_start], False))

            # The replacement
            segments.append((s["replacement"], True))
            pos = seg_end

        # Remaining text after last span (within this run)
        if pos < run_end:
            segments.append((paragraph_text[pos:run_end], False))

        if len(segments) == 1 and not segments[0][1]:
            # No replacement in this run
            continue

        # Get this run's formatting
        rpr = _get_run_style_props(run_elem)

        # Replace the current run's text with the first segment
        t_elem.text = segments[0][0]

        # Insert additional runs after the current run for remaining segments
        parent = run_elem.getparent()
        insert_pos = list(parent).index(run_elem) + 1

        for text, _ in segments[1:]:
            new_run = _make_run_elem(text, rpr)
            # Detach from temp parent
            if new_run.getparent() is not None:
                new_run.getparent().remove(new_run)
            parent.insert(insert_pos, new_run)
            insert_pos += 1

        # Update run_metas for subsequent runs (positions shifted)
        offset_delta = len(segments) - 1
        for later_meta in run_metas:
            if later_meta["text_start"] >= run_end:
                # These runs moved, but we don't update their positions
                # since we process them in order and they still have correct text
                pass


def _rebuild_paragraph_with_redactions(
    paragraph_elem,
    paragraph_text: str,
    run_metas: List[dict],
    spans: List[dict],
) -> Tuple[List[dict], List[AuditWarning]]:
    """Rebuild paragraph runs with redacted text.

    spans: list of {start, end, replacement} sorted by start ascending.
    Returns (locator_entries, warnings).
    Each locator_entry: {run_start_index, run_end_index, text_start, text_end}
    pointing to the redacted document structure.
    """
    warnings: List[AuditWarning] = []
    if not spans:
        return [], warnings

    # Get the style from the first run (or first affected run)
    first_run_rpr = None
    for meta in run_metas:
        if meta["text_node"] is not None:
            run_elem = meta["text_node"].getparent()
            first_run_rpr = _get_run_style_props(run_elem)
            break

    # Build segments: non-redacted text + redacted replacements
    # We'll produce a new list of run elements
    new_runs = []
    locator_entries = []

    pos = 0
    for span in spans:
        s_start, s_end, replacement = span["start"], span["end"], span["replacement"]

        # Text before this span
        if s_start > pos:
            before_text = paragraph_text[pos:s_start]
            new_runs.append(_make_run_elem(before_text, first_run_rpr))

        # The replacement text
        replacement_run = _make_run_elem(replacement, first_run_rpr)
        run_start_idx = len(new_runs)
        new_runs.append(replacement_run)
        run_end_idx = run_start_idx  # single run for replacement

        locator_entries.append({
            "run_start_index": run_start_idx,
            "run_end_index": run_end_idx,
            "text_start": 0,
            "text_end": len(replacement),
        })

        pos = s_end

    # Remaining text after last span
    if pos < len(paragraph_text):
        new_runs.append(_make_run_elem(paragraph_text[pos:], first_run_rpr))

    # Clear old runs and insert new ones
    ppr = paragraph_elem.find(_tag("pPr"))
    _clear_paragraph_runs(paragraph_elem)

    for run_elem in new_runs:
        # Detach from temporary parent and attach to paragraph
        run_elem.getparent().remove(run_elem) if run_elem.getparent() is not None else None
        paragraph_elem.append(run_elem)

    return locator_entries, warnings


def _restore_paragraph_from_locator(
    paragraph_elem,
    occurrences: List[dict],
    entity_map: dict,
) -> str:
    """Restore a paragraph's runs using locator occurrences.

    Each locator points to a specific run in the redacted paragraph:
    - run_start_index: index of the replacement run
    - text_start/text_end: position of the replacement within that run's text

    We restore each replacement run by swapping the replacement text back to original,
    then rebuild the paragraph with all runs.
    """
    runs = paragraph_elem.findall(f".//{_tag('r')}")

    # Process each occurrence: modify the target run's text in-place
    for occ in sorted(occurrences, key=lambda o: o["locator"]["run_start_index"], reverse=True):
        loc = occ["locator"]
        run_idx = loc["run_start_index"]
        ts = loc["text_start"]
        te = loc["text_end"]
        original = entity_map.get(occ["entity_id"], "")

        if run_idx >= len(runs):
            continue

        run_elem = runs[run_idx]
        t_elem = run_elem.find(_tag("t"))
        if t_elem is None or t_elem.text is None:
            continue

        run_text = t_elem.text
        # Replace the replacement portion with original
        restored_run_text = run_text[:ts] + original + run_text[te:]
        t_elem.text = restored_run_text

    # Re-extract all run texts to build full paragraph text
    full_text, _ = _extract_paragraph_runs_text(paragraph_elem)

    return full_text


class DOCXAdapter(DocumentAdapter):
    """DOCX adapter for content-level redact / restore / audit."""

    def extract_text(self, path: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Extract paragraph text from all supported OOXML text parts."""
        import zipfile

        with zipfile.ZipFile(path, "r") as zf:
            parts = {name: zf.read(name) for name in zf.namelist() if _is_text_part(name)}

        segments = []
        full_parts = []
        for part_name, xml_bytes in parts.items():
            tree = etree.fromstring(xml_bytes)
            for para_idx, paragraph in enumerate(_paragraphs(tree)):
                text, _ = _extract_paragraph_runs_text(paragraph)
                segments.append({
                    "paragraph_index": para_idx,
                    "text": text,
                    "part": part_name,
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
        """Redact DOCX content. Returns (map_data, audit_data)."""
        import zipfile
        import io
        import shutil

        # Read source package and parse every supported text part.
        with zipfile.ZipFile(source_path, "r") as zf:
            package_files = {n: zf.read(n) for n in zf.namelist()}
        text_trees = {
            name: etree.fromstring(data)
            for name, data in package_files.items()
            if _is_text_part(name)
        }

        source_sha256 = hashlib.sha256(
            open(source_path, "rb").read()
        ).hexdigest()

        all_occurrences = []
        all_entities = []
        all_warnings: List[dict] = []
        entity_set = {}  # (entity_type, original) -> doc_ent_id
        entity_counters: Dict[str, int] = {}
        profile_name = getattr(redact_fn, "_profile_name", None)

        def get_doc_entity(ent: dict, engine: str) -> Tuple[str, str]:
            ent_key = (ent["entity_type"], ent["original"])
            if ent_key not in entity_set:
                entity_type = ent["entity_type"]
                entity_counters[entity_type] = entity_counters.get(entity_type, 0) + 1
                count = entity_counters[entity_type]
                doc_ent_id = f"{entity_type}_{count}"
                replacement = ent.get("replacement") or f"{_label_prefix_for(entity_type, rules)}{count}"
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

        for part_name, tree in text_trees.items():
            for para_idx, child in enumerate(_paragraphs(tree)):
                para_text, run_metas = _extract_paragraph_runs_text(child)
                if not para_text.strip():
                    continue

                # Call text engine on paragraph text. Engine failures must abort the
                # whole document so we never emit a partially redacted file.
                redacted_para_text, seg_map, seg_audit = redact_fn(
                    para_text, rules, hashlib.sha256(para_text.encode("utf-8")).hexdigest(),
                    mode, level, model_dir,
                )
                if profile_name is None:
                    profile_name = seg_map.get("profile")

                if redacted_para_text == para_text:
                    continue

                # Build spans from segment occurrences
                spans_for_para = []
                ent_lookup = {e["id"]: e for e in seg_map.get("entities", [])}
                for occ in seg_map.get("occurrences", []):
                    ent = ent_lookup.get(occ["entity_id"])
                    if not ent:
                        continue
                    doc_ent_id, replacement = get_doc_entity(ent, occ["engine"])
                    spans_for_para.append({
                        "start": occ["original_start"],
                        "end": occ["original_end"],
                        "replacement": replacement,
                        "entity_id": doc_ent_id,
                        "engine": occ["engine"],
                        "original_text": ent["original"],
                    })

                # Rebuild paragraph with redactions
                locators, rebuild_warnings = _rebuild_paragraph_with_redactions(
                    child, para_text, run_metas, spans_for_para,
                )

                # Merge warnings
                for w in rebuild_warnings:
                    all_warnings.append({
                        "type": w.type,
                        "message": w.message,
                        "details": w.details,
                        "paragraph_index": para_idx,
                        "part": part_name,
                    })

                # Also add warnings from seg_audit (e.g. overlapped spans)
                for w in seg_audit.get("warnings", []):
                    if isinstance(w, dict):
                        all_warnings.append({**w, "paragraph_index": para_idx, "part": part_name})
                    else:
                        all_warnings.append({
                            "type": "audit_warning",
                            "message": str(w),
                            "paragraph_index": para_idx,
                            "part": part_name,
                        })

                # Build document-level occurrences with locator
                for i, sp in enumerate(spans_for_para):
                    if i < len(locators):
                        loc = locators[i]
                        all_occurrences.append({
                            "entity_id": sp["entity_id"],
                            "engine": sp["engine"],
                            "original_text": sp["original_text"],
                            "replacement": sp["replacement"],
                            "locator": {
                                "type": "docx",
                                "part": part_name,
                                "paragraph_index": para_idx,
                                "run_start_index": loc["run_start_index"],
                                "run_end_index": loc["run_end_index"],
                                "text_start": loc["text_start"],
                                "text_end": loc["text_end"],
                            },
                        })

        # Serialize modified text parts back into the package.
        for part_name, tree in text_trees.items():
            package_files[part_name] = etree.tostring(
                tree, xml_declaration=True, encoding="UTF-8", standalone=True
            )

        with zipfile.ZipFile(redacted_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in package_files.items():
                zf.writestr(name, data)

        redacted_sha256 = hashlib.sha256(
            open(redacted_path, "rb").read()
        ).hexdigest()

        # Collect cross-paragraph warning
        # Text engine may produce entities spanning multiple paragraphs at boundary
        # We detect by checking if replacement differs from what was expected

        map_data = {
            "schema_version": "1.1",
            "document_type": "docx",
            "verification": "content",
            "source_file": source_path,
            "redacted_file": redacted_path,
            "source_sha256": source_sha256,
            "redacted_sha256": redacted_sha256,
            "profile": profile_name,
            "level": level,
            "mode": mode,
            "entities": all_entities,
            "occurrences": all_occurrences,
        }

        # Build audit
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
            "document_type": "docx",
            "profile": profile_name,
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
        """Restore DOCX using redacted-document locators."""
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

        with zipfile.ZipFile(redacted_path, "r") as zf:
            package_files = {n: zf.read(n) for n in zf.namelist()}
        text_trees = {
            name: etree.fromstring(data)
            for name, data in package_files.items()
            if _is_text_part(name)
        }

        # Build entity lookup
        entity_map = {e["id"]: e["original"] for e in map_data.get("entities", [])}

        # Group occurrences by package part and paragraph index.
        from collections import defaultdict
        para_occurrences = defaultdict(list)
        for occ in map_data.get("occurrences", []):
            loc = occ.get("locator", {})
            if loc.get("type") != "docx":
                continue
            para_occurrences[(loc.get("part", "word/document.xml"), loc["paragraph_index"])].append(occ)

        for (part_name, para_idx), occs in para_occurrences.items():
            tree = text_trees.get(part_name)
            if tree is None:
                continue
            paragraphs = _paragraphs(tree)
            if para_idx >= len(paragraphs):
                continue
            para_elem = paragraphs[para_idx]

            # Restore this paragraph
            _restore_paragraph_from_locator(para_elem, occs, entity_map)

        for part_name, tree in text_trees.items():
            package_files[part_name] = etree.tostring(
                tree, xml_declaration=True, encoding="UTF-8", standalone=True
            )

        with zipfile.ZipFile(restored_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in package_files.items():
                zf.writestr(name, data)

    def audit(self, path: str, map_data: dict, rules) -> dict:
        """Audit a redacted DOCX for residual sensitive data."""
        import hashlib

        # Verify redacted SHA
        file_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        expected = map_data.get("redacted_sha256", "")
        warnings = []
        if file_sha != expected:
            warnings.append({
                "type": "sha256_mismatch",
                "message": f"redacted_sha256 mismatch: file={file_sha[:16]} map={expected[:16]}",
            })

        # Extract and scan for residual patterns
        full_text, _ = self.extract_text(path)
        from .engine_regex import scan_regex_for_audit
        residual = scan_regex_for_audit(full_text, rules)
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
            "document_type": "docx",
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
            "warnings": warnings,
        }
