"""021: Scan pipeline performance and pixel failure fix tests."""
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from legal_desens.pipeline_diag import PipelineDiagnostics


def _blank_page(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (120, 40), "white").save(path)


class TestPipelineDiagnostics:
    """Test PipelineDiagnostics counter logic."""

    def test_initial_state(self):
        diag = PipelineDiagnostics()
        assert diag.render_document_calls == 0
        assert diag.rendered_pages == 0
        assert diag.original_ocr_calls == 0
        assert diag.verification_ocr_calls == 0
        assert diag.redact_calls == 0
        assert diag.rapidocr_instances == 0
        assert diag.ner_engine_instances == 0
        assert diag.onnx_sessions == 0

    def test_record_render(self):
        diag = PipelineDiagnostics()
        diag.record_render(8)
        assert diag.render_document_calls == 1
        assert diag.rendered_pages == 8

    def test_record_ocr(self):
        diag = PipelineDiagnostics()
        diag.record_ocr(is_verification=False)
        diag.record_ocr(is_verification=True)
        assert diag.original_ocr_calls == 1
        assert diag.verification_ocr_calls == 1

    def test_assert_hard_metrics_pass(self):
        diag = PipelineDiagnostics()
        diag.record_render(4)
        for _ in range(4):
            diag.record_ocr(is_verification=False)
            diag.record_ocr(is_verification=True)
            diag.record_redact()
        diag.record_rapidocr_instance()

        violations = diag.assert_hard_metrics(4, mode="regex-only")
        assert violations == []

    def test_assert_hard_metrics_fail_render(self):
        diag = PipelineDiagnostics()
        diag.record_render(4)
        diag.record_render(4)  # Second call = violation

        violations = diag.assert_hard_metrics(4, mode="regex-only")
        assert any("render_document_calls" in v for v in violations)

    def test_assert_hard_metrics_regex_only_no_ner(self):
        diag = PipelineDiagnostics()
        diag.record_render(4)
        diag.record_rapidocr_instance()
        # In regex-only, NER instances should be 0
        diag.record_ner_instance()  # This would be a violation

        violations = diag.assert_hard_metrics(4, mode="regex-only")
        assert any("ner_engine_instances" in v for v in violations)

    def test_two_page_pdf_uses_single_production_pass(self, monkeypatch, tmp_path):
        import legal_desens.scan as scan_module
        from legal_desens.engine.ocr import OCRLine, OCRResult

        source = tmp_path / "source.pdf"
        source.write_bytes(b"%PDF synthetic")
        pages = [tmp_path / "page1.png", tmp_path / "page2.png"]
        for page in pages:
            _blank_page(page)

        render_calls = 0

        def fake_render(_path, dpi=200):
            nonlocal render_calls
            render_calls += 1
            return [str(page) for page in pages], len(pages)

        ocr_calls = 0

        def fake_ocr(_path, confidence_threshold=0.7, engine=None):
            nonlocal ocr_calls
            ocr_calls += 1
            line = OCRLine("plain text", [[0, 0], [100, 0], [100, 20], [0, 20]], 0.99)
            return OCRResult(text=line.text, lines=[line])

        redact_calls = 0

        def fake_redact(**_kwargs):
            nonlocal redact_calls
            redact_calls += 1
            return (
                "plain text",
                {"entities": [], "occurrences": []},
                {
                    "summary": {"total_entities": 0, "total_occurrences": 0, "by_entity_type": {}},
                    "residual_scan": {"passed": True, "findings": []},
                    "warnings": [],
                },
            )

        monkeypatch.setattr(scan_module, "_render_pdf_pages", fake_render)
        monkeypatch.setattr(scan_module, "run_rapidocr", fake_ocr)
        monkeypatch.setattr(scan_module, "redact", fake_redact)
        monkeypatch.setattr(
            scan_module,
            "_write_redacted_scan_pdf",
            lambda _pages, output, dpi=200: Path(output).write_bytes(b"%PDF redacted"),
        )
        monkeypatch.setattr(scan_module, "_cleanup_pdf_temp_pages", lambda _pages: None)

        _map, audit, _meta = scan_module.scan_redact_preserve_format(
            str(source),
            str(tmp_path / "redacted.pdf"),
            str(tmp_path / "redacted.md"),
            rules=[],
            mode="regex-only",
        )

        assert render_calls == 1
        assert ocr_calls == 4
        assert redact_calls == 2
        assert audit["pipeline_diagnostics"]["call_counts"] == {
            "render_document": 1,
            "rendered_pages": 2,
            "original_ocr": 2,
            "verification_ocr": 2,
            "redact": 2,
        }


