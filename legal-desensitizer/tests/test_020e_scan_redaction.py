"""020-E: Scan/image redaction tests."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def has_rapidocr():
    """Check if RapidOCR is available."""
    try:
        import rapidocr_onnxruntime
        return True
    except ImportError:
        return False


@pytest.fixture
def sample_image(has_rapidocr, tmp_path):
    """Create a simple test image with text."""
    if not has_rapidocr:
        pytest.skip("RapidOCR not installed")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        pytest.skip("Pillow not installed")

    img = Image.new("RGB", (400, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "Phone: 13800138000", fill="black")

    img_path = str(tmp_path / "test.png")
    img.save(img_path)
    return img_path


class TestScanRedaction:
    """Test scan/image redaction pipeline."""

    def test_rapidocr_available(self, has_rapidocr):
        """RapidOCR should be importable."""
        assert has_rapidocr

    def test_image_ocr(self, sample_image, has_rapidocr):
        """OCR should extract text from image."""
        if not has_rapidocr:
            pytest.skip("RapidOCR not installed")

        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
        result, _ = ocr(sample_image)
        assert result is not None
        # Should detect some text
        texts = [line[1] for line in result]
        text_combined = " ".join(texts)
        assert len(text_combined) > 0

    def test_scan_redact_pipeline(self, sample_image, tmp_path):
        """Full scan redact pipeline should work."""
        from legal_desens.rules import load_rules
        from legal_desens.scan import redact_scan_pixels
        output = tmp_path / "redacted.png"
        map_data, audit = redact_scan_pixels(sample_image, str(output), load_rules())
        assert output.exists()
        assert map_data["occurrences"]
        assert audit["verification"]["passed"] is True

        from PIL import Image
        with Image.open(output) as image:
            colors = image.convert("RGB").getcolors(maxcolors=1_000_000)
        assert colors is not None
        assert any(color == (255, 255, 255) for _count, color in colors)

    def test_preserve_format_keeps_markdown_intermediate(self, sample_image, tmp_path):
        from legal_desens.rules import load_rules
        from legal_desens.scan import scan_redact_preserve_format

        output = tmp_path / "redacted.png"
        markdown = tmp_path / "redacted.intermediate.md"
        map_data, audit, _meta = scan_redact_preserve_format(
            sample_image, str(output), str(markdown), load_rules()
        )

        assert output.exists()
        assert markdown.exists()
        assert map_data["verification"] == "redacted-pixels"
        assert map_data["intermediate_markdown_file"] == markdown.name
        assert audit["verification"]["passed"] is True


class TestScanRedactIrreversible:
    """Test that scan redaction is properly marked irreversible."""

    def test_map_marks_irreversible(self, sample_image, tmp_path):
        """Map should mark restore_supported: false."""
        from legal_desens.rules import load_rules
        from legal_desens.scan import redact_scan_pixels
        map_data, _audit = redact_scan_pixels(
            sample_image, str(tmp_path / "redacted.png"), load_rules()
        )
        assert map_data["restore_supported"] is False
        assert map_data["verification"] == "redacted-pixels"

    def test_residual_scan_passes(self, sample_image, tmp_path):
        """Residual scan should pass for recognized text."""
        from legal_desens.rules import load_rules
        from legal_desens.scan import redact_scan_pixels
        _map, audit = redact_scan_pixels(
            sample_image, str(tmp_path / "redacted.png"), load_rules()
        )
        assert audit["residual_scan"]["passed"] is True
