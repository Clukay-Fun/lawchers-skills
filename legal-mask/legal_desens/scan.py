"""Irreversible scan pipeline: OCR/Parse → Redact → Derive output.

This pipeline produces REDACTED DERIVATIVE COPIES (Markdown/Text).
It is NOT reversible — map marks pipeline:scan / verification:irreversible.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .engine.ocr import OCRResult, run_rapidocr
from .pipeline_diag import PipelineDiagnostics
from .profile import Profile
from .redact import redact
from .rules import Rule


def _run_rapidocr_compatible(
    image_path: str,
    confidence_threshold: float,
    engine,
) -> OCRResult:
    """Call run_rapidocr with a shared engine when the active implementation accepts it."""
    try:
        parameters = inspect.signature(run_rapidocr).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "engine" in parameters:
        return run_rapidocr(
            image_path,
            confidence_threshold=confidence_threshold,
            engine=engine,
        )
    return run_rapidocr(image_path, confidence_threshold=confidence_threshold)


class ScanPipelineContext:
    """Per-command runtime shared by every page in a scan operation."""

    def __init__(self, mode: str, model_dir: Optional[str] = None):
        self.mode = mode
        self.model_dir = model_dir
        self.diagnostics = PipelineDiagnostics()
        self._ocr_engine = None
        self._ner_engine = None

    def record_render(self, page_count: int) -> None:
        self.diagnostics.record_render(page_count)

    def run_ocr(
        self,
        image_path: str,
        confidence_threshold: float,
        *,
        page: Optional[int] = None,
        verification: bool = False,
    ) -> OCRResult:
        if self._ocr_engine is None:
            from .engine.ocr import get_rapidocr_instance

            self._ocr_engine = get_rapidocr_instance()
            self.diagnostics.record_rapidocr_instance()
        started = self.diagnostics.start_stage(
            "verification_ocr" if verification else "original_ocr",
            page,
        )
        try:
            return _run_rapidocr_compatible(
                image_path,
                confidence_threshold,
                self._ocr_engine,
            )
        finally:
            self.diagnostics.record_ocr(is_verification=verification)
            self.diagnostics.end_stage(
                "verification_ocr" if verification else "original_ocr",
                started,
                page,
            )

    def redact_text(self, *, page: Optional[int] = None, **kwargs):
        if self.mode != "regex-only" and self._ner_engine is None:
            from .engine.ner import get_ner_engine_instance

            self._ner_engine = get_ner_engine_instance(self.model_dir)
            self.diagnostics.record_ner_instance()
            self.diagnostics.record_onnx_session()
        started = self.diagnostics.start_stage("redact", page)
        try:
            return redact(ner_engine=self._ner_engine, **kwargs)
        finally:
            self.diagnostics.record_redact()
            self.diagnostics.end_stage("redact", started, page)


@dataclass
class PageScanResult:
    page: int
    image_path: str
    ocr_result: OCRResult
    redacted_text: str
    map_data: dict
    audit_data: dict


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


def _scan_page(
    image_path: str,
    page: int,
    source_sha: str,
    rules: List[Rule],
    context: ScanPipelineContext,
    level: str,
    confidence_threshold: float,
    profile: Optional[Profile],
    allowlist: Optional[set],
    denylist: Optional[set],
) -> PageScanResult:
    """OCR and redact one source page exactly once."""
    ocr_result = context.run_ocr(
        image_path,
        confidence_threshold,
        page=page,
    )
    redacted_text, map_data, audit_data = context.redact_text(
        page=page,
        text=ocr_result.text,
        rules=rules,
        source_sha256=source_sha,
        mode=context.mode,
        level=level,
        model_dir=context.model_dir,
        profile=profile,
        allowlist=allowlist,
        denylist=denylist,
    )
    return PageScanResult(
        page=page,
        image_path=image_path,
        ocr_result=ocr_result,
        redacted_text=redacted_text,
        map_data=map_data,
        audit_data=audit_data,
    )


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
    context: Optional[ScanPipelineContext] = None,
    page_results_out: Optional[List[PageScanResult]] = None,
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

    context = context or ScanPipelineContext(mode=mode, model_dir=model_dir)
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
            context=context,
            page_results_out=page_results_out,
        )

    source_sha = _source_sha256(image_path)

    page_result = _scan_page(
        image_path,
        1,
        source_sha,
        rules,
        context,
        level,
        confidence_threshold,
        profile,
        allowlist,
        denylist,
    )
    if page_results_out is not None:
        page_results_out.append(page_result)
    ocr_result = page_result.ocr_result
    redacted_text = page_result.redacted_text
    redact_map = page_result.map_data
    redact_audit = page_result.audit_data

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
        "pipeline_diagnostics": context.diagnostics.to_dict(),
    }

    ocr_meta = {
        "engine": ocr_engine,
        "total_lines": len(ocr_result.lines),
        "low_confidence_lines": len(ocr_result.warnings),
        "text_length": len(ocr_result.text),
    }

    return redacted_text, map_data, audit_data, ocr_meta


def _line_span_polygon(line, start: int, end: int, padding_chars: float = 0.0):
    """Approximate a character span inside a four-point OCR line box."""
    if not line.text or len(line.box) != 4:
        return None
    padded_start = max(0.0, start - padding_chars)
    padded_end = min(float(len(line.text)), end + padding_chars)
    start_ratio = padded_start / len(line.text)
    end_ratio = padded_end / len(line.text)
    top_left, top_right, bottom_right, bottom_left = line.box

    def interpolate(left_point, right_point, ratio):
        return [
            left_point[0] + (right_point[0] - left_point[0]) * ratio,
            left_point[1] + (right_point[1] - left_point[1]) * ratio,
        ]

    return [
        interpolate(top_left, top_right, start_ratio),
        interpolate(top_left, top_right, end_ratio),
        interpolate(bottom_left, bottom_right, end_ratio),
        interpolate(bottom_left, bottom_right, start_ratio),
    ]


def _polygons_intersect(first, second) -> bool:
    def bounds(polygon):
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        return min(xs), min(ys), max(xs), max(ys)

    a_left, a_top, a_right, a_bottom = bounds(first)
    b_left, b_top, b_right, b_bottom = bounds(second)
    return not (
        a_right < b_left
        or b_right < a_left
        or a_bottom < b_top
        or b_bottom < a_top
    )


def _expand_polygon(polygon):
    """Conservatively expand a failed mask for one bounded retry."""
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    x_pad = max(3.0, (right - left) * 0.25)
    y_pad = max(2.0, (bottom - top) * 0.15)
    return [
        [left - x_pad, top - y_pad],
        [right + x_pad, top - y_pad],
        [right + x_pad, bottom + y_pad],
        [left - x_pad, bottom + y_pad],
    ]


def _classify_pixel_residuals(
    verification_ocr: OCRResult,
    redact_map: dict,
    page_number: int,
) -> List[dict]:
    """Classify residual entities without copying sensitive text into audit."""
    occurrences_by_entity = {}
    for occurrence in redact_map.get("occurrences", []):
        occurrences_by_entity.setdefault(occurrence.get("entity_id"), []).append(occurrence)

    failures = []
    for entity in redact_map.get("entities", []):
        original = entity.get("original")
        entity_id = entity.get("id") or entity.get("entity_id")
        if not original or original not in verification_ocr.text:
            continue

        mask_polygons = [
            polygon
            for occurrence in occurrences_by_entity.get(entity_id, [])
            for polygon in occurrence.get("polygons", [])
        ]
        intersects_mask = False
        for line in verification_ocr.lines:
            search_start = 0
            while True:
                local_start = line.text.find(original, search_start)
                if local_start < 0:
                    break
                residual_polygon = _line_span_polygon(
                    line,
                    local_start,
                    local_start + len(original),
                )
                if residual_polygon and any(
                    _polygons_intersect(residual_polygon, mask)
                    for mask in mask_polygons
                ):
                    intersects_mask = True
                    break
                search_start = local_start + 1
            if intersects_mask:
                break

        failures.append({
            "page": page_number,
            "entity_id": entity_id,
            "entity_type": entity.get("entity_type", "UNKNOWN"),
            "category": "pixel_undercoverage" if intersects_mask else "unmapped_residual",
        })
    return failures


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
    context: Optional[ScanPipelineContext] = None,
    page_result: Optional[PageScanResult] = None,
    page_number: int = 1,
) -> Tuple[dict, dict]:
    """Irreversibly cover detected spans in an image using white OCR boxes."""
    from PIL import Image, ImageDraw

    context = context or ScanPipelineContext(mode=mode, model_dir=model_dir)
    source_sha = _source_sha256(image_path)
    if page_result is None:
        page_result = _scan_page(
            image_path,
            page_number,
            source_sha,
            rules,
            context,
            level,
            confidence_threshold,
            profile,
            allowlist,
            denylist,
        )
    ocr_result = page_result.ocr_result
    redact_map = page_result.map_data
    redact_audit = page_result.audit_data

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

            polygon = _line_span_polygon(
                line,
                local_start,
                local_end,
                padding_chars=1.0,
            )
            if polygon is None:
                continue
            draw.polygon([(p[0], p[1]) for p in polygon], fill="white")
            polygons.append(polygon)
            matched = True
        if not matched:
            unresolved.append(occurrence)
        else:
            occurrence["polygons"] = polygons

    image.save(redacted_image_path)
    verification_ocr = context.run_ocr(
        redacted_image_path,
        confidence_threshold,
        page=page_number,
        verification=True,
    )
    failures = _classify_pixel_residuals(
        verification_ocr,
        redact_map,
        page_number,
    )
    entity_types = {
        (entity.get("id") or entity.get("entity_id")): entity.get("entity_type", "UNKNOWN")
        for entity in redact_map.get("entities", [])
    }
    for occurrence in unresolved:
        failures.append({
            "page": page_number,
            "entity_id": occurrence.get("entity_id"),
            "entity_type": entity_types.get(occurrence.get("entity_id"), "UNKNOWN"),
            "category": "coordinate_mapping_failed",
        })

    retry_attempted = False
    retry_entity_ids = {
        failure["entity_id"]
        for failure in failures
        if failure["category"] == "pixel_undercoverage"
    }
    if retry_entity_ids:
        retry_attempted = True
        for occurrence in redact_map.get("occurrences", []):
            if occurrence.get("entity_id") not in retry_entity_ids:
                continue
            expanded_polygons = []
            for polygon in occurrence.get("polygons", []):
                expanded = _expand_polygon(polygon)
                draw.polygon([(point[0], point[1]) for point in expanded], fill="white")
                expanded_polygons.append(expanded)
            occurrence["polygons"] = expanded_polygons
        image.save(redacted_image_path)
        verification_ocr = context.run_ocr(
            redacted_image_path,
            confidence_threshold,
            page=page_number,
            verification=True,
        )
        failures = _classify_pixel_residuals(
            verification_ocr,
            redact_map,
            page_number,
        )
        for occurrence in unresolved:
            failures.append({
                "page": page_number,
                "entity_id": occurrence.get("entity_id"),
                "entity_type": entity_types.get(occurrence.get("entity_id"), "UNKNOWN"),
                "category": "coordinate_mapping_failed",
            })

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
        "verification": {
            "type": "redacted-pixels",
            "passed": not failures,
            "failed_pages": [page_number] if failures else [],
            "failures": failures,
            "retry_attempted": retry_attempted,
        },
        "restore_supported": False,
        "best_effort": True,
        "warnings": warnings,
        "pipeline_diagnostics": context.diagnostics.to_dict(),
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

    context = ScanPipelineContext(mode=mode, model_dir=model_dir)
    page_results: List[PageScanResult] = []
    pixel_failures: List[dict] = []
    retry_attempted = False
    artifact_output = output
    incomplete_output = output.with_name(
        f"{output.stem}.INCOMPLETE_DO_NOT_USE{output.suffix}"
    )
    incomplete_output.unlink(missing_ok=True)

    if source.suffix.lower() in image_extensions:
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
            context=context,
            page_results_out=page_results,
        )
        markdown.write_text(redacted_markdown, encoding="utf-8")
        _pixel_map, pixel_audit = redact_scan_pixels(
            str(source), str(output), rules, mode=mode, level=level,
            model_dir=model_dir, confidence_threshold=confidence_threshold,
            profile=profile, allowlist=allowlist, denylist=denylist,
            context=context, page_result=page_results[0], page_number=1,
        )
        pixel_verification = pixel_audit["verification"]
        pixel_failures.extend(pixel_verification.get("failures", []))
        retry_attempted = pixel_verification.get("retry_attempted", False)
        if pixel_failures:
            artifact_output = incomplete_output
            output.replace(artifact_output)
    else:
        page_images, total_pages = _render_pdf_pages(str(source))
        context.record_render(total_pages)
        temp_redacted_dir = Path(tempfile.mkdtemp(prefix="legal_desens_redacted_pdf_"))
        redacted_pages: List[str] = []
        try:
            redacted_markdown, map_data, audit_data, ocr_meta = _scan_redact_pdf(
                pdf_path=str(source),
                rules=rules,
                ocr_engine=ocr_engine,
                mode=mode,
                level=level,
                model_dir=model_dir,
                confidence_threshold=confidence_threshold,
                profile=profile,
                allowlist=allowlist,
                denylist=denylist,
                context=context,
                page_image_paths=page_images,
                total_pages=total_pages,
                page_results_out=page_results,
            )
            markdown.write_text(redacted_markdown, encoding="utf-8")
            for page_result in page_results:
                index = page_result.page
                page_image = page_result.image_path
                redacted_page = temp_redacted_dir / f"page_{index:04d}.png"
                _pixel_map, pixel_audit = redact_scan_pixels(
                    page_image, str(redacted_page), rules, mode=mode, level=level,
                    model_dir=model_dir, confidence_threshold=confidence_threshold,
                    profile=profile, allowlist=allowlist, denylist=denylist,
                    context=context, page_result=page_result, page_number=index,
                )
                pixel_verification = pixel_audit["verification"]
                pixel_failures.extend(pixel_verification.get("failures", []))
                retry_attempted = (
                    retry_attempted
                    or pixel_verification.get("retry_attempted", False)
                )
                redacted_pages.append(str(redacted_page))
            if pixel_failures:
                artifact_output = incomplete_output
                output.unlink(missing_ok=True)
            _write_redacted_scan_pdf(redacted_pages, str(artifact_output))
        finally:
            _cleanup_pdf_temp_pages(page_images)
            shutil.rmtree(temp_redacted_dir, ignore_errors=True)

    map_data.update({
        "pipeline": "scan-pixel-redaction",
        "verification": "redacted-pixels",
        "redacted_file": artifact_output.name,
        "redacted_sha256": _source_sha256(str(artifact_output)),
        "intermediate_markdown_file": markdown.name,
        "intermediate_markdown_sha256": _source_sha256(str(markdown)),
    })
    audit_data.update({
        "pipeline": "scan-pixel-redaction",
        "verification": {
            "type": "redacted-pixels",
            "passed": not pixel_failures,
            "failed_pages": sorted({failure["page"] for failure in pixel_failures}),
            "failures": pixel_failures,
            "retry_attempted": retry_attempted,
            "incomplete_output_file": artifact_output.name if pixel_failures else None,
        },
        "pipeline_diagnostics": context.diagnostics.to_dict(),
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
    context: ScanPipelineContext,
    page_image_paths: Optional[List[str]] = None,
    total_pages: Optional[int] = None,
    page_results_out: Optional[List[PageScanResult]] = None,
) -> Tuple[str, dict, dict, dict]:
    """PDF-specific scan: render pages → OCR each → redact each → merge Markdown."""
    _check_fitz_available()

    source_sha = _source_sha256(pdf_path)
    owns_page_images = page_image_paths is None
    if page_image_paths is None:
        page_image_paths, rendered_page_count = _render_pdf_pages(pdf_path)
        total_pages = rendered_page_count
        context.record_render(rendered_page_count)
    elif total_pages is None:
        total_pages = len(page_image_paths)

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

            page_result = _scan_page(
                page_image_path,
                page_num,
                source_sha,
                rules,
                context,
                level,
                confidence_threshold,
                profile,
                allowlist,
                denylist,
            )
            if page_results_out is not None:
                page_results_out.append(page_result)
            ocr_result = page_result.ocr_result
            total_ocr_lines += len(ocr_result.lines)
            total_low_conf += len(ocr_result.warnings)
            page_redacted = page_result.redacted_text
            page_map = page_result.map_data
            page_audit = page_result.audit_data

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
            "pipeline_diagnostics": context.diagnostics.to_dict(),
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
        if owns_page_images:
            _cleanup_pdf_temp_pages(page_image_paths)
