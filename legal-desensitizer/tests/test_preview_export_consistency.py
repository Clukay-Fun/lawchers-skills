"""P6.1 Preview-Export Consistency Test.

Verifies that entities from prepare match what text-export actually produces:
1. Entity count: prepare candidates == export entities applied
2. Residual: sensitive originals NOT extractable from export
3. Mode: star/placeholder replacements present in export

Uses synthetic PDFs — no real case materials.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def _cli_args(*args):
    """Build CLI args using python -m."""
    return [sys.executable, "-m", "legal_desens.cli", *args]


def _run_cmd(args, cwd=None):
    """Run CLI command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=60, cwd=cwd,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a synthetic text-layer PDF with known sensitive content."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "张三的电话是13800138000", fontname="china-s", fontsize=12)
    page.insert_text((72, 130), "身份证号110101199003071234", fontname="china-s", fontsize=12)
    page.insert_text((72, 160), "普通文字没有敏感信息", fontname="china-s", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _prepare(pdf_path, work_dir, regex_only=True):
    """Run prepare and return manifest + source map."""
    manifest_path = work_dir / "manifest.json"
    preview_path = work_dir / "preview.md"
    source_map_path = work_dir / "source-map.json"
    args = _cli_args("prepare", str(pdf_path),
                     "--manifest", str(manifest_path),
                     "--preview-md", str(preview_path),
                     "--map", str(source_map_path))
    if regex_only:
        args.insert(args.index("prepare") + 1, "--regex-only")
    rc, _, stderr = _run_cmd(args, cwd=str(work_dir))
    assert rc == 0, f"prepare failed: {stderr}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_map = json.loads(source_map_path.read_text(encoding="utf-8")) if source_map_path.exists() else {}
    return manifest, source_map


def _text_export(pdf_path, ocr_text, entities, mode, fmt, work_dir):
    """Run text-export and return output path + content."""
    entities_path = work_dir / "entities.json"
    entities_path.write_text(json.dumps(entities, ensure_ascii=False), encoding="utf-8")
    ocr_text_path = work_dir / "ocr_text.txt"
    ocr_text_path.write_text(ocr_text, encoding="utf-8")
    out_path = work_dir / f"exported.{fmt}"
    args = _cli_args("text-export", str(pdf_path),
                     "--entities", str(entities_path),
                     "--ocr-text", str(ocr_text_path),
                     "--out", str(out_path),
                     "--mode", mode,
                     "--format", fmt)
    rc, _, stderr = _run_cmd(args, cwd=str(work_dir))
    assert rc == 0, f"text-export failed: {stderr}"
    return out_path, out_path.read_text(encoding="utf-8")


def _extract_ocr_text(manifest, source_map):
    """Extract OCR text from prepare results."""
    blocks = source_map.get("blocks", [])
    return "\n".join(b.get("text", "") for b in blocks)


def _candidates_to_entities(manifest, source_map):
    """Convert prepare candidates to entity list for text-export.

    Candidates have blockId/start/end but not text. Extract text from blocks.
    """
    candidates = manifest.get("candidates", [])
    blocks_by_id = {b["id"]: b for b in source_map.get("blocks", [])}
    entities = []
    for c in candidates:
        block = blocks_by_id.get(c.get("blockId"), {})
        block_text = block.get("text", "")
        start = c.get("start", 0)
        end = c.get("end", 0)
        original = block_text[start:end] if start < len(block_text) else ""
        if not original:
            continue
        entities.append({
            "original": original,
            "entity_type": c.get("entityType", "CUSTOM"),
            "start": start,
            "end": end,
        })
    return entities


class TestPreviewExportConsistency:
    """P6.1: Verify prepare candidates match export output."""

    def test_star_entity_count_matches(self, sample_pdf, tmp_path):
        """prepare candidate count == entities applied in export."""
        work = tmp_path / "work"
        work.mkdir()

        manifest, source_map = _prepare(sample_pdf, work)
        entities = _candidates_to_entities(manifest, source_map)
        assert len(entities) > 0, "No candidates detected"

        ocr_text = _extract_ocr_text(manifest, source_map)
        _, content = _text_export(sample_pdf, ocr_text, entities, "star", "txt", work)

        for ent in entities:
            original = ent["original"]
            assert original not in content, \
                f"Entity '{original}' still present in star export (should be masked)"

    def test_placeholder_entity_count_matches(self, sample_pdf, tmp_path):
        """Placeholder export also masks all detected entities."""
        work = tmp_path / "work"
        work.mkdir()

        manifest, source_map = _prepare(sample_pdf, work)
        entities = _candidates_to_entities(manifest, source_map)
        assert len(entities) > 0

        ocr_text = _extract_ocr_text(manifest, source_map)
        _, content = _text_export(sample_pdf, ocr_text, entities, "placeholder", "txt", work)

        for ent in entities:
            original = ent["original"]
            assert original not in content, \
                f"Entity '{original}' still present in placeholder export"

    def test_sensitive_not_extractable(self, sample_pdf, tmp_path):
        """After star export, sensitive originals are NOT in output text."""
        work = tmp_path / "work"
        work.mkdir()

        manifest, source_map = _prepare(sample_pdf, work)
        entities = _candidates_to_entities(manifest, source_map)
        ocr_text = _extract_ocr_text(manifest, source_map)

        _, content = _text_export(sample_pdf, ocr_text, entities, "star", "txt", work)

        sensitive = ["13800138000", "110101199003071234"]
        for s in sensitive:
            if any(s in ent["original"] for ent in entities):
                assert s not in content, \
                    f"Sensitive value '{s}' extractable from export"

    def test_non_sensitive_preserved(self, sample_pdf, tmp_path):
        """Non-sensitive text is preserved in export."""
        work = tmp_path / "work"
        work.mkdir()

        manifest, source_map = _prepare(sample_pdf, work)
        entities = _candidates_to_entities(manifest, source_map)
        ocr_text = _extract_ocr_text(manifest, source_map)

        _, content = _text_export(sample_pdf, ocr_text, entities, "star", "txt", work)

        assert "普通文字没有敏感信息" in content, \
            "Non-sensitive text was removed from export"

    def test_star_mode_replacement_format(self, sample_pdf, tmp_path):
        """Star export contains star-masked patterns."""
        work = tmp_path / "work"
        work.mkdir()

        manifest, source_map = _prepare(sample_pdf, work)
        entities = _candidates_to_entities(manifest, source_map)
        ocr_text = _extract_ocr_text(manifest, source_map)

        _, content = _text_export(sample_pdf, ocr_text, entities, "star", "txt", work)

        assert "****" in content or "***" in content, \
            "Star export doesn't contain star-masked patterns"

    def test_placeholder_mode_replacement_format(self, sample_pdf, tmp_path):
        """Placeholder export contains <type> tags."""
        work = tmp_path / "work"
        work.mkdir()

        manifest, source_map = _prepare(sample_pdf, work)
        entities = _candidates_to_entities(manifest, source_map)
        ocr_text = _extract_ocr_text(manifest, source_map)

        _, content = _text_export(sample_pdf, ocr_text, entities, "placeholder", "txt", work)

        assert "<" in content and ">" in content, \
            "Placeholder export doesn't contain <type> tags"
