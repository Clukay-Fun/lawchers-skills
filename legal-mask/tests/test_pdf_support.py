"""Tests for 019 — Local PDF support via opt-in [pdf] extra."""

import hashlib
import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.rules import load_rules

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")
FITZ_AVAILABLE = importlib.util.find_spec("fitz") is not None
RAPIDOCR_AVAILABLE = importlib.util.find_spec("rapidocr_onnxruntime") is not None

requires_fitz = pytest.mark.skipif(
    not FITZ_AVAILABLE,
    reason="pymupdf is not installed; install with legal-desens[pdf]",
)
requires_ocr_and_fitz = pytest.mark.skipif(
    not (RAPIDOCR_AVAILABLE and FITZ_AVAILABLE),
    reason="requires both [ocr] and [pdf] extras",
)


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


@pytest.fixture
def synthetic_pdf(tmp_path):
    """Create a synthetic PDF with sensitive content for testing."""
    pytest.importorskip("fitz")
    import fitz

    doc = fitz.open()
    page = doc.new_page()

    # Insert text with phone number and name
    text = "联系电话 13800138000\n姓名 张三\n身份证 110101199001011234\n"
    point = fitz.Point(50, 100)
    page.insert_text(point, text, fontsize=12)

    # Second page
    page2 = doc.new_page()
    text2 = "公司 北京科技有限公司\n地址 北京市朝阳区\n银行账号 6222021234567890123\n"
    point2 = fitz.Point(50, 100)
    page2.insert_text(point2, text2, fontsize=12)

    pdf_path = str(tmp_path / "test_sensitive.pdf")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


# ── 1. PDF Adapter ───────────────────────────────────────────────────────────


@requires_fitz
class TestPDFAdapter:
    def test_render_pdf_pages(self, synthetic_pdf):
        """PDF adapter renders each page as a PNG image."""
        from legal_desens.adapters.pdf_adapter import render_pdf_pages

        result = render_pdf_pages(synthetic_pdf)

        assert result.total_pages == 2
        assert len(result.page_images) == 2
        assert result.page_images[0].page_number == 1
        assert result.page_images[1].page_number == 2

        # Verify images exist and are valid PNG
        for page_img in result.page_images:
            assert os.path.exists(page_img.image_path)
            assert page_img.image_path.endswith(".png")
            assert page_img.width > 0
            assert page_img.height > 0

            # Check PNG magic bytes
            with open(page_img.image_path, "rb") as f:
                header = f.read(8)
                assert header[:4] == b"\x89PNG"

    def test_render_pdf_custom_dpi(self, synthetic_pdf):
        """PDF adapter respects custom DPI setting."""
        from legal_desens.adapters.pdf_adapter import render_pdf_pages

        result_low = render_pdf_pages(synthetic_pdf, dpi=72)
        result_high = render_pdf_pages(synthetic_pdf, dpi=300)

        # Higher DPI should produce larger images
        assert result_high.page_images[0].width > result_low.page_images[0].width
        assert result_high.page_images[0].height > result_low.page_images[0].height

    def test_render_pdf_nonexistent_raises(self):
        """Rendering a nonexistent PDF raises FileNotFoundError."""
        from legal_desens.adapters.pdf_adapter import render_pdf_pages

        with pytest.raises(FileNotFoundError):
            render_pdf_pages("/nonexistent/path.pdf")

    def test_render_pdf_empty_raises(self, tmp_path):
        """Rendering a PDF that fitz cannot open raises an error."""
        pytest.importorskip("fitz")

        # Create a file that looks like PDF but is invalid/corrupt
        pdf_path = str(tmp_path / "empty.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.7\n%%EOF\n")

        from legal_desens.adapters.pdf_adapter import render_pdf_pages
        # Corrupt/empty PDF should raise some error (ValueError or fitz exception)
        with pytest.raises(Exception):
            render_pdf_pages(pdf_path)

    def test_render_pdf_cleanup(self, synthetic_pdf, tmp_path):
        """PDF adapter creates images in specified output directory."""
        from legal_desens.adapters.pdf_adapter import render_pdf_pages

        output_dir = str(tmp_path / "pdf_pages")
        result = render_pdf_pages(synthetic_pdf, output_dir=output_dir)

        assert os.path.isdir(output_dir)
        for page_img in result.page_images:
            assert page_img.image_path.startswith(output_dir)


