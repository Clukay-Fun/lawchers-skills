"""CLI entry point for legal-desens."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, TextIO

from .audit import audit
from .io import read_text, write_text
from .profile import load_profile, resolve_profile_name
from .redact import redact
from .restore import restore
from .rules import load_rules


# Format categories for decision table routing
# A: Core reversible (byte or content level)
# B: Irreversible derivatives via 009 scan/parse pipeline
# C: Unsupported, with conversion guidance
_FORMAT_A_REVERSIBLE = {".txt", ".md", ".csv", ".docx", ".xlsx"}
_FORMAT_B_IRREVERSIBLE = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".pptx", ".html"}
_FORMAT_C_UNSUPPORTED = {".doc", ".xls", ".wps", ".et", ".dps", ".pages", ".numbers", ".key"}

_C_CONVERT_MSG = (
    "Unsupported format: {ext}. "
    "Please convert to a supported format first:\n"
    "  - .doc → .docx\n"
    "  - .xls → .xlsx\n"
    "  - .wps/.et/.dps → .docx/.xlsx/.pptx or PDF/image\n"
    "  - .pages/.numbers/.key → .docx/.xlsx/.pptx or PDF/image\n"
    "Then run the command again on the converted file."
)


def _write_stdout_utf8(text: str, stdout: TextIO | None = None) -> None:
    """Write redirected stdout as UTF-8 on Windows and other legacy locales."""
    stream = stdout or sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
        return

    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _detect_format(path: str) -> str:
    """Detect document format from file extension."""
    ext = Path(path).suffix.lower()
    if ext in _FORMAT_A_REVERSIBLE:
        return ext.lstrip(".")
    elif ext in _FORMAT_B_IRREVERSIBLE:
        return "irreversible"
    elif ext in _FORMAT_C_UNSUPPORTED:
        return "unsupported"
    else:
        return "unknown"


def _get_adapter(fmt: str):
    """Get the appropriate document adapter."""
    if fmt == "docx":
        from .adapters.docx_adapter import DOCXAdapter
        return DOCXAdapter()
    elif fmt == "xlsx":
        from .adapters.xlsx_adapter import XLSXAdapter
        return XLSXAdapter()
    elif fmt == "csv":
        from .adapters.csv_adapter import csv_redact, csv_restore, csv_audit
        return type("CSVAdapter", (), {
            "redact": staticmethod(csv_redact),
            "restore": staticmethod(csv_restore),
            "audit": staticmethod(csv_audit),
        })()
    else:
        return None


def _make_txt_redact_fn(profile=None, allowlist=None, denylist=None):
    """Create a text redact function with profile, allowlist, and denylist bound."""
    def _txt_redact_fn(text, rules, source_sha256, mode, level, model_dir):
        return redact(
            text, rules, source_sha256, mode, level, model_dir,
            profile=profile, allowlist=allowlist, denylist=denylist,
        )
    _txt_redact_fn._profile = profile
    _txt_redact_fn._profile_name = profile.name if profile else None
    _txt_redact_fn._allowlist = allowlist
    _txt_redact_fn._denylist = denylist
    return _txt_redact_fn


def _load_map_file(path: str) -> dict:
    """Load a map JSON file and raise ValueError with user-facing messages."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError(f"Map file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Map file is not valid JSON: {path} ({e})")
    except OSError as e:
        raise ValueError(f"Unable to read map file: {path} ({e})")


