"""Regression tests for the review preparation pipeline."""

from pathlib import Path

import pytest


def _hybrid_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    first = doc.new_page()
    first.insert_text((50, 80), "page one 13800138000")
    doc.new_page()  # image-only page; OCR is mocked below
    third = doc.new_page()
    third.insert_text((50, 80), "page three 110101199001011234")
    path = tmp_path / "hybrid.pdf"
    doc.save(path)
    doc.close()
    return path


def test_hybrid_pdf_preserves_page_order_polygon_and_temp_cleanup(tmp_path, monkeypatch):
    from legal_desens.engine.ocr import OCRLine, OCRResult
    from legal_desens.prepare import _prepare_text_pdf
    from legal_desens.profile import load_profile

    seen_temp_paths = []
    polygon = [[1, 2], [30, 2], [30, 12], [1, 12]]

    monkeypatch.setattr("legal_desens.engine.ocr.get_rapidocr_instance", lambda: object())

    def fake_ocr(image_path, confidence_threshold, engine):
        seen_temp_paths.append(image_path)
        assert Path(image_path).exists()
        line = OCRLine("page two OCR", polygon, 0.98)
        return OCRResult(text=line.text, lines=[line])

    monkeypatch.setattr("legal_desens.engine.ocr.run_rapidocr", fake_ocr)

    blocks, full_text, document_kind = _prepare_text_pdf(
        str(_hybrid_pdf(tmp_path)), [], load_profile("strict"), "regex-only"
    )

    assert document_kind == "pdf-hybrid"
    assert [block["sourceLocator"]["page"] for block in blocks] == [1, 2, 3]
    assert [block["sourceLocator"]["type"] for block in blocks] == [
        "pdf-text", "pdf-scan", "pdf-text"
    ]
    assert blocks[1]["sourceLocator"]["polygon"] == polygon
    assert full_text.index("page one") < full_text.index("page two") < full_text.index("page three")
    assert seen_temp_paths and all(not Path(path).exists() for path in seen_temp_paths)


def test_hybrid_pdf_cleans_temp_image_when_ocr_fails(tmp_path, monkeypatch):
    from legal_desens.prepare import _prepare_text_pdf
    from legal_desens.profile import load_profile

    seen_temp_paths = []
    monkeypatch.setattr("legal_desens.engine.ocr.get_rapidocr_instance", lambda: object())

    def failing_ocr(image_path, confidence_threshold, engine):
        seen_temp_paths.append(image_path)
        raise RuntimeError("synthetic OCR failure")

    monkeypatch.setattr("legal_desens.engine.ocr.run_rapidocr", failing_ocr)

    with pytest.raises(RuntimeError, match="synthetic OCR failure"):
        _prepare_text_pdf(
            str(_hybrid_pdf(tmp_path)), [], load_profile("strict"), "regex-only"
        )

    assert seen_temp_paths and all(not Path(path).exists() for path in seen_temp_paths)
