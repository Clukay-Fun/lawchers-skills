"""Irreversible scan pipeline: OCR/Parse → Redact → Derive output.

This pipeline produces REDACTED DERIVATIVE COPIES (Markdown/Text).
It is NOT reversible — map marks pipeline:scan / verification:irreversible.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .engine.ocr import OCRResult, run_rapidocr
from .redact import redact
from .rules import Rule


def _source_sha256(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_redact(
    image_path: str,
    rules: List[Rule],
    ocr_engine: str = "rapidocr",
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
    confidence_threshold: float = 0.7,
) -> Tuple[str, dict, dict, dict]:
    """Full irreversible scan pipeline: image → OCR → redact → derivative.

    Args:
        image_path: Path to image file.
        rules: Desensitization rules.
        ocr_engine: OCR engine to use (currently only "rapidocr").
        mode: "regex-only" or "regex+ner".
        level: Redaction level.
        model_dir: Path to NER model (if mode includes ner).
        confidence_threshold: OCR confidence threshold for warnings.

    Returns:
        (redacted_markdown, map_data, audit_data, ocr_meta)
        - redacted_markdown: The redacted text output
        - map_data: Map JSON with irreversible markers
        - audit_data: Audit JSON with low-confidence warnings
        - ocr_meta: OCR metadata (line count, warning count, etc.)
    """
    if ocr_engine != "rapidocr":
        raise ValueError(
            f"Unknown OCR engine: {ocr_engine}. "
            "Currently supported: rapidocr. "
            "Install with: pip install legal-desens[ocr]"
        )

    source_sha = _source_sha256(image_path)

    # Step 1: OCR
    ocr_result = run_rapidocr(image_path, confidence_threshold=confidence_threshold)

    # Step 2: Redact the OCR text
    redacted_text, redact_map, redact_audit = redact(
        text=ocr_result.text,
        rules=rules,
        source_sha256=source_sha,
        mode=mode,
        level=level,
        model_dir=model_dir,
    )

    # Step 3: Build irreversible map
    redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    map_data = {
        "schema_version": "1.0",
        "pipeline": "scan",
        "verification": "irreversible",
        "restore_supported": False,
        "best_effort": True,
        "source_file": str(Path(image_path).name),
        "source_sha256": source_sha,
        "redacted_sha256": redacted_sha,
        "level": level,
        "mode": mode,
        "ocr_engine": ocr_engine,
        "created_at": now,
        "entities": redact_map["entities"],
        "occurrences": redact_map["occurrences"],
    }

    # Step 4: Build audit with OCR warnings merged in
    warnings = list(redact_audit.get("warnings", []))

    # Add OCR low-confidence warnings
    for w in ocr_result.warnings:
        warnings.append(w)

    # Add top-level best-effort notice
    warnings.append({
        "type": "best_effort_notice",
        "message": (
            "This is an irreversible scan derivative. "
            "OCR may miss or misrecognize characters. "
            "Residual scan only covers recognized text. "
            "Original document cannot be restored from this output."
        ),
    })

    audit_data = {
        "schema_version": "1.0",
        "pipeline": "scan",
        "verification": "irreversible",
        "restore_supported": False,
        "best_effort": True,
        "summary": redact_audit["summary"],
        "residual_scan": redact_audit["residual_scan"],
        "ocr": {
            "engine": ocr_engine,
            "total_lines": len(ocr_result.lines),
            "low_confidence_lines": len(ocr_result.warnings),
            "confidence_threshold": confidence_threshold,
        },
        "warnings": warnings,
    }

    ocr_meta = {
        "engine": ocr_engine,
        "total_lines": len(ocr_result.lines),
        "low_confidence_lines": len(ocr_result.warnings),
        "text_length": len(ocr_result.text),
    }

    return redacted_text, map_data, audit_data, ocr_meta