def _apply_decisions(args: argparse.Namespace, fmt: str, decisions_file: str) -> int:
    """Apply reviewed decisions directly to a document.

    Bypasses auto-detection (regex/NER). Only positions specified in
    decisions are modified. 'keep' decisions are never touched.
    """
    from .decisions_apply import apply_decisions_text, apply_decisions_docx, _load_decisions, _load_source_map

    try:
        decisions = _load_decisions(decisions_file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading decisions: {e}", file=sys.stderr)
        return 1

    # Load source map to get blocks
    source_map_file = getattr(args, "source_map", None)
    if not source_map_file:
        print("Error: --source-map is required with --decisions", file=sys.stderr)
        return 1

    try:
        source_map = _load_source_map(source_map_file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading source map: {e}", file=sys.stderr)
        return 1

    blocks = source_map.get("blocks", [])
    if not blocks:
        print("Error: source map has no blocks", file=sys.stderr)
        return 1

    if not args.out:
        print("Error: --out is required with --decisions", file=sys.stderr)
        return 1

    # Apply decisions based on format
    if fmt in ("txt", "md"):
        try:
            map_data = apply_decisions_text(args.input, args.out, decisions, blocks)
        except Exception as e:
            print(f"Error applying decisions to text: {e}", file=sys.stderr)
            return 1

    elif fmt == "docx":
        try:
            map_data = apply_decisions_docx(args.input, args.out, decisions, blocks)
        except Exception as e:
            print(f"Error applying decisions to DOCX: {e}", file=sys.stderr)
            return 1

    elif fmt == "irreversible":
        ext = Path(args.input).suffix.lower()
        # P0: Block all PDF decisions until coordinate-based implementation exists
        # - scan PDF: no text layer, needs polygon pixel redaction
        # - text PDF: search_for matches ALL occurrences, not just decision position
        print(f"Error: PDF decisions export not yet implemented.\n"
              f"  Scan PDF requires polygon-based pixel redaction.\n"
              f"  Text PDF requires per-decision coordinate mapping.\n"
              f"  Use the legacy /api/export/redacted endpoint for PDF files.",
              file=sys.stderr)
        return 1
    else:
        print(f"Error: format {fmt} not supported for decisions export", file=sys.stderr)
        return 1

    # Write map
    if args.map:
        with open(args.map, "w", encoding="utf-8") as f:
            json.dump(map_data, f, ensure_ascii=False, indent=2)

    # P0: Real residual verification — verify every redact decision was applied
    residual_findings = []
    if fmt in ("txt", "md"):
        from .io import read_text
        exported_text = read_text(args.out).text
        for d in decisions:
            if d.get("action") != "redact":
                continue
            block_id = d.get("blockId")
            block = next((b for b in blocks if b["id"] == block_id), None)
            if not block:
                continue
            block_offset = block.get("char_offset", 0)
            doc_start = block_offset + d.get("start", 0)
            doc_end = block_offset + d.get("end", 0)
            original = block["text"][d.get("start", 0):d.get("end", 0)]
            if not original:
                continue
            # Check if original text still appears at the expected position
            exported_segment = exported_text[doc_start:doc_end]
            if exported_segment == original:
                residual_findings.append({
                    "type": "decision_not_applied",
                    "decision_id": d.get("id"),
                    "position": f"[{doc_start}:{doc_end}]",
                    "text_preview": original[:20],
                })
    elif fmt == "docx":
        # Verify DOCX by extracting text and checking each decision position
        from .adapters.docx_adapter import DOCXAdapter
        adapter = DOCXAdapter()
        exported_text, _ = adapter.extract_text(args.out)
        # Build block offset map from source map
        for d in decisions:
            if d.get("action") != "redact":
                continue
            block_id = d.get("blockId")
            block = next((b for b in blocks if b["id"] == block_id), None)
            if not block:
                continue
            block_offset = block.get("char_offset", 0)
            doc_start = block_offset + d.get("start", 0)
            doc_end = block_offset + d.get("end", 0)
            original = block["text"][d.get("start", 0):d.get("end", 0)]
            if not original or len(original) < 2:
                continue
            # Check if original text still appears at the position in exported DOCX
            if doc_end <= len(exported_text):
                exported_segment = exported_text[doc_start:doc_end]
                if exported_segment == original:
                    residual_findings.append({
                        "type": "decision_not_applied",
                        "decision_id": d.get("id"),
                        "text_preview": original[:20],
                    })

    residual_passed = len(residual_findings) == 0

    # Write audit
    if args.audit:
        audit_data = {
            "schema_version": "1.0",
            "summary": {
                "total_entities": len(map_data.get("entities", [])),
                "total_occurrences": len(map_data.get("occurrences", [])),
            },
            "residual_scan": {
                "passed": residual_passed,
                "findings": residual_findings,
                "method": "position_verification",
            },
            "export_mode": "decisions",
        }
        with open(args.audit, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, ensure_ascii=False, indent=2)

    if not residual_passed:
        # Clean up failed export
        Path(args.out).unlink(missing_ok=True)
        print(f"Error: {len(residual_findings)} redact decisions were not applied. Export rejected.", file=sys.stderr)
        for f in residual_findings[:3]:
            print(f"  - {f.get('type')}: '{f.get('text_preview')}' at {f.get('position', '?')}", file=sys.stderr)
        return 1

    n_redact = sum(1 for d in decisions if d.get("action") == "redact")
    print(f"Decisions export complete: {n_redact} positions redacted, mode={fmt}", file=sys.stderr)
    return 0


def _apply_decisions_pdf(pdf_path: str, output_path: str, decisions: List[dict], blocks: List[dict]) -> dict:
    """Apply decisions to a text-layer PDF using fitz."""
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF required for PDF decisions export: pip install legal-desens[pdf]")

    # Group decisions by page
    blocks_by_id = {b["id"]: b for b in blocks}
    page_decisions: Dict[int, List[dict]] = {}

    for d in decisions:
        if d.get("action") != "redact":
            continue
        locator = d.get("sourceLocator", {})
        page_num = locator.get("page")
        if page_num is None:
            # Try to find page from block
            block = blocks_by_id.get(d.get("blockId"))
            if block:
                page_num = block.get("sourceLocator", {}).get("page")
        if page_num is not None:
            page_decisions.setdefault(page_num, []).append(d)

    doc = fitz.open(pdf_path)
    entities = []
    occurrences = []

    for page_number, page_dcs in page_decisions.items():
        if page_number < 1 or page_number > len(doc):
            continue
        page = doc[page_number - 1]
        page_text = page.get_text()
        if not page_text.strip():
            continue

        for d in page_dcs:
            block = blocks_by_id.get(d.get("blockId"))
            if not block:
                continue

            original = block["text"][d["start"]:d["end"]]
            if not original:
                continue

            # Search for the text on this page
            rects = page.search_for(original)
            for rect in rects:
                page.add_redact_annot(rect, fill=(1, 1, 1))

            entity_type = d.get("entityType", "")
            replacement = _mask_value(original, entity_type)

            entity_id = f"decision_{d.get('id', len(entities))}"
            entities.append({
                "id": entity_id,
                "entity_type": entity_type or "MANUAL",
                "original": original,
                "replacement": replacement,
                "engines": ["decision"],
            })

            for rect in rects:
                occurrences.append({
                    "entity_id": entity_id,
                    "engine": "decision",
                    "page": page_number,
                    "rectangles": [list(rect)],
                })

        if page_dcs:
            page.apply_redactions()
            # Insert replacement text
            for d in page_dcs:
                block = blocks_by_id.get(d.get("blockId"))
                if not block:
                    continue
                original = block["text"][d["start"]:d["end"]]
                entity_type = d.get("entityType", "")
                replacement = _mask_value(original, entity_type)
                rects = page.search_for(original)
                for rect in rects:
                    page.insert_text(
                        (rect.x0, rect.y1 - 2),
                        replacement,
                        fontname="china-s",
                        fontsize=max(4, min(10, rect.height * 0.75)),
                        color=(0, 0, 0),
                    )

    doc.save(output_path, garbage=4, clean=True, deflate=True)
    doc.close()

    source_sha = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    return {
        "schema_version": "1.0",
        "source_file": Path(pdf_path).name,
        "redacted_file": Path(output_path).name,
        "source_sha256": source_sha,
        "entities": entities,
        "occurrences": occurrences,
    }


def _cmd_redact(args: argparse.Namespace) -> int:
    from .engine.allowlist import load_allowlist

    rules = load_rules(args.rules)
    fmt = _detect_format(args.input)

    # ── decisions mode: apply reviewed decisions directly, skip auto-detection ──
    decisions_file = getattr(args, "decisions", None)
    if decisions_file:
        return _apply_decisions(args, fmt, decisions_file)

    # Resolve profile
    profile_name = resolve_profile_name(
        getattr(args, "profile", None),
        args.level,
    )

    # Load entity_policy if provided
    entity_policy_file = getattr(args, "entity_policy", None)

    try:
        profile = load_profile(
            profile_name,
            entity_policy_file=entity_policy_file,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Load allowlist and denylist
    allowlist_file = getattr(args, "allowlist", None)
    denylist_file = getattr(args, "denylist", None)

    allowlist = load_allowlist(
        builtin=True,
        case_file=allowlist_file,
    ) if allowlist_file else load_allowlist(builtin=True)

    denylist = set()
    if denylist_file:
        try:
            with open(denylist_file, "r", encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term and not line.startswith("#"):
                        denylist.add(term)
        except FileNotFoundError:
            print(f"Warning: denylist file not found: {denylist_file}", file=sys.stderr)

    # A: Core reversible formats
    if fmt in ("txt", "md"):
        # Original text-based redaction (txt and md share byte-safe logic)
        tf = read_text(args.input)
        source_sha = tf.sha256

        try:
            redacted_text, map_data, audit_data = redact(
                text=tf.text,
                rules=rules,
                source_sha256=source_sha,
                mode="regex-only" if args.regex_only else "regex+ner",
                level=args.level,
                model_dir=args.model_dir,
                profile=profile,
                allowlist=allowlist,
                denylist=denylist,
            )
        except (RuntimeError, FileNotFoundError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        redacted_bytes = redacted_text.encode("utf-8")
        if tf.has_bom:
            redacted_bytes = b"\xef\xbb\xbf" + redacted_bytes
        redacted_sha = hashlib.sha256(redacted_bytes).hexdigest()

        map_data["source_file"] = str(Path(args.input).name)
        map_data["redacted_file"] = str(Path(args.out).name) if args.out else ""
        map_data["redacted_sha256"] = redacted_sha
        map_data["byte_metadata"] = {
            "encoding": "utf-8-sig" if tf.has_bom else "utf-8",
            "has_bom": tf.has_bom,
            "newline": tf.newline,
            "has_trailing_newline": tf.has_trailing_newline,
        }

        if args.out:
            write_text(args.out, redacted_text, tf)
        else:
            _write_stdout_utf8(redacted_text)

        if args.map:
            with open(args.map, "w", encoding="utf-8") as f:
                json.dump(map_data, f, ensure_ascii=False, indent=2)

        if args.audit:
            with open(args.audit, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

        return 0

    elif fmt == "csv":
        from .adapters.csv_adapter import csv_redact
        if not args.out:
            print("Error: --out is required for CSV redaction", file=sys.stderr)
            return 1

        try:
            map_data, audit_data = csv_redact(
                source_path=args.input,
                redacted_path=args.out,
                redact_fn=_make_txt_redact_fn(profile, allowlist, denylist),
                rules=rules,
                mode="regex-only" if args.regex_only else "regex+ner",
                level=args.level,
                model_dir=args.model_dir,
            )
        except (RuntimeError, FileNotFoundError, NotImplementedError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.map:
            with open(args.map, "w", encoding="utf-8") as f:
                json.dump(map_data, f, ensure_ascii=False, indent=2)

        if args.audit:
            with open(args.audit, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

        return 0

    elif fmt in ("docx", "xlsx"):
        adapter = _get_adapter(fmt)
        if not args.out:
            print("Error: --out is required for document redaction", file=sys.stderr)
            return 1

        try:
            map_data, audit_data = adapter.redact(
                source_path=args.input,
                redacted_path=args.out,
                redact_fn=_make_txt_redact_fn(profile, allowlist, denylist),
                rules=rules,
                mode="regex-only" if args.regex_only else "regex+ner",
                level=args.level,
                model_dir=args.model_dir,
            )
        except (RuntimeError, FileNotFoundError, NotImplementedError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.map:
            with open(args.map, "w", encoding="utf-8") as f:
                json.dump(map_data, f, ensure_ascii=False, indent=2)

        if args.audit:
            with open(args.audit, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

        return 0

    # B: Irreversible formats → route to 009 scan/parse
    elif fmt == "irreversible":
        ext = Path(args.input).suffix.lower()
        if ext == ".pdf" and args.out and Path(args.out).suffix.lower() == ".pdf":
            from .adapters.pdf_adapter import redact_text_pdf
            try:
                map_data, audit_data = redact_text_pdf(
                    source_path=args.input,
                    redacted_path=args.out,
                    rules=rules,
                    redact_fn=_make_txt_redact_fn(profile, allowlist, denylist),
                    mode="regex-only" if args.regex_only else "regex+ner",
                    level=args.level,
                    model_dir=args.model_dir,
                )
            except (ImportError, RuntimeError, ValueError, FileNotFoundError) as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            if args.map:
                with open(args.map, "w", encoding="utf-8") as f:
                    json.dump(map_data, f, ensure_ascii=False, indent=2)
            if args.audit:
                with open(args.audit, "w", encoding="utf-8") as f:
                    json.dump(audit_data, f, ensure_ascii=False, indent=2)
            return 0
        print(
            f"Error: {ext} is an irreversible format.\n"
            "Use 'redact-scan' for images/scanned docs (requires [ocr] extra),\n"
            "or 'parse' for complex documents (requires [parse-docling] extra).\n"
            "These produce derivative copies only — restoration is not possible.",
            file=sys.stderr,
        )
        return 1

    # C: Unsupported formats → conversion guidance
    elif fmt == "unsupported":
        ext = Path(args.input).suffix.lower()
        print(_C_CONVERT_MSG.format(ext=ext), file=sys.stderr)
        return 1

    # Unknown format
    else:
        ext = Path(args.input).suffix.lower()
        print(f"Error: Unknown file format: {ext}", file=sys.stderr)
        return 1


def _cmd_restore(args: argparse.Namespace) -> int:
    try:
        map_data = _load_map_file(args.map)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    fmt = _detect_format(args.input)

    # A: Core reversible formats
    if fmt in ("txt", "md"):
        # Original text-based restoration (txt and md share byte-safe logic)
        tf = read_text(args.input)
        redacted_sha = tf.sha256

        try:
            restored_text = restore(
                redacted_text=tf.text,
                map_data=map_data,
                redacted_file_sha256=redacted_sha,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.out:
            write_text(args.out, restored_text, tf)
        else:
            _write_stdout_utf8(restored_text)

        restored_bytes = restored_text.encode("utf-8")
        if tf.has_bom:
            restored_bytes = b"\xef\xbb\xbf" + restored_bytes
        restored_sha = hashlib.sha256(restored_bytes).hexdigest()
        source_sha = map_data.get("source_sha256", "")

        if restored_sha == source_sha:
            print("Restoration successful: SHA-256 matches source.", file=sys.stderr)
        else:
            print(
                f"Warning: SHA-256 mismatch after restoration. "
                f"restored={restored_sha[:16]}... source={source_sha[:16]}...",
                file=sys.stderr,
            )
            return 1

        return 0

    elif fmt == "csv":
        from .adapters.csv_adapter import csv_restore
        if not args.out:
            print("Error: --out is required for CSV restoration", file=sys.stderr)
            return 1

        try:
            csv_restore(
                redacted_path=args.input,
                restored_path=args.out,
                map_data=map_data,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        print("Restoration successful: SHA-256 matches source.", file=sys.stderr)
        return 0

    elif fmt in ("docx", "xlsx"):
        adapter = _get_adapter(fmt)
        if not args.out:
            print("Error: --out is required for document restoration", file=sys.stderr)
            return 1

        try:
            adapter.restore(
                redacted_path=args.input,
                restored_path=args.out,
                map_data=map_data,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except NotImplementedError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        # Content-level verification for DOCX/XLSX
        source_path = map_data.get("source_file", "")
        if source_path and Path(source_path).exists():
            full_text_source, _ = adapter.extract_text(source_path)
            full_text_restored, _ = adapter.extract_text(args.out)
            if full_text_source == full_text_restored:
                print("Restoration successful: content matches source.", file=sys.stderr)
            else:
                print("Warning: content mismatch after restoration.", file=sys.stderr)
                return 1
        else:
            print("Restoration completed. Source file not available for content verification.", file=sys.stderr)

        return 0

    # B: Irreversible formats → no restore
    elif fmt == "irreversible":
        ext = Path(args.input).suffix.lower()
        print(
            f"Error: {ext} is an irreversible format.\n"
            "Restoration is not possible for scan/parse derivatives.\n"
            "These formats produce derivative copies only.",
            file=sys.stderr,
        )
        return 1

    # C: Unsupported formats → conversion guidance
    elif fmt == "unsupported":
        ext = Path(args.input).suffix.lower()
        print(_C_CONVERT_MSG.format(ext=ext), file=sys.stderr)
        return 1

    # Unknown format
    else:
        ext = Path(args.input).suffix.lower()
        print(f"Error: Unknown file format: {ext}", file=sys.stderr)
        return 1


def _cmd_redact_scan(args: argparse.Namespace) -> int:
    """Redact-scan: OCR → redact → Markdown and optional format-preserving output."""
    from .engine.allowlist import load_allowlist
    from .scan import scan_redact, scan_redact_preserve_format

    rules = load_rules(args.rules)

    # Resolve profile
    profile_name = resolve_profile_name(
        getattr(args, "profile", None),
        args.level,
    )

    # Load entity_policy if provided
    entity_policy_file = getattr(args, "entity_policy", None)

    try:
        profile = load_profile(
            profile_name,
            entity_policy_file=entity_policy_file,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Load allowlist and denylist
    allowlist_file = getattr(args, "allowlist", None)
    denylist_file = getattr(args, "denylist", None)

    allowlist = load_allowlist(
        builtin=True,
        case_file=allowlist_file,
    ) if allowlist_file else load_allowlist(builtin=True)

    denylist = set()
    if denylist_file:
        try:
            with open(denylist_file, "r", encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term and not line.startswith("#"):
                        denylist.add(term)
        except FileNotFoundError:
            print(f"Warning: denylist file not found: {denylist_file}", file=sys.stderr)

    try:
        input_suffix = Path(args.input).suffix.lower()
        output_suffix = Path(args.out).suffix.lower() if args.out else ""
        preserve_format = bool(args.out and output_suffix == input_suffix)

        if preserve_format:
            markdown_path = args.md_out or str(
                Path(args.out).with_name(Path(args.out).stem + ".intermediate.md")
            )
            map_data, audit_data, ocr_meta = scan_redact_preserve_format(
                source_path=args.input,
                output_path=args.out,
                markdown_path=markdown_path,
                rules=rules,
                ocr_engine=args.ocr,
                mode="regex-only" if args.regex_only else "regex+ner",
                level=args.level,
                model_dir=args.model_dir,
                profile=profile,
                allowlist=allowlist,
                denylist=denylist,
            )
            redacted_text = None
        else:
            redacted_text, map_data, audit_data, ocr_meta = scan_redact(
            image_path=args.input,
            rules=rules,
            ocr_engine=args.ocr,
            mode="regex-only" if args.regex_only else "regex+ner",
            level=args.level,
            model_dir=args.model_dir,
            profile=profile,
            allowlist=allowlist,
            denylist=denylist,
            )
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.out and redacted_text is not None:
        Path(args.out).write_text(redacted_text, encoding="utf-8")
    elif not args.out and redacted_text is not None:
        _write_stdout_utf8(redacted_text)

    if args.map:
        with open(args.map, "w", encoding="utf-8") as f:
            json.dump(map_data, f, ensure_ascii=False, indent=2)

    if args.audit:
        with open(args.audit, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, ensure_ascii=False, indent=2)

    verification = audit_data.get("verification")
    if isinstance(verification, dict) and verification.get("passed") is False:
        failed_pages = verification.get("failed_pages", [])
        print(
            "Error: Pixel redaction verification failed"
            + (f" on page(s): {failed_pages}" if failed_pages else "")
            + ". Audit and quarantined incomplete output were preserved.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Scan complete: {ocr_meta['total_lines']} lines OCR'd, "
        f"{ocr_meta['low_confidence_lines']} low-confidence warnings, "
        f"pipeline=scan irreversible best_effort=true",
        file=sys.stderr,
    )
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    """Parse: document → Markdown/JSON using Docling (requires parse-docling extra)."""
    try:
        from .engine.ocr import run_docling_parse
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        md_text, metadata = run_docling_parse(args.input)
    except (RuntimeError, FileNotFoundError, ValueError, ImportError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(md_text, encoding="utf-8")
        print(f"Parsed: {args.out}", file=sys.stderr)
    else:
        _write_stdout_utf8(md_text)

    if args.meta:
        with open(args.meta, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    try:
        map_data = _load_map_file(args.map)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    rules = load_rules(args.rules)
    fmt = _detect_format(args.input)

    # Resolve profile (from map or CLI)
    profile_name = getattr(args, "profile", None) or map_data.get("profile", "labor")
    try:
        profile = load_profile(profile_name)
    except FileNotFoundError:
        profile = None

    # A: Core reversible formats
    if fmt in ("txt", "md"):
        tf = read_text(args.input)
        result = audit(tf.text, map_data, rules, profile=profile)

    elif fmt == "csv":
        from .adapters.csv_adapter import csv_audit
        result = csv_audit(args.input, map_data, rules)

    elif fmt in ("docx", "xlsx"):
        adapter = _get_adapter(fmt)
        if adapter is None:
            print(f"Error: unsupported format {fmt}", file=sys.stderr)
            return 1
        result = adapter.audit(args.input, map_data, rules)

    # B: Irreversible formats
    elif fmt == "irreversible":
        ext = Path(args.input).suffix.lower()
        print(
            f"Error: {ext} is an irreversible format.\n"
            "Use the map file from redact-scan/parse for audit information.\n"
            "These formats produce derivative copies only.",
            file=sys.stderr,
        )
        return 1

    # C: Unsupported formats
    elif fmt == "unsupported":
        ext = Path(args.input).suffix.lower()
        print(_C_CONVERT_MSG.format(ext=ext), file=sys.stderr)
        return 1

    # Unknown format
    else:
        ext = Path(args.input).suffix.lower()
        print(f"Error: Unknown file format: {ext}", file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    else:
        _write_stdout_utf8(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    return 0


def _cmd_install_model(args: argparse.Namespace) -> int:
    from .model_install import InstallError, install_model

    try:
        manifest = install_model(
            from_app=args.from_app,
            src=args.src,
            url=args.url,
            sha256=args.sha256,
            force=args.force,
            target=args.target,
        )
    except InstallError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Model installed to {manifest['path']}", file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _cmd_ner_inspect(args: argparse.Namespace) -> int:
    from .engine.ner import inspect_ner

    try:
        info = inspect_ner(args.model_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def _cmd_prepare(args: argparse.Namespace) -> int:
    """Prepare: document → preview Markdown + manifest + source map for review."""
    from .engine.allowlist import load_allowlist
    from .prepare import prepare

    rules = load_rules(args.rules)

    # Resolve profile
    profile_name = resolve_profile_name(
        getattr(args, "profile", None),
        getattr(args, "level", "strict"),
    )
    try:
        profile = load_profile(profile_name)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    mode = "regex-only" if getattr(args, "regex_only", False) else "regex+ner"

    try:
        manifest, preview_md, source_map_json = prepare(
            source_path=args.input,
            rules=rules,
            level=getattr(args, "level", "strict"),
            mode=mode,
            model_dir=getattr(args, "model_dir", None),
            profile=profile,
        )
    except (RuntimeError, FileNotFoundError, ValueError, ImportError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Write outputs
    if args.preview_md:
        Path(args.preview_md).write_text(preview_md, encoding="utf-8")
        print(f"Preview: {args.preview_md}", file=sys.stderr)

    if args.manifest:
        with open(args.manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"Manifest: {args.manifest}", file=sys.stderr)

    if args.map:
        Path(args.map).write_text(source_map_json, encoding="utf-8")
        print(f"Source map: {args.map}", file=sys.stderr)

    if not args.preview_md and not args.manifest and not args.map:
        # Default: output manifest to stdout
        print(json.dumps(manifest, ensure_ascii=False, indent=2))

    n_candidates = len(manifest.get("candidates", []))
    n_blocks = len(manifest.get("blocks", []))
    doc_kind = manifest.get("documentKind", "unknown")
    print(
        f"Prepare complete: {doc_kind}, {n_blocks} blocks, "
        f"{n_candidates} candidates detected, mode={mode}",
        file=sys.stderr,
    )
    return 0


def _cmd_batch_redact_case(args: argparse.Namespace) -> int:
    """Batch case redaction orchestrator."""
    from .batch import BatchError, batch_redact_case

    try:
        rc = batch_redact_case(
            input_dir=args.input,
            out_dir=args.out,
            profile_name=getattr(args, "profile", None) or "labor",
            allowlist_file=getattr(args, "allowlist", None),
            denylist_file=getattr(args, "denylist", None),
            entity_policy_file=getattr(args, "entity_policy", None),
            cleanup=getattr(args, "cleanup", "none"),
            confirm_delete=getattr(args, "confirm_delete", False),
            model_dir=getattr(args, "model_dir", None),
            rules_path=args.rules,
            regex_only=getattr(args, "regex_only", False),
        )
        return rc
    except BatchError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def _cmd_ner_spans(args: argparse.Namespace) -> int:
    from .engine.ner import get_ner_engine_instance

    try:
        engine = get_ner_engine_instance(args.model_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    tf = read_text(args.input)
    spans, warnings = engine.scan(tf.text)

    result = {
        "input_file": str(Path(args.input).name),
        "text_length": len(tf.text),
        "spans": [
            {
                "entity_type": s.entity_type,
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "engine": s.engine,
                "priority": s.priority,
            }
            for s in spans
        ],
        "warnings": warnings,
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="legal-desens",
        description="Legal document text desensitization CLI",
    )
    parser.add_argument(
        "--rules", default=None,
        help="Path to rules.json (default: rules/rules.json in project root)"
    )

    sub = parser.add_subparsers(dest="command")

    # ── redact ──
    p_redact = sub.add_parser("redact", help="Redact sensitive information from document")
    p_redact.add_argument("input", help="Input file (.txt, .md, .csv, .docx, .xlsx)")
    p_redact.add_argument("--profile", default=None, choices=["labor", "strict"],
                          help="Redaction profile (default: labor)")
    p_redact.add_argument("--level", default=None, choices=["labor", "strict"],
                          help="Redaction level — maps to profile (strict→strict, labor→labor)")
    p_redact.add_argument("--regex-only", action="store_true", default=False,
                          help="Use only regex engine (skip NER)")
    p_redact.add_argument("--model-dir", default=None,
                          help="Path to NER model directory")
    p_redact.add_argument("--allowlist", default=None,
                          help="Path to case-specific allowlist file (one term per line, local, not in git)")
    p_redact.add_argument("--denylist", default=None,
                          help="Path to case-specific denylist file (one term per line, local, not in git)")
    p_redact.add_argument("--entity-policy", default=None,
                          help="Path to entity_policy JSON file (local, not in git)")
    p_redact.add_argument("--out", help="Output redacted file")
    p_redact.add_argument("--map", help="Output map JSON file")
    p_redact.add_argument("--audit", help="Output audit JSON file")
    p_redact.add_argument("--decisions", default=None,
                          help="Path to decisions JSON file (bypasses auto-detection)")
    p_redact.add_argument("--source-map", default=None,
                          help="Path to source-map JSON from prepare (required with --decisions)")

    # ── restore ──
    p_restore = sub.add_parser("restore", help="Restore redacted document using map")
    p_restore.add_argument("input", help="Redacted file (.txt, .md, .csv, .docx, .xlsx)")
    p_restore.add_argument("--map", required=True, help="Map JSON file")
    p_restore.add_argument("--out", help="Output restored file")

    # ── audit ──
    p_audit = sub.add_parser("audit", help="Audit redacted document for residual sensitive data")
    p_audit.add_argument("input", help="Redacted file (.txt, .md, .csv, .docx, .xlsx)")
    p_audit.add_argument("--profile", default=None, choices=["labor", "strict"],
                         help="Redaction profile for residual scan (default: from map)")
    p_audit.add_argument("--regex-only", action="store_true", default=True,
                         help="Use only regex engine (default: true)")
    p_audit.add_argument("--map", required=True, help="Map JSON file")
    p_audit.add_argument("--out", help="Output audit JSON file")

    # ── install-model ──
    p_install = sub.add_parser("install-model", help="Install NER model to user-level directory")
    install_mode = p_install.add_mutually_exclusive_group()
    install_mode.add_argument("--from-app", action="store_true", default=True,
                              help="Import from local App (default mode)")
    install_mode.add_argument("--url", default=None,
                              help="Download model from URL")
    p_install.add_argument("--sha256", default=None,
                           help="Expected SHA-256 of downloaded archive (required with --url)")
    p_install.add_argument("--src", default=None,
                           help="Source model directory (overrides default App path for --from-app)")
    p_install.add_argument("--force", action="store_true", default=False,
                           help="Force reinstall even if already installed")
    p_install.add_argument("--target", default=None,
                           help="Target installation directory (default: ~/.legal-desens/models/roberta-crf-ner)")
    p_install.add_argument("--out", default=None,
                           help="Write manifest JSON to file")

    # ── ner-inspect ──
    p_ner_inspect = sub.add_parser("ner-inspect", help="Inspect NER model I/O and labels")
    p_ner_inspect.add_argument("--model-dir", default=None,
                               help="Path to NER model directory")

    # ── ner-spans ──
    p_ner_spans = sub.add_parser("ner-spans", help="Run NER on text and output spans as JSON")
    p_ner_spans.add_argument("input", help="Input .txt file")
    p_ner_spans.add_argument("--model-dir", default=None,
                             help="Path to NER model directory")
    p_ner_spans.add_argument("--out", help="Output JSON file")

    # ── redact-scan ──
    p_scan = sub.add_parser(
        "redact-scan",
        help="OCR image/scanned doc → white-box redact → same-format file + Markdown intermediate",
    )
    p_scan.add_argument(
        "input",
        help="Input image file (.png, .jpg, .jpeg, .tiff, .bmp) or PDF (.pdf, requires [pdf] extra)",
    )
    p_scan.add_argument("--ocr", default="rapidocr", choices=["rapidocr"],
                        help="OCR engine to use (default: rapidocr)")
    p_scan.add_argument("--profile", default=None, choices=["labor", "strict"],
                        help="Redaction profile (default: labor)")
    p_scan.add_argument("--level", default=None, choices=["labor", "strict"],
                        help="Redaction level — maps to profile (strict→strict, labor→labor)")
    p_scan.add_argument("--regex-only", action="store_true", default=False,
                        help="Use only regex engine (skip NER)")
    p_scan.add_argument("--model-dir", default=None,
                        help="Path to NER model directory")
    p_scan.add_argument("--allowlist", default=None,
                        help="Path to case-specific allowlist file (one term per line, local, not in git)")
    p_scan.add_argument("--denylist", default=None,
                        help="Path to case-specific denylist file (one term per line, local, not in git)")
    p_scan.add_argument("--entity-policy", default=None,
                        help="Path to entity_policy JSON file (local, not in git)")
    p_scan.add_argument(
        "--out",
        help="Output redacted file; use the input extension for white-box format preservation, or .md for legacy Markdown-only output",
    )
    p_scan.add_argument(
        "--md-out",
        help="Intermediate redacted Markdown path when --out preserves the input format",
    )
    p_scan.add_argument("--map", help="Output map JSON file (with irreversible markers)")
    p_scan.add_argument("--audit", help="Output audit JSON file")

    # ── parse ──
    p_parse = sub.add_parser(
        "parse",
        help="Parse document to Markdown using Docling (requires parse-docling extra)",
    )
    p_parse.add_argument("input", help="Input document file")
    p_parse.add_argument("--parser", default="docling", choices=["docling"],
                         help="Parser engine to use (default: docling)")
    p_parse.add_argument("--out", help="Output Markdown file")
    p_parse.add_argument("--meta", help="Output metadata JSON file")

    # ── batch-redact-case ──
    p_batch = sub.add_parser(
        "batch-redact-case",
        help="Batch case redaction: NER check -> profile + allow/deny -> redact -> report -> gate",
    )
    p_batch.add_argument("--input", required=True,
                         help="Input directory containing case files")
    p_batch.add_argument("--out", required=True,
                         help="Output directory for redacted results")
    p_batch.add_argument("--profile", default=None, choices=["labor", "strict"],
                         help="Redaction profile (default: labor)")
    p_batch.add_argument("--allowlist", default=None,
                         help="Path to case-specific allowlist file")
    p_batch.add_argument("--denylist", default=None,
                         help="Path to case-specific denylist file")
    p_batch.add_argument("--entity-policy", default=None,
                         help="Path to entity_policy JSON file")
    p_batch.add_argument("--cleanup", default="delete", choices=["none", "archive", "delete"],
                         help="Cleanup mode for sensitive work files (default: delete)")
    p_batch.add_argument("--confirm-delete", action="store_true", default=False,
                         help="Required with --cleanup delete to confirm permanent deletion")
    p_batch.add_argument("--model-dir", default=None,
                         help="Path to NER model directory")
    p_batch.add_argument("--regex-only", action="store_true", default=False,
                         help="Explicitly use only regex engine and skip NER pre-check")

    # ── prepare ──
    p_prepare = sub.add_parser(
        "prepare",
        help="Prepare document for review: extract blocks, detect candidates, generate preview",
    )
    p_prepare.add_argument("input", help="Input document (.docx, .pdf, .txt, .md)")
    p_prepare.add_argument("--profile", default=None, choices=["labor", "strict"],
                           help="Redaction profile (default: labor)")
    p_prepare.add_argument("--level", default="strict", choices=["labor", "strict"],
                           help="Redaction level (default: strict)")
    p_prepare.add_argument("--regex-only", action="store_true", default=False,
                           help="Use only regex engine (skip NER)")
    p_prepare.add_argument("--model-dir", default=None,
                           help="Path to NER model directory")
    p_prepare.add_argument("--preview-md", default=None,
                           help="Output preview Markdown file")
    p_prepare.add_argument("--manifest", default=None,
                           help="Output manifest JSON file")
    p_prepare.add_argument("--map", default=None,
                           help="Output source map JSON file")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "redact": _cmd_redact,
        "restore": _cmd_restore,
        "audit": _cmd_audit,
        "install-model": _cmd_install_model,
        "ner-inspect": _cmd_ner_inspect,
        "ner-spans": _cmd_ner_spans,
        "redact-scan": _cmd_redact_scan,
        "parse": _cmd_parse,
        "batch-redact-case": _cmd_batch_redact_case,
        "prepare": _cmd_prepare,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