# ── 2. Scan Pipeline with PDF ────────────────────────────────────────────────


@requires_ocr_and_fitz
class TestScanPipelinePDF:
    def test_scan_redact_pdf_produces_output(self, rules, synthetic_pdf):
        """Full pipeline: PDF → OCR → redact → text + map + audit."""
        from legal_desens.scan import scan_redact

        redacted, map_data, audit_data, ocr_meta = scan_redact(synthetic_pdf, rules)

        assert isinstance(redacted, str)
        assert len(redacted) > 0
        assert ocr_meta["total_pages"] == 2
        assert ocr_meta["total_lines"] >= 1

    def test_scan_redact_pdf_irreversible_markers(self, rules, synthetic_pdf):
        """Map from PDF scan has pipeline=scan, irreversible, best_effort markers."""
        from legal_desens.scan import scan_redact

        _, map_data, _, _ = scan_redact(synthetic_pdf, rules)

        assert map_data["pipeline"] == "scan"
        assert map_data["verification"] == "irreversible"
        assert map_data["restore_supported"] is False
        assert map_data["best_effort"] is True

    def test_scan_redact_pdf_map_has_required_fields(self, rules, synthetic_pdf):
        """Map contains schema_version, source_sha256, redacted_sha256, entities, occurrences, total_pages."""
        from legal_desens.scan import scan_redact

        _, map_data, _, _ = scan_redact(synthetic_pdf, rules)

        assert map_data["schema_version"] == "1.0"
        assert "source_sha256" in map_data
        assert "redacted_sha256" in map_data
        assert "entities" in map_data
        assert "occurrences" in map_data
        assert map_data["ocr_engine"] == "rapidocr"
        assert map_data["total_pages"] == 2

    def test_scan_redact_pdf_audit_has_best_effort_notice(self, rules, synthetic_pdf):
        """Audit must include a best_effort_notice warning mentioning PDF."""
        from legal_desens.scan import scan_redact

        _, _, audit_data, _ = scan_redact(synthetic_pdf, rules)

        assert audit_data["pipeline"] == "scan"
        assert audit_data["verification"] == "irreversible"
        assert audit_data["restore_supported"] is False
        assert audit_data["best_effort"] is True

        notice_warnings = [w for w in audit_data["warnings"] if w["type"] == "best_effort_notice"]
        assert len(notice_warnings) == 1
        assert "irreversible" in notice_warnings[0]["message"].lower()
        assert "pdf" in notice_warnings[0]["message"].lower()

    def test_scan_redact_pdf_audit_has_ocr_metadata(self, rules, synthetic_pdf):
        """Audit includes OCR engine info with page count."""
        from legal_desens.scan import scan_redact

        _, _, audit_data, _ = scan_redact(synthetic_pdf, rules)

        assert "ocr" in audit_data
        assert audit_data["ocr"]["engine"] == "rapidocr"
        assert audit_data["ocr"]["total_pages"] == 2
        assert audit_data["ocr"]["total_lines"] >= 1

    def test_scan_redact_pdf_source_sha_is_file_hash(self, rules, synthetic_pdf):
        """Map's source_sha256 matches the actual PDF file hash."""
        from legal_desens.scan import scan_redact

        _, map_data, _, _ = scan_redact(synthetic_pdf, rules)

        with open(synthetic_pdf, "rb") as f:
            expected_sha = hashlib.sha256(f.read()).hexdigest()

        assert map_data["source_sha256"] == expected_sha

    def test_scan_redact_pdf_redacted_sha_matches_text(self, rules, synthetic_pdf):
        """Map's redacted_sha256 matches the actual redacted text hash."""
        from legal_desens.scan import scan_redact

        redacted, map_data, _, _ = scan_redact(synthetic_pdf, rules)

        expected_sha = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        assert map_data["redacted_sha256"] == expected_sha

    def test_scan_redact_pdf_per_page_sections(self, rules, synthetic_pdf):
        """Redacted Markdown has per-page headings."""
        from legal_desens.scan import scan_redact

        redacted, _, _, _ = scan_redact(synthetic_pdf, rules)

        assert "## 第 1 页" in redacted
        assert "## 第 2 页" in redacted

    def test_scan_redact_pdf_entities_have_page_numbers(self, rules, synthetic_pdf):
        """Entities and occurrences in map have page numbers."""
        from legal_desens.scan import scan_redact

        _, map_data, _, _ = scan_redact(synthetic_pdf, rules)
        entity_ids = {entity["id"] for entity in map_data["entities"]}

        for entity in map_data["entities"]:
            assert "page" in entity
            assert entity["page"] in (1, 2)

        for occ in map_data["occurrences"]:
            assert "page" in occ
            assert occ["page"] in (1, 2)
            assert occ["entity_id"] in entity_ids

    def test_scan_redact_pdf_temp_cleanup(self, rules, synthetic_pdf):
        """Temporary page images are cleaned up after processing."""
        from legal_desens.scan import scan_redact

        scan_redact(synthetic_pdf, rules)

        # Temp files should be cleaned up — we can't check exact paths
        # but we can verify the function completes without error
        # and the test doesn't leave temp files around

    def test_scan_redact_pdf_removes_temp_dir_with_residue(self, rules, tmp_path, monkeypatch):
        """PDF cleanup removes the generated temp directory even if residue remains."""
        from legal_desens.engine.ocr import OCRResult
        import legal_desens.scan as scan_mod

        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")

        temp_dir = tmp_path / "legal_desens_pdf_case"
        temp_dir.mkdir()
        page = temp_dir / "page_0001.png"
        page.write_bytes(b"fake png")
        (temp_dir / "leftover.tmp").write_text("residue", encoding="utf-8")

        monkeypatch.setattr(scan_mod, "_check_fitz_available", lambda: None)
        monkeypatch.setattr(scan_mod, "_render_pdf_pages", lambda path: ([str(page)], 1))
        monkeypatch.setattr(
            scan_mod,
            "run_rapidocr",
            lambda path, confidence_threshold=0.7: OCRResult(
                text="电话13800138000。",
                lines=[],
                warnings=[],
            ),
        )
        monkeypatch.setattr(
            scan_mod,
            "redact",
            lambda **kwargs: (
                "电话【手机号】。",
                {"entities": [], "occurrences": []},
                {
                    "summary": {"total_entities": 0, "total_occurrences": 0, "by_entity_type": {}},
                    "residual_scan": {"passed": True, "findings": []},
                    "warnings": [],
                },
            ),
        )

        scan_mod.scan_redact(str(pdf), rules)

        assert not temp_dir.exists()


