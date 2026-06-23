"""020-D: Text-layer PDF redaction tests."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def has_pymupdf():
    """Check if PyMuPDF is available."""
    try:
        import fitz
        return True
    except ImportError:
        return False


@pytest.fixture
def sample_text_pdf(has_pymupdf, tmp_path):
    """Create a simple text-layer PDF for testing."""
    if not has_pymupdf:
        pytest.skip("PyMuPDF not installed")

    import fitz

    pdf_path = str(tmp_path / "sample.pdf")
    doc = fitz.open()
    page = doc.new_page()
    # Use English text to avoid font issues
    page.insert_text((100, 100), "Applicant: Zhang San, ID: 110101199001011234")
    page.insert_text((100, 150), "Phone: 13800138000, Account: 6225880112345678")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


class TestTextPDFDetection:
    """Test text-layer PDF detection."""

    def test_text_pdf_has_text(self, sample_text_pdf):
        """Text PDF should have extractable text."""
        import fitz
        doc = fitz.open(sample_text_pdf)
        page = doc[0]
        text = page.get_text()
        doc.close()
        assert "Zhang San" in text
        assert "13800138000" in text

    def test_text_pdf_has_chars(self, sample_text_pdf):
        """Text PDF should have character-level info."""
        import fitz
        doc = fitz.open(sample_text_pdf)
        page = doc[0]
        chars = page.get_text("rawdict")["blocks"]
        doc.close()
        assert len(chars) > 0


class TestTextPDFRedaction:
    """Test text-layer PDF permanent redaction."""

    def _redact(self, source, output):
        from legal_desens.adapters.pdf_adapter import redact_text_pdf
        from legal_desens.cli import _make_txt_redact_fn
        from legal_desens.profile import load_profile
        from legal_desens.rules import load_rules
        return redact_text_pdf(
            source,
            str(output),
            load_rules(),
            _make_txt_redact_fn(load_profile("strict")),
        )

    def test_redact_removes_text(self, sample_text_pdf, tmp_path):
        """Redaction should remove sensitive text from PDF."""
        output = tmp_path / "redacted.pdf"
        self._redact(sample_text_pdf, output)
        import fitz
        doc = fitz.open(output)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        assert "13800138000" not in text
        assert "110101199001011234" not in text
        assert "手机号" in text

    def test_redact_residual_scan(self, sample_text_pdf, tmp_path):
        """Residual scan should pass after redaction."""
        _map, audit = self._redact(sample_text_pdf, tmp_path / "redacted.pdf")
        assert audit["residual_scan"]["passed"] is True
        assert audit["verification"]["passed"] is True

    def test_redact_map_irreversible(self, sample_text_pdf, tmp_path):
        """Map should mark restore_supported: false."""
        map_data, _audit = self._redact(sample_text_pdf, tmp_path / "redacted.pdf")
        assert map_data["restore_supported"] is False
        assert map_data["verification"] == "redacted-content"
