"""CLI entry point for legal-desens."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .audit import audit
from .io import read_text, write_text
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


def _txt_redact_fn(text, rules, source_sha256, mode, level, model_dir):
    """Wrapper to call text redact engine with standard signature."""
    return redact(text, rules, source_sha256, mode, level, model_dir)


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


def _cmd_redact(args: argparse.Namespace) -> int:
    rules = load_rules(args.rules)
    fmt = _detect_format(args.input)

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
            sys.stdout.write(redacted_text)

        if args.map:
            with open(args.map, "w", encoding="utf-8") as f:
                json.dump(map_data, f, ensure_ascii=False, indent=2)

        if args.audit:
            audit_result = audit(redacted_text, map_data, rules)
            with open(args.audit, "w", encoding="utf-8") as f:
                json.dump(audit_result, f, ensure_ascii=False, indent=2)

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
                redact_fn=_txt_redact_fn,
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
                redact_fn=_txt_redact_fn,
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
            sys.stdout.write(restored_text)

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
    """Redact-scan: OCR → redact → irreversible derivative (Markdown)."""
    from .scan import scan_redact

    rules = load_rules(args.rules)

    try:
        redacted_text, map_data, audit_data, ocr_meta = scan_redact(
            image_path=args.input,
            rules=rules,
            ocr_engine=args.ocr,
            mode="regex-only" if args.regex_only else "regex+ner",
            level=args.level,
            model_dir=args.model_dir,
        )
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(redacted_text, encoding="utf-8")
    else:
        sys.stdout.write(redacted_text)

    if args.map:
        with open(args.map, "w", encoding="utf-8") as f:
            json.dump(map_data, f, ensure_ascii=False, indent=2)

    if args.audit:
        with open(args.audit, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, ensure_ascii=False, indent=2)

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
        sys.stdout.write(md_text)

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

    # A: Core reversible formats
    if fmt in ("txt", "md"):
        tf = read_text(args.input)
        result = audit(tf.text, map_data, rules)

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
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")

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


def _cmd_ner_spans(args: argparse.Namespace) -> int:
    from .engine.ner import NEREngine

    try:
        engine = NEREngine(args.model_dir)
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
    p_redact.add_argument("--level", default="strict", choices=["strict"],
                          help="Redaction level (only 'strict' is currently supported)")
    p_redact.add_argument("--regex-only", action="store_true", default=False,
                          help="Use only regex engine (skip NER)")
    p_redact.add_argument("--model-dir", default=None,
                          help="Path to NER model directory")
    p_redact.add_argument("--out", help="Output redacted file")
    p_redact.add_argument("--map", help="Output map JSON file")
    p_redact.add_argument("--audit", help="Output audit JSON file")

    # ── restore ──
    p_restore = sub.add_parser("restore", help="Restore redacted document using map")
    p_restore.add_argument("input", help="Redacted file (.txt, .md, .csv, .docx, .xlsx)")
    p_restore.add_argument("--map", required=True, help="Map JSON file")
    p_restore.add_argument("--out", help="Output restored file")

    # ── audit ──
    p_audit = sub.add_parser("audit", help="Audit redacted document for residual sensitive data")
    p_audit.add_argument("input", help="Redacted file (.txt, .md, .csv, .docx, .xlsx)")
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
        help="OCR image/scanned doc → redact → irreversible derivative (Markdown)",
    )
    p_scan.add_argument("input", help="Input image file (.png, .jpg, .jpeg, .tiff, .bmp) or scanned PDF")
    p_scan.add_argument("--ocr", default="rapidocr", choices=["rapidocr"],
                        help="OCR engine to use (default: rapidocr)")
    p_scan.add_argument("--level", default="strict", choices=["strict"],
                        help="Redaction level (only 'strict' is currently supported)")
    p_scan.add_argument("--regex-only", action="store_true", default=False,
                        help="Use only regex engine (skip NER)")
    p_scan.add_argument("--model-dir", default=None,
                        help="Path to NER model directory")
    p_scan.add_argument("--out", help="Output redacted Markdown file")
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
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
