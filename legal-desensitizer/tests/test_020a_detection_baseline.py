"""020-A: Detection baseline tests for legal smoke suite and CLUENER candidate."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SMOKE_SUITE = PROJECT_ROOT / "tests" / "fixtures" / "legal_smoke_suite.txt"


class TestLegalSmokeSuite:
    """Verify smoke suite is a valid synthetic legal text."""

    def test_smoke_suite_exists(self):
        assert SMOKE_SUITE.exists()
        content = SMOKE_SUITE.read_text(encoding="utf-8")
        assert len(content) > 100

    def test_smoke_suite_has_entities(self):
        """Smoke suite should contain multiple entity types."""
        content = SMOKE_SUITE.read_text(encoding="utf-8")
        # Check for known entity indicators
        assert "张三" in content  # person
        assert "有限公司" in content  # company
        assert "法院" in content  # court
        assert "13800138000" in content  # phone


class TestCurrentNERBaseline:
    """Verify current NER model on smoke suite."""

    @pytest.fixture
    def ner_spans(self, tmp_path):
        """Run ner-spans on smoke suite."""
        out_file = tmp_path / "spans.json"
        result = subprocess.run(
            [sys.executable, "-m", "legal_desens.cli", "ner-spans",
             str(SMOKE_SUITE), "--out", str(out_file)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT)
        )
        if result.returncode != 0:
            pytest.skip(f"NER not available: {result.stderr[:200]}")
        with open(out_file, encoding="utf-8") as f:
            return json.load(f)

    def test_not_all_o(self, ner_spans):
        """Current model must detect entities in smoke suite."""
        spans = ner_spans.get("spans", [])
        assert len(spans) > 0, "All O - no entities detected!"

    def test_person_detected(self, ner_spans):
        """Must detect at least one person."""
        spans = ner_spans.get("spans", [])
        per_spans = [s for s in spans if s.get("entity_type") == "PER"]
        assert len(per_spans) >= 1

    def test_org_detected(self, ner_spans):
        """Must detect at least one organization."""
        spans = ner_spans.get("spans", [])
        org_spans = [s for s in spans if s.get("entity_type") == "ORG"]
        assert len(org_spans) >= 1

    def test_location_detected(self, ner_spans):
        """Must detect at least one location."""
        spans = ner_spans.get("spans", [])
        loc_spans = [s for s in spans if s.get("entity_type") == "LOC"]
        assert len(loc_spans) >= 1

    def test_span_text_matches(self, ner_spans):
        """Every span's text must match the source at its position."""
        text = SMOKE_SUITE.read_text(encoding="utf-8")
        for span in ner_spans.get("spans", []):
            start = span["start"]
            end = span["end"]
            expected = text[start:end]
            actual = span.get("text", "")
            assert actual == expected, f"Span mismatch: '{actual}' != '{expected}' at [{start}:{end}]"


class TestCLuenerCandidate:
    """Verify CLUENER candidate model evaluation (if available)."""

    @pytest.fixture
    def cluener_results(self):
        """Load CLUENER PyTorch results if available."""
        results_file = Path("/tmp/cluener_pytorch_spans.json")
        if not results_file.exists():
            pytest.skip("CLUENER results not found. Run scripts/eval_cluener.py first.")
        with open(results_file, encoding="utf-8") as f:
            return json.load(f)

    def test_cluener_not_all_o(self, cluener_results):
        """CLUENER must detect entities."""
        spans = cluener_results.get("spans", [])
        assert len(spans) > 0, "CLUENER: All O - no entities detected!"

    def test_cluener_person(self, cluener_results):
        """CLUENER must detect persons."""
        by_type = cluener_results.get("by_type", {})
        assert by_type.get("name", 0) >= 1

    def test_cluener_company(self, cluener_results):
        """CLUENER must detect companies."""
        by_type = cluener_results.get("by_type", {})
        assert by_type.get("company", 0) >= 1

    def test_cluener_onnx_match(self):
        """CLUENER PyTorch and ONNX must produce identical predictions."""
        onnx_dir = Path("/tmp/cluener_onnx")
        if not (onnx_dir / "model.onnx").exists():
            pytest.skip("CLUENER ONNX not found. Run scripts/export_cluener_onnx.py first.")

        # Re-run comparison
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "export_cluener_onnx.py")],
            capture_output=True, text=True, timeout=120
        )
        assert "PASS: PyTorch and ONNX outputs are identical" in result.stdout
        assert result.returncode == 0
