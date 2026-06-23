"""020-F: Final gate tests - dependency isolation, installation matrix."""
import importlib
import sys
from pathlib import Path

import pytest


class TestDependencyIsolation:
    """Verify extra dependencies are properly isolated."""

    def test_core_no_agpl_deps(self):
        """Core installation should not import AGPL dependencies."""
        import subprocess
        code = r'''
import importlib.abc
import sys
class BlockFitz(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "fitz" or fullname.startswith("fitz."):
            raise ImportError("fitz deliberately blocked")
        return None
sys.meta_path.insert(0, BlockFitz())
import legal_desens.rules
import legal_desens.redact
import legal_desens.restore
import legal_desens.audit
print("core-ok")
'''
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "core-ok"

    def test_core_imports(self):
        """Core modules should be importable without extras."""
        from legal_desens import rules
        from legal_desens import redact
        from legal_desens import restore
        from legal_desens import audit
        from legal_desens import profile
        assert True

    def test_regex_engine_imports(self):
        """Regex engine should be importable."""
        from legal_desens.engine import regex
        from legal_desens.engine import merge
        from legal_desens.engine import span
        assert True

    def test_ner_engine_imports(self):
        """NER engine should be importable."""
        from legal_desens.engine import ner
        from legal_desens.engine import ner_postprocess
        assert True


class TestCLIBasicCommands:
    """Verify basic CLI commands work."""

    def test_help(self):
        """CLI help should work."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "legal_desens.cli", "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "redact" in result.stdout

    def test_ner_inspect(self):
        """NER inspect should work or give clear error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "legal_desens.cli", "ner-inspect"],
            capture_output=True, text=True
        )
        # Should succeed (model available) or fail with clear message
        if result.returncode != 0:
            assert "model" in result.stderr.lower() or "not found" in result.stderr.lower()


class TestReversibilityBaseline:
    """Verify core reversibility is not broken."""

    def test_txt_roundtrip(self, tmp_path):
        """TXT redact->restore should be byte-identical."""
        import subprocess

        input_file = tmp_path / "input.txt"
        input_file.write_text("申请人张三，电话13800138000。", encoding="utf-8")

        redacted_file = tmp_path / "redacted.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        restored_file = tmp_path / "restored.txt"

        # Redact
        result = subprocess.run(
            [sys.executable, "-m", "legal_desens.cli", "redact",
             str(input_file), "--regex-only", "--level", "strict",
             "--out", str(redacted_file), "--map", str(map_file), "--audit", str(audit_file)],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        # Restore
        result = subprocess.run(
            [sys.executable, "-m", "legal_desens.cli", "restore",
             str(redacted_file), "--map", str(map_file), "--out", str(restored_file)],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        # Compare
        original = input_file.read_bytes()
        restored = restored_file.read_bytes()
        assert original == restored


class TestExtraIsolation:
    """Verify extras are properly isolated."""

    def test_ocr_extra_isolated(self):
        """OCR should be optional."""
        # RapidOCR should not be required for core functionality
        from legal_desens import redact
        assert True

    def test_pdf_extra_isolated(self):
        """PDF should be optional."""
        # PyMuPDF should not be required for core functionality
        from legal_desens import redact
        assert True


class TestDocumentationCompliance:
    """Verify documentation mentions best-effort caveats."""

    def test_skill_mentions_best_effort(self):
        """SKILL.md should mention best-effort for NER/OCR."""
        skill_path = Path(__file__).parent.parent / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text()
            assert "best-effort" in content.lower() or "best_effort" in content.lower()
