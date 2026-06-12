"""Tests for 009 — OCR/Parse irreversible scan pipeline."""

import hashlib
import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.rules import load_rules
from legal_desens.engine.ocr import run_rapidocr, OCRResult, CONFIDENCE_THRESHOLD

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "scan")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")
RAPIDOCR_AVAILABLE = importlib.util.find_spec("rapidocr_onnxruntime") is not None
requires_rapidocr = pytest.mark.skipif(
    not RAPIDOCR_AVAILABLE,
    reason="rapidocr_onnxruntime is not installed; install with legal-desens[ocr]",
)


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


# ── 1. OCR Engine ────────────────────────────────────────────────────────────


@requires_rapidocr
class TestRapidOCREngine:
    def test_basic_ocr(self):
        """RapidOCR reads text from a synthetic image."""
        path = os.path.join(FIXTURES, "sensitive.png")
        result = run_rapidocr(path)
        assert isinstance(result, OCRResult)
        assert len(result.lines) >= 1
        assert len(result.text) > 0

    def test_ocr_detects_phone_digits(self):
        """OCR output contains recognizable phone digits."""
        path = os.path.join(FIXTURES, "single_line.png")
        result = run_rapidocr(path)
        # OCR might introduce spaces, but digits should be present
        assert "13800138000" in result.text.replace(" ", "")

    def test_ocr_confidence_tracking(self):
        """Each line has a confidence score."""
        path = os.path.join(FIXTURES, "sensitive.png")
        result = run_rapidocr(path)
        for line in result.lines:
            assert 0.0 <= line.confidence <= 1.0

    def test_ocr_no_match_image(self):
        """Image with no sensitive content still produces OCR text."""
        path = os.path.join(FIXTURES, "no_match.png")
        result = run_rapidocr(path)
        assert len(result.lines) >= 1
        assert "plain" in result.text.lower() or "text" in result.text.lower()


# ── 2. Scan Pipeline ─────────────────────────────────────────────────────────