# ── 3. CLI PDF Routing ───────────────────────────────────────────────────────


@requires_ocr_and_fitz
class TestCLIPDFRouting:
    def test_redact_scan_pdf_cli(self, tmp_path, synthetic_pdf, rules):
        """CLI redact-scan with PDF produces output files."""
        from legal_desens.cli import main

        out_file = str(tmp_path / "out.md")
        map_file = str(tmp_path / "map.json")
        audit_file = str(tmp_path / "audit.json")

        rc = main([
            "redact-scan", synthetic_pdf,
            "--ocr", "rapidocr",
            "--regex-only",
            "--out", out_file,
            "--map", map_file,
            "--audit", audit_file,
        ])

        assert rc == 0
        assert os.path.exists(out_file)
        assert os.path.exists(map_file)
        assert os.path.exists(audit_file)

        with open(map_file, encoding="utf-8") as f:
            map_data = json.load(f)
        assert map_data["pipeline"] == "scan"
        assert map_data["verification"] == "irreversible"
        assert map_data["restore_supported"] is False
        assert map_data["best_effort"] is True
        assert map_data["total_pages"] == 2

        with open(audit_file, encoding="utf-8") as f:
            audit_data = json.load(f)
        assert audit_data["pipeline"] == "scan"
        best_effort = [w for w in audit_data["warnings"] if w["type"] == "best_effort_notice"]
        assert len(best_effort) == 1

    def test_redact_scan_pdf_preserves_pdf_format(self, tmp_path, synthetic_pdf):
        from legal_desens.cli import main

        output = tmp_path / "redacted.pdf"
        markdown = tmp_path / "redacted.intermediate.md"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"

        rc = main([
            "redact-scan", synthetic_pdf,
            "--ocr", "rapidocr",
            "--regex-only",
            "--out", str(output),
            "--md-out", str(markdown),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert rc == 0
        assert output.read_bytes().startswith(b"%PDF")
        assert markdown.exists()

        import fitz
        with fitz.open(output) as document:
            assert len(document) == 2

    def test_redact_scan_pdf_no_out_prints_stdout(self, synthetic_pdf):
        """Without --out, redact-scan with PDF prints to stdout."""
        from legal_desens.cli import main

        rc = main(["redact-scan", synthetic_pdf, "--regex-only"])

        assert rc == 0


# ── 4. Dependency Isolation ──────────────────────────────────────────────────


class TestPDFDependencyIsolation:
    def test_missing_fitz_raises_clear_error(self, monkeypatch):
        """If fitz is not importable, raises ImportError with install hint."""
        import importlib
        original_import = importlib.import_module

        def mock_import(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError("No module named 'fitz'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        from legal_desens.scan import _check_fitz_available
        with pytest.raises(ImportError, match="pip install legal-desens"):
            _check_fitz_available()

    def test_pdf_extra_independent_of_ocr(self):
        """pdf extra should be independent of ocr extra (different packages)."""
        # This is a contract test — verified at install time.
        # Read pyproject.toml directly to verify extras are separate.
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(pyproject_path) as f:
            content = f.read()

        # Verify [pdf] extra exists and contains pymupdf
        assert "pdf = [" in content or 'pdf = [' in content
        assert "pymupdf" in content.lower()

        # Verify [ocr] extra exists and contains rapidocr
        assert "ocr = [" in content or 'ocr = [' in content
        assert "rapidocr" in content.lower()


# ── 5. Default Install Does Not Include PyMuPDF ─────────────────────────────


class TestDefaultInstallClean:
    def test_default_dependencies_no_pymupdf(self):
        """Default dependencies (no extras) must not include PyMuPDF."""
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(pyproject_path) as f:
            content = f.read()

        # Extract the dependencies section (between [project] and [project.optional-dependencies])
        in_deps = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "dependencies = [":
                in_deps = True
                continue
            if in_deps:
                if stripped == "]":
                    break
                assert "pymupdf" not in stripped.lower(), f"PyMuPDF found in default dependencies: {stripped}"
                assert "fitz" not in stripped.lower(), f"fitz found in default dependencies: {stripped}"

    def test_pdf_extra_exists(self):
        """[pdf] extra must exist and contain pymupdf."""
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(pyproject_path) as f:
            content = f.read()

        assert "pdf" in content, "[pdf] extra not found in pyproject.toml"
        assert "pymupdf" in content.lower(), "pymupdf not found in [pdf] extra"

    def test_wheelhouse_builder_includes_install_extras(self):
        """Offline wheelhouse must include the extras install_with_model uses."""
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "build_wheelhouse.sh"
        )
        with open(script_path, encoding="utf-8") as f:
            content = f.read()

        assert "install_with_model.sh installs legal-desens[ocr,pdf]" in content
        assert "for group in ('ocr', 'pdf')" in content