class TestPixelFailureDiagnostics:
    def test_residual_is_classified_without_sensitive_text(self, monkeypatch, tmp_path):
        import legal_desens.scan as scan_module
        from legal_desens.engine.ocr import OCRLine, OCRResult

        source = tmp_path / "source.png"
        output = tmp_path / "redacted.png"
        _blank_page(source)
        line = OCRLine(
            "甲乙丙王小明丁戊",
            [[0, 0], [100, 0], [100, 20], [0, 20]],
            0.99,
        )

        def fake_ocr(path, confidence_threshold=0.7):
            return OCRResult(text=line.text, lines=[line])

        def fake_redact(**_kwargs):
            return (
                "甲乙丙【姓名】丁戊",
                {
                    "entities": [{"id": "PERSON_1", "entity_type": "PERSON", "original": "王小明"}],
                    "occurrences": [{"entity_id": "PERSON_1", "original_start": 3, "original_end": 6}],
                },
                {
                    "summary": {"total_entities": 1, "total_occurrences": 1, "by_entity_type": {"PERSON": 1}},
                    "residual_scan": {"passed": True, "findings": []},
                    "warnings": [],
                },
            )

        monkeypatch.setattr(scan_module, "run_rapidocr", fake_ocr)
        monkeypatch.setattr(scan_module, "redact", fake_redact)

        _map, audit = scan_module.redact_scan_pixels(
            str(source),
            str(output),
            rules=[],
            page_number=7,
        )

        assert audit["verification"]["passed"] is False
        assert audit["verification"]["failed_pages"] == [7]
        assert audit["verification"]["failures"][0] == {
            "page": 7,
            "entity_id": "PERSON_1",
            "entity_type": "PERSON",
            "category": "pixel_undercoverage",
        }
        assert "王小明" not in json.dumps(audit, ensure_ascii=False)

    def test_undercoverage_gets_one_local_retry(self, monkeypatch, tmp_path):
        import legal_desens.scan as scan_module
        from legal_desens.engine.ocr import OCRLine, OCRResult

        source = tmp_path / "source.png"
        output = tmp_path / "redacted.png"
        _blank_page(source)
        line = OCRLine("甲乙丙王小明丁戊", [[0, 0], [100, 0], [100, 20], [0, 20]], 0.99)
        calls = 0

        def fake_ocr(path, confidence_threshold=0.7):
            nonlocal calls
            calls += 1
            text = line.text if calls <= 2 else "甲乙丙丁戊"
            return OCRResult(text=text, lines=[line])

        monkeypatch.setattr(scan_module, "run_rapidocr", fake_ocr)
        monkeypatch.setattr(
            scan_module,
            "redact",
            lambda **_kwargs: (
                "甲乙丙【姓名】丁戊",
                {
                    "entities": [{"id": "PERSON_1", "entity_type": "PERSON", "original": "王小明"}],
                    "occurrences": [{"entity_id": "PERSON_1", "original_start": 3, "original_end": 6}],
                },
                {
                    "summary": {"total_entities": 1, "total_occurrences": 1, "by_entity_type": {"PERSON": 1}},
                    "residual_scan": {"passed": True, "findings": []},
                    "warnings": [],
                },
            ),
        )

        _map, audit = scan_module.redact_scan_pixels(str(source), str(output), rules=[])

        assert audit["verification"]["passed"] is True
        assert audit["verification"]["retry_attempted"] is True
        assert audit["pipeline_diagnostics"]["call_counts"]["verification_ocr"] == 2

    def test_failed_pdf_is_quarantined_and_reports_page(self, monkeypatch, tmp_path):
        import legal_desens.scan as scan_module
        from legal_desens.engine.ocr import OCRLine, OCRResult

        source = tmp_path / "source.pdf"
        output = tmp_path / "redacted.pdf"
        markdown = tmp_path / "redacted.md"
        source.write_bytes(b"%PDF synthetic")
        pages = [tmp_path / "page1.png", tmp_path / "page2.png"]
        for page in pages:
            _blank_page(page)

        monkeypatch.setattr(
            scan_module,
            "_render_pdf_pages",
            lambda _path, dpi=200: ([str(page) for page in pages], 2),
        )
        monkeypatch.setattr(scan_module, "_cleanup_pdf_temp_pages", lambda _pages: None)

        sensitive_line = OCRLine("王小明", [[0, 0], [100, 0], [100, 20], [0, 20]], 0.99)

        def fake_ocr(path, confidence_threshold=0.7):
            if "page2" in str(path) or "page_0002" in str(path):
                return OCRResult(text="王小明", lines=[sensitive_line])
            return OCRResult(text="plain", lines=[])

        def fake_redact(**kwargs):
            if "王小明" not in kwargs["text"]:
                return (
                    kwargs["text"],
                    {"entities": [], "occurrences": []},
                    {
                        "summary": {"total_entities": 0, "total_occurrences": 0, "by_entity_type": {}},
                        "residual_scan": {"passed": True, "findings": []},
                        "warnings": [],
                    },
                )
            return (
                "【姓名】",
                {
                    "entities": [{"id": "PERSON_1", "entity_type": "PERSON", "original": "王小明"}],
                    "occurrences": [{"entity_id": "PERSON_1", "original_start": 0, "original_end": 3}],
                },
                {
                    "summary": {"total_entities": 1, "total_occurrences": 1, "by_entity_type": {"PERSON": 1}},
                    "residual_scan": {"passed": True, "findings": []},
                    "warnings": [],
                },
            )

        monkeypatch.setattr(scan_module, "run_rapidocr", fake_ocr)
        monkeypatch.setattr(scan_module, "redact", fake_redact)
        monkeypatch.setattr(
            scan_module,
            "_write_redacted_scan_pdf",
            lambda _pages, path, dpi=200: Path(path).write_bytes(b"%PDF redacted"),
        )

        map_data, audit, _meta = scan_module.scan_redact_preserve_format(
            str(source),
            str(output),
            str(markdown),
            rules=[],
        )

        incomplete = tmp_path / "redacted.INCOMPLETE_DO_NOT_USE.pdf"
        assert not output.exists()
        assert incomplete.exists()
        assert markdown.exists()
        assert audit["verification"]["passed"] is False
        assert audit["verification"]["failed_pages"] == [2]
        assert map_data["redacted_file"] == incomplete.name

    def test_cli_writes_failed_audit_and_returns_nonzero(self, monkeypatch, tmp_path):
        import legal_desens.scan as scan_module
        from legal_desens.cli import main

        source = tmp_path / "source.pdf"
        output = tmp_path / "redacted.pdf"
        audit_path = tmp_path / "audit.json"
        map_path = tmp_path / "map.json"
        source.write_bytes(b"%PDF synthetic")

        def fake_preserve(**kwargs):
            incomplete = output.with_name("redacted.INCOMPLETE_DO_NOT_USE.pdf")
            incomplete.write_bytes(b"%PDF incomplete")
            Path(kwargs["markdown_path"]).write_text("【姓名】", encoding="utf-8")
            return (
                {"entities": [], "occurrences": [], "redacted_file": incomplete.name},
                {
                    "verification": {
                        "type": "redacted-pixels",
                        "passed": False,
                        "failed_pages": [2],
                        "failures": [{
                            "page": 2,
                            "entity_id": "PERSON_1",
                            "entity_type": "PERSON",
                            "category": "pixel_undercoverage",
                        }],
                    }
                },
                {"total_lines": 10, "low_confidence_lines": 0},
            )

        monkeypatch.setattr(scan_module, "scan_redact_preserve_format", fake_preserve)

        rc = main([
            "redact-scan",
            str(source),
            "--regex-only",
            "--out", str(output),
            "--audit", str(audit_path),
            "--map", str(map_path),
        ])

        assert rc == 1
        assert audit_path.exists()
        assert json.loads(audit_path.read_text(encoding="utf-8"))["verification"]["failed_pages"] == [2]


class TestOCRSingleton:
    """Test RapidOCR singleton behavior."""

    def test_singleton_returns_same_instance(self):
        from legal_desens.engine.ocr import get_rapidocr_instance, _rapidocr_instance
        # Reset singleton
        import legal_desens.engine.ocr as ocr_module
        ocr_module._rapidocr_instance = None

        try:
            inst1 = get_rapidocr_instance()
            inst2 = get_rapidocr_instance()
            assert inst1 is inst2
        finally:
            ocr_module._rapidocr_instance = None


class TestNEREngineSingleton:
    """Test NEREngine singleton behavior."""

    def test_singleton_returns_same_instance(self):
        from legal_desens.engine.ner import get_ner_engine_instance, _ner_engine_instance
        import legal_desens.engine.ner as ner_module

        # Skip if no model available
        try:
            inst1 = get_ner_engine_instance()
        except (FileNotFoundError, RuntimeError):
            pytest.skip("NER model not available")

        inst2 = get_ner_engine_instance()
        assert inst1 is inst2

        # Cleanup
        ner_module._ner_engine_instance = None
        ner_module._ner_engine_model_dir = None