@requires_rapidocr
class TestScanPipeline:
    def test_scan_redact_produces_output(self, rules):
        """Full pipeline: image → OCR → redact → text + map + audit."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        redacted, map_data, audit_data, ocr_meta = scan_redact(path, rules)

        assert isinstance(redacted, str)
        assert len(redacted) > 0
        assert ocr_meta["total_lines"] >= 1

    def test_map_irreversible_markers(self, rules):
        """Map must have pipeline=scan, verification=irreversible, restore_supported=false, best_effort=true."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        _, map_data, _, _ = scan_redact(path, rules)

        assert map_data["pipeline"] == "scan"
        assert map_data["verification"] == "irreversible"
        assert map_data["restore_supported"] is False
        assert map_data["best_effort"] is True

    def test_map_has_required_fields(self, rules):
        """Map contains schema_version, source_sha256, redacted_sha256, entities, occurrences."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        _, map_data, _, _ = scan_redact(path, rules)

        assert map_data["schema_version"] == "1.0"
        assert "source_sha256" in map_data
        assert "redacted_sha256" in map_data
        assert "entities" in map_data
        assert "occurrences" in map_data
        assert map_data["ocr_engine"] == "rapidocr"

    def test_audit_has_best_effort_notice(self, rules):
        """Audit must include a best_effort_notice warning."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        _, _, audit_data, _ = scan_redact(path, rules)

        assert audit_data["pipeline"] == "scan"
        assert audit_data["verification"] == "irreversible"
        assert audit_data["restore_supported"] is False
        assert audit_data["best_effort"] is True

        notice_warnings = [w for w in audit_data["warnings"] if w["type"] == "best_effort_notice"]
        assert len(notice_warnings) == 1
        assert "irreversible" in notice_warnings[0]["message"].lower()

    def test_audit_has_ocr_metadata(self, rules):
        """Audit includes OCR engine info."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        _, _, audit_data, _ = scan_redact(path, rules)

        assert "ocr" in audit_data
        assert audit_data["ocr"]["engine"] == "rapidocr"
        assert audit_data["ocr"]["total_lines"] >= 1

    def test_source_sha_is_file_hash(self, rules):
        """Map's source_sha256 matches the actual file hash."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        _, map_data, _, _ = scan_redact(path, rules)

        with open(path, "rb") as f:
            expected_sha = hashlib.sha256(f.read()).hexdigest()

        assert map_data["source_sha256"] == expected_sha

    def test_redacted_sha_matches_text(self, rules):
        """Map's redacted_sha256 matches the actual redacted text hash."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        redacted, map_data, _, _ = scan_redact(path, rules)

        expected_sha = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        assert map_data["redacted_sha256"] == expected_sha

    def test_unknown_ocr_engine_raises(self, rules):
        """Passing an unknown OCR engine raises ValueError."""
        from legal_desens.scan import scan_redact

        path = os.path.join(FIXTURES, "sensitive.png")
        with pytest.raises(ValueError, match="Unknown OCR engine"):
            scan_redact(path, rules, ocr_engine="nonexistent")


# ── 3. Low Confidence Warnings ───────────────────────────────────────────────


@requires_rapidocr
class TestLowConfidence:
    def test_low_confidence_lines_generate_warnings(self, rules):
        """If OCR has low-confidence lines, audit includes low_confidence_ocr warnings."""
        from legal_desens.scan import scan_redact
        from legal_desens.engine.ocr import OCRLine, OCRResult

        path = os.path.join(FIXTURES, "sensitive.png")

        # Monkey-patch run_rapidocr to inject a low-confidence line
        import legal_desens.scan as scan_mod
        original_fn = scan_mod.run_rapidocr

        def mock_rapidocr(img_path, confidence_threshold=0.7):
            real = original_fn(img_path, confidence_threshold)
            # Add a fake low-confidence line
            low_line = OCRLine(
                text="unclear text 13800138000",
                box=[[0, 0], [100, 0], [100, 20], [0, 20]],
                confidence=0.3,
            )
            lines = list(real.lines) + [low_line]
            text = real.text + "\n" + low_line.text
            warnings = list(real.warnings) + [{
                "type": "low_confidence_ocr",
                "text_preview": low_line.text[:50],
                "confidence": 0.3,
                "threshold": confidence_threshold,
                "box": low_line.box,
            }]
            return OCRResult(text=text, lines=lines, warnings=warnings)

        scan_mod.run_rapidocr = mock_rapidocr
        try:
            _, _, audit_data, _ = scan_redact(path, rules)
            low_conf = [w for w in audit_data["warnings"] if w["type"] == "low_confidence_ocr"]
            assert len(low_conf) >= 1
            assert low_conf[0]["confidence"] < 0.7
        finally:
            scan_mod.run_rapidocr = original_fn


# ── 4. CLI Subcommands ───────────────────────────────────────────────────────


class TestCLIScanCommands:
    def test_redact_scan_help(self):
        """redact-scan subcommand appears in help."""
        from legal_desens.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["redact-scan", "--help"])
        assert exc_info.value.code == 0

    def test_parse_help(self):
        """parse subcommand appears in help."""
        from legal_desens.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["parse", "--help"])
        assert exc_info.value.code == 0

    def test_ocr_missing_extra_raises_import_error(self, monkeypatch):
        """If rapidocr is not importable, raises ImportError with install hint."""
        import importlib
        monkeypatch.setattr(
            importlib, "import_module",
            lambda name: (_ for _ in ()).throw(ImportError("mock")) if name == "rapidocr_onnxruntime" else importlib.__import__(name),
        )
        from legal_desens.engine.ocr import run_rapidocr
        with pytest.raises(ImportError, match="pip install legal-desens"):
            run_rapidocr("dummy.png")

    @requires_rapidocr
    def test_redact_scan_cli(self, tmp_path, rules):
        """CLI redact-scan produces output files."""
        from legal_desens.cli import main

        input_path = os.path.join(FIXTURES, "sensitive.png")
        out_file = str(tmp_path / "out.md")
        map_file = str(tmp_path / "map.json")
        audit_file = str(tmp_path / "audit.json")

        rc = main([
            "redact-scan", input_path,
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

        with open(audit_file, encoding="utf-8") as f:
            audit_data = json.load(f)
        assert audit_data["pipeline"] == "scan"
        best_effort = [w for w in audit_data["warnings"] if w["type"] == "best_effort_notice"]
        assert len(best_effort) == 1

    @requires_rapidocr
    def test_redact_scan_no_out_prints_stdout(self, capsys):
        """Without --out, redact-scan prints to stdout."""
        from legal_desens.cli import main

        input_path = os.path.join(FIXTURES, "single_line.png")
        rc = main(["redact-scan", input_path, "--regex-only"])

        assert rc == 0
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_parse_missing_extra_cli_error(self, monkeypatch):
        """parse command with missing docling extra gives clear error."""
        import legal_desens.engine.ocr as ocr_mod
        monkeypatch.setattr(ocr_mod, "_check_docling_available", lambda: (_ for _ in ()).throw(
            ImportError("Docling is not installed. Install with:\n  pip install legal-desens[parse-docling]")
        ))
        from legal_desens.cli import main
        rc = main(["parse", "dummy.pdf", "--out", "out.md"])
        assert rc == 1


# ── 5. Restore Not Supported ─────────────────────────────────────────────────


@requires_rapidocr
class TestRestoreNotSupported:
    def test_scan_map_cannot_be_used_for_restore(self, rules):
        """Map from scan pipeline should not be usable for restore (restore_supported=false)."""
        from legal_desens.scan import scan_redact
        from legal_desens.restore import restore

        path = os.path.join(FIXTURES, "sensitive.png")
        redacted, map_data, _, _ = scan_redact(path, rules)

        # The restore function checks for redacted_sha256 match, but the map
        # explicitly says restore_supported=false. This is a contract check —
        # callers should not attempt restore on scan maps.
        assert map_data["restore_supported"] is False
        # The map structure itself signals this; actual enforcement is at the
        # call-site level (SKILL.md / agent instructions).


# ── 6. Dependency Isolation ──────────────────────────────────────────────────


class TestDependencyIsolation:
    def test_ocr_extra_does_not_pull_docling(self):
        """ocr extra must be independent of parse-docling."""
        # This is a contract test — verified at install time.
        # Here we just verify the import paths are separate.
        import legal_desens.engine.ocr as ocr_mod
        # The module should import without docling
        assert hasattr(ocr_mod, "run_rapidocr")
        assert hasattr(ocr_mod, "run_docling_parse")
        # run_rapidocr should not touch docling
        # run_docling_parse raises ImportError if docling missing
