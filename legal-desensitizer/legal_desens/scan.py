"""Irreversible scan pipeline: OCR/Parse → Redact → Derive output.

This pipeline produces REDACTED DERIVATIVE COPIES (Markdown/Text).
It is NOT reversible — map marks pipeline:scan / verification:irreversible.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .engine.ocr import OCRResult, run_rapidocr
from .profile import Profile
from .redact import redact
from .rules import Rule


def _source_sha256(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_fitz_available() -> None:
    """Raise clear error if PyMuPDF (fitz) is not installed."""
    try:
        import importlib
        importlib.import_module("fitz")
    except ImportError:
        raise ImportError(
            "PyMuPDF is not installed. Install with:\n"
            "  pip install legal-desens[pdf]\n"
            "This will install PyMuPDF (AGPL licensed, opt-in for local use only)."
        )


def _render_pdf_pages(pdf_path: str, dpi: int = 200) -> Tuple[List[str], int]:
    """Render PDF pages to temporary PNG images.

    Returns:
        (list of temporary PNG file paths, total page count)
        Caller is responsible for cleaning up temp files.
    """
    from .adapters.pdf_adapter import render_pdf_pages

    result = render_pdf_pages(pdf_path, dpi=dpi)
    image_paths = [p.image_path for p in result.page_images]
    return image_paths, result.total_pages


def _cleanup_pdf_temp_pages(page_image_paths: List[str]) -> None:
    """Remove PDF render temp files and their generated temp directory."""
    if not page_image_paths:
        return

    temp_dir = Path(page_image_paths[0]).parent
    if temp_dir.name.startswith("legal_desens_pdf_"):
        shutil.rmtree(temp_dir, ignore_errors=True)
        return

    for p in page_image_paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        temp_dir.rmdir()
    except OSError:
        pass


_COMMON_SINGLE_CHAR_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
)


def _manual_review_warnings(text: str) -> List[dict]:
    """Flag scan/OCR residuals that are risky but too ambiguous to auto-redact."""
    warnings: List[dict] = []

    for match in re.finditer(r"(?<!\d)\d{6,10}(?!\d)", text):
        warnings.append({
            "type": "manual_review_suspicious_short_digits",
            "start": match.start(),
            "end": match.end(),
            "text_preview": match.group(0),
            "message": (
                "Short standalone digit sequence remains after redaction. "
                "It may be an OCR-truncated ID number, internal ID, date, or non-sensitive number; review before upload."
            ),
        })

    signer_pattern = re.compile(
        rf"(?:签名|签字|授权代表|法定代表人|代表人|委托人|受托人|甲方|乙方)"
        rf"[\s:：]*(?P<surname>[{_COMMON_SINGLE_CHAR_SURNAMES}])"
        rf"(?=$|[\s，。；;、])"
    )
    for match in signer_pattern.finditer(text):
        surname = match.group("surname")
        warnings.append({
            "type": "manual_review_single_char_signer",
            "start": match.start("surname"),
            "end": match.end("surname"),
            "text_preview": surname,
            "message": (
                "Single Chinese surname-like character appears in signing-party context. "
                "NER usually does not treat one character as a full person name; review before upload."
            ),
        })

    return warnings


def scan_redact(
    image_path: str,
    rules: List[Rule],
    ocr_engine: str = "rapidocr",
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
    confidence_threshold: float = 0.7,
    profile: Optional[Profile] = None,
    allowlist: Optional[set] = None,
    denylist: Optional[set] = None,
) -> Tuple[str, dict, dict, dict]:
    """Full irreversible scan pipeline: image/PDF → OCR → redact → derivative.

    Args:
        image_path: Path to image file or PDF.
        rules: Desensitization rules.
        ocr_engine: OCR engine to use (currently only "rapidocr").
        mode: "regex-only" or "regex+ner".
        level: Redaction level.
        model_dir: Path to NER model (if mode includes ner).
        confidence_threshold: OCR confidence threshold for warnings.
        profile: Profile defining redact/preserve policy.
        allowlist: Set of terms that should NOT be redacted.
        denylist: Set of terms that MUST be redacted.

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

    ext = Path(image_path).suffix.lower()

    if ext == ".pdf":
        return _scan_redact_pdf(
            pdf_path=image_path,
            rules=rules,
            ocr_engine=ocr_engine,
            mode=mode,
            level=level,
            model_dir=model_dir,
            confidence_threshold=confidence_threshold,
            profile=profile,
            allowlist=allowlist,
            denylist=denylist,
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
        profile=profile,
        allowlist=allowlist,
        denylist=denylist,
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
        "profile": profile.name if profile else "labor",
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

    warnings.extend(_manual_review_warnings(redacted_text))

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


def redact_scan_pixels(
    image_path: str,
    redacted_image_path: str,
    rules: List[Rule],
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
    confidence_threshold: float = 0.7,
    profile: Optional[Profile] = None,
    allowlist: Optional[set] = None,
    denylist: Optional[set] = None,
) -> Tuple[dict, dict]:
    """Irreversibly cover detected spans in an image using white OCR boxes."""
    from PIL import Image, ImageDraw

    ocr_result = run_rapidocr(image_path, confidence_threshold=confidence_threshold)
    source_sha = _source_sha256(image_path)
    _redacted_text, redact_map, redact_audit = redact(
        text=ocr_result.text,
        rules=rules,
        source_sha256=source_sha,
        mode=mode,
        level=level,
        model_dir=model_dir,
        profile=profile,
        allowlist=allowlist,
        denylist=denylist,
    )

    line_ranges = []
    offset = 0
    for line in ocr_result.lines:
        line_ranges.append((offset, offset + len(line.text), line))
        offset += len(line.text) + 1

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    unresolved = []
    for occurrence in redact_map.get("occurrences", []):
        start = occurrence["original_start"]
        end = occurrence["original_end"]
        matched = False
        polygons = []
        for line_start, line_end, line in line_ranges:
            overlap_start = max(start, line_start)
            overlap_end = min(end, line_end)
            if overlap_start >= overlap_end or not line.text:
                continue
            local_start = overlap_start - line_start
            local_end = overlap_end - line_start

            # RapidOCR exposes a quadrilateral for the whole recognized line,
            # not per-character boxes. Character widths are not uniform, so a
            # strict proportional slice can leave the edges of short NER spans
            # visible. Expand by one estimated character on each side and
            # interpolate along the original (possibly skewed) line box.
            padded_start = max(0, local_start - 1)
            padded_end = min(len(line.text), local_end + 1)
            start_ratio = padded_start / len(line.text)
            end_ratio = padded_end / len(line.text)

            top_left, top_right, bottom_right, bottom_left = line.box

            def interpolate(left_point, right_point, ratio):
                return [
                    left_point[0] + (right_point[0] - left_point[0]) * ratio,
                    left_point[1] + (right_point[1] - left_point[1]) * ratio,
                ]

            polygon = [
                interpolate(top_left, top_right, start_ratio),
                interpolate(top_left, top_right, end_ratio),
                interpolate(bottom_left, bottom_right, end_ratio),
                interpolate(bottom_left, bottom_right, start_ratio),
            ]
            draw.polygon([(p[0], p[1]) for p in polygon], fill="white")
            polygons.append(polygon)
            matched = True
        if not matched:
            unresolved.append(occurrence)
        else:
            occurrence["polygons"] = polygons

    if unresolved:
        raise RuntimeError(
            f"Unable to map {len(unresolved)} detected span(s) to OCR coordinates"
        )

    image.save(redacted_image_path)
    verification_ocr = run_rapidocr(
        redacted_image_path, confidence_threshold=confidence_threshold
    )
    originals = {
        entity["original"] for entity in redact_map.get("entities", []) if entity.get("original")
    }
    residual_originals = [value for value in originals if value in verification_ocr.text]
    if residual_originals:
        Path(redacted_image_path).unlink(missing_ok=True)
        raise RuntimeError("Sensitive text remains visible after pixel redaction")

    redacted_sha = _source_sha256(redacted_image_path)
    map_data = {
        **redact_map,
        "pipeline": "scan-pixel-redaction",
        "verification": "redacted-pixels",
        "restore_supported": False,
        "best_effort": True,
        "source_file": Path(image_path).name,
        "redacted_file": Path(redacted_image_path).name,
        "source_sha256": source_sha,
        "redacted_sha256": redacted_sha,
        "ocr_engine": "rapidocr",
    }
    warnings = list(redact_audit.get("warnings", [])) + list(ocr_result.warnings)
    warnings.append({
        "type": "best_effort_notice",
        "message": "OCR-based pixel redaction is irreversible and requires human review.",
    })
    audit_data = {
        **redact_audit,
        "pipeline": "scan-pixel-redaction",
        "verification": {"type": "redacted-pixels", "passed": True},
        "restore_supported": False,
        "best_effort": True,
        "warnings": warnings,
    }
    return map_data, audit_data


def _write_redacted_scan_pdf(page_images: List[str], output_path: str, dpi: int = 200) -> None:
    """Assemble redacted page images into an image-only PDF."""
    _check_fitz_available()
    import fitz

    output = fitz.open()
    try:
        for image_path in page_images:
            from PIL import Image

            with Image.open(image_path) as image:
                width_pt = image.width * 72.0 / dpi
                height_pt = image.height * 72.0 / dpi
            page = output.new_page(width=width_pt, height=height_pt)
            page.insert_image(page.rect, filename=image_path)
        output.save(output_path, deflate=True, garbage=3)
    finally:
        output.close()


def scan_redact_preserve_format(
    source_path: str,
    output_path: str,
    markdown_path: str,
    rules: List[Rule],
    ocr_engine: str = "rapidocr",
    mode: str = "regex-only",
    level: str = "strict",
    model_dir: Optional[str] = None,
    confidence_threshold: float = 0.7,
    profile: Optional[Profile] = None,
    allowlist: Optional[set] = None,
    denylist: Optional[set] = None,
) -> Tuple[dict, dict, dict]:
    """Produce redacted Markdown plus a white-boxed file in the source format."""
    source = Path(source_path)
    output = Path(output_path)
    markdown = Path(markdown_path)
    image_extensions = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

    if source.suffix.lower() != output.suffix.lower():
        raise ValueError("Format-preserving scan output must use the same extension as the input")
    if source.suffix.lower() not in image_extensions | {".pdf"}:
        raise ValueError(f"Unsupported format-preserving scan input: {source.suffix.lower()}")

    redacted_markdown, map_data, audit_data, ocr_meta = scan_redact(
        image_path=str(source),
        rules=rules,
        ocr_engine=ocr_engine,
        mode=mode,
        level=level,
        model_dir=model_dir,
        confidence_threshold=confidence_threshold,
        profile=profile,
        allowlist=allowlist,
        denylist=denylist,
    )
    markdown.write_text(redacted_markdown, encoding="utf-8")

    if source.suffix.lower() in image_extensions:
        redact_scan_pixels(
            str(source), str(output), rules, mode=mode, level=level,
            model_dir=model_dir, confidence_threshold=confidence_threshold,
            profile=profile, allowlist=allowlist, denylist=denylist,
        )
    else:
        page_images, _total_pages = _render_pdf_pages(str(source))
        temp_redacted_dir = Path(tempfile.mkdtemp(prefix="legal_desens_redacted_pdf_"))
        redacted_pages: List[str] = []
        try:
            for index, page_image in enumerate(page_images, start=1):
                redacted_page = temp_redacted_dir / f"page_{index:04d}.png"
                redact_scan_pixels(
                    page_image, str(redacted_page), rules, mode=mode, level=level,
                    model_dir=model_dir, confidence_threshold=confidence_threshold,
                    profile=profile, allowlist=allowlist, denylist=denylist,
                )
                redacted_pages.append(str(redacted_page))
            _write_redacted_scan_pdf(redacted_pages, str(output))
        finally:
            _cleanup_pdf_temp_pages(page_images)
            shutil.rmtree(temp_redacted_dir, ignore_errors=True)

    map_data.update({
        "pipeline": "scan-pixel-redaction",
        "verification": "redacted-pixels",
        "redacted_file": output.name,
        "redacted_sha256": _source_sha256(str(output)),
        "intermediate_markdown_file": markdown.name,
        "intermediate_markdown_sha256": _source_sha256(str(markdown)),
    })
    audit_data.update({
        "pipeline": "scan-pixel-redaction",
        "verification": {"type": "redacted-pixels", "passed": True},
    })
    return map_data, audit_data, ocr_meta


def _scan_redact_pdf(
    pdf_path: str,
    rules: List[Rule],
    ocr_engine: str,
    mode: str,
    level: str,
    model_dir: Optional[str],
    confidence_threshold: float,
    profile: Optional[Profile],
    allowlist: Optional[set],
    denylist: Optional[set],
) -> Tuple[str, dict, dict, dict]:
    """PDF-specific scan: render pages → OCR each → redact each → merge Markdown."""
    _check_fitz_available()

    source_sha = _source_sha256(pdf_path)
    page_image_paths, total_pages = _render_pdf_pages(pdf_path)

    try:
        page_texts: List[str] = []
        all_entities: List[dict] = []
        all_occurrences: List[dict] = []
        all_warnings: List[dict] = []
        all_residual_findings: List[dict] = []
        total_ocr_lines = 0
        total_low_conf = 0
        entity_id_counter = 0

        for page_idx, page_image_path in enumerate(page_image_paths):
            page_num = page_idx + 1

            # OCR this page
            ocr_result = run_rapidocr(page_image_path, confidence_threshold=confidence_threshold)
            total_ocr_lines += len(ocr_result.lines)
            total_low_conf += len(ocr_result.warnings)

            # Redact this page
            page_redacted, page_map, page_audit = redact(
                text=ocr_result.text,
                rules=rules,
                source_sha256=source_sha,
                mode=mode,
                level=level,
                model_dir=model_dir,
                profile=profile,
                allowlist=allowlist,
                denylist=denylist,
            )

            # Prefix entities with page number and re-index. Keep an explicit
            # old->new map so occurrences always point to an existing entity.
            entity_id_map = {}
            for entity in page_map.get("entities", []):
                entity_id_counter += 1
                old_id = entity.get("id", "")
                new_id = f"p{page_num}_{entity_id_counter}"
                entity["id"] = new_id
                entity["page"] = page_num
                if old_id:
                    entity_id_map[old_id] = new_id
                all_entities.append(entity)

            for occ in page_map.get("occurrences", []):
                occ["page"] = page_num
                old_id = occ.get("entity_id", "")
                if old_id:
                    occ["entity_id"] = entity_id_map.get(old_id, old_id)
                all_occurrences.append(occ)

            for w in ocr_result.warnings:
                w["page"] = page_num
                all_warnings.append(w)

            for w in page_audit.get("warnings", []):
                w["page"] = page_num
                all_warnings.append(w)

            # Collect residual findings from this page
            page_residual = page_audit.get("residual_scan", {}).get("findings", [])
            for f in page_residual:
                f["page"] = page_num
                all_residual_findings.append(f)

            # Format page heading
            page_texts.append(f"## 第 {page_num} 页\n\n{page_redacted}")

        redacted_text = "\n\n".join(page_texts) + "\n"

        # Add manual review warnings on combined text
        all_warnings.extend(_manual_review_warnings(redacted_text))

        # Best-effort notice
        all_warnings.append({
            "type": "best_effort_notice",
            "message": (
                f"This is an irreversible scan derivative from a {total_pages}-page PDF. "
                "OCR may miss or misrecognize characters. "
                "Residual scan only covers recognized text. "
                "Original document cannot be restored from this output."
            ),
        })

        # Aggregate residual scan from per-page redact() audit results
        residual_passed = len(all_residual_findings) == 0

        redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        by_entity_type: dict = {}
        for e in all_entities:
            etype = e.get("entity_type", "UNKNOWN")
            by_entity_type[etype] = by_entity_type.get(etype, 0) + 1

        map_data = {
            "schema_version": "1.0",
            "pipeline": "scan",
            "verification": "irreversible",
            "restore_supported": False,
            "best_effort": True,
            "source_file": str(Path(pdf_path).name),
            "source_sha256": source_sha,
            "redacted_sha256": redacted_sha,
            "profile": profile.name if profile else "labor",
            "level": level,
            "mode": mode,
            "ocr_engine": ocr_engine,
            "total_pages": total_pages,
            "created_at": now,
            "entities": all_entities,
            "occurrences": all_occurrences,
        }

        audit_data = {
            "schema_version": "1.0",
            "pipeline": "scan",
            "verification": "irreversible",
            "restore_supported": False,
            "best_effort": True,
            "summary": {
                "total_entities": len(all_entities),
                "total_occurrences": len(all_occurrences),
                "by_entity_type": by_entity_type,
            },
            "residual_scan": {
                "passed": residual_passed,
                "findings": all_residual_findings,
            },
            "ocr": {
                "engine": ocr_engine,
                "total_pages": total_pages,
                "total_lines": total_ocr_lines,
                "low_confidence_lines": total_low_conf,
                "confidence_threshold": confidence_threshold,
            },
            "warnings": all_warnings,
        }

        ocr_meta = {
            "engine": ocr_engine,
            "total_pages": total_pages,
            "total_lines": total_ocr_lines,
            "low_confidence_lines": total_low_conf,
            "text_length": len(redacted_text),
        }

        return redacted_text, map_data, audit_data, ocr_meta

    finally:
        _cleanup_pdf_temp_pages(page_image_paths)
