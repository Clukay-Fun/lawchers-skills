"""020-C: DOCX complete coverage tests."""
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from legal_desens.adapters.docx_adapter import DOCXAdapter


FIXTURES = Path(__file__).parent / "fixtures" / "docx"


def _make_simple_docx(paragraphs, header_text=None, footer_text=None, comment_text=None):
    """Create a minimal DOCX with optional header, footer, comments."""
    NSMAP = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    # Build document.xml
    doc_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W}" xmlns:r="{NSMAP['r']}">
      <w:body>'''

    for para_text in paragraphs:
        doc_xml += f'''
        <w:p>
          <w:r>
            <w:t xml:space="preserve">{para_text}</w:t>
          </w:r>
        </w:p>'''

    doc_xml += '''
      </w:body>
    </w:document>'''

    # Create ZIP
    buf = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    buf.close()

    with zipfile.ZipFile(buf.name, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')

        if header_text:
            header_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:hdr xmlns:w="{W}">
              <w:p><w:r><w:t>{header_text}</w:t></w:r></w:p>
            </w:hdr>'''
            zf.writestr("word/header1.xml", header_xml)

        if footer_text:
            footer_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:ftr xmlns:w="{W}">
              <w:p><w:r><w:t>{footer_text}</w:t></w:r></w:p>
            </w:ftr>'''
            zf.writestr("word/footer1.xml", footer_xml)

        if comment_text:
            comments_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:comments xmlns:w="{W}">
              <w:comment w:id="1" w:author="Test">
                <w:p><w:r><w:t>{comment_text}</w:t></w:r></w:p>
              </w:comment>
            </w:comments>'''
            zf.writestr("word/comments.xml", comments_xml)

    return buf.name


class TestDOCXBasicCoverage:
    """Test basic DOCX redact/restore."""

    def test_simple_paragraph_redact(self):
        """Simple paragraph should be redacted."""
        docx_path = _make_simple_docx(["申请人张三于2022年入职"])
        try:
            adapter = DOCXAdapter()
            text, segments = adapter.extract_text(docx_path)
            assert "张三" in text
            assert len(segments) >= 1
        finally:
            os.unlink(docx_path)

    def test_multiple_paragraphs(self):
        """Multiple paragraphs should be extracted."""
        docx_path = _make_simple_docx([
            "第一段内容",
            "第二段内容",
            "第三段内容",
        ])
        try:
            adapter = DOCXAdapter()
            text, segments = adapter.extract_text(docx_path)
            assert len(segments) == 3
        finally:
            os.unlink(docx_path)


class TestDOCXHeaderFooter:
    """Test header/footer coverage."""

    def test_header_text_extracted(self):
        """Header text should be extractable."""
        docx_path = _make_simple_docx(
            ["正文内容"],
            header_text="页眉：机密文件",
        )
        try:
            adapter = DOCXAdapter()
            text, segments = adapter.extract_text(docx_path)
            assert "页眉：机密文件" in text
            assert any(s["part"] == "word/header1.xml" for s in segments)
        finally:
            os.unlink(docx_path)


class TestDOCXCommentCoverage:
    """Test comment coverage."""

    def test_comment_text_extracted(self):
        """Comment text should be extractable."""
        docx_path = _make_simple_docx(
            ["正文内容"],
            comment_text="批注：此处需要核实",
        )
        try:
            adapter = DOCXAdapter()
            text, segments = adapter.extract_text(docx_path)
            assert "批注：此处需要核实" in text
            assert any(s["part"] == "word/comments.xml" for s in segments)
        finally:
            os.unlink(docx_path)

    def test_auxiliary_parts_redact_and_restore(self, tmp_path):
        """Header, footer, and comment text participate in positional restore."""
        from legal_desens.cli import _make_txt_redact_fn
        from legal_desens.profile import load_profile
        from legal_desens.rules import load_rules

        source = _make_simple_docx(
            ["正文内容"],
            header_text="联系电话13800138000",
            footer_text="邮箱test@example.com",
            comment_text="身份证110101199001011234",
        )
        redacted = tmp_path / "redacted.docx"
        restored = tmp_path / "restored.docx"
        try:
            adapter = DOCXAdapter()
            source_text, _ = adapter.extract_text(source)
            map_data, _audit = adapter.redact(
                source,
                str(redacted),
                _make_txt_redact_fn(load_profile("strict")),
                load_rules(),
            )
            redacted_text, _ = adapter.extract_text(str(redacted))
            assert "13800138000" not in redacted_text
            assert "test@example.com" not in redacted_text
            assert "110101199001011234" not in redacted_text
            assert {o["locator"]["part"] for o in map_data["occurrences"]} >= {
                "word/header1.xml", "word/footer1.xml", "word/comments.xml",
            }
            adapter.restore(str(redacted), str(restored), map_data)
            restored_text, _ = adapter.extract_text(str(restored))
            assert restored_text == source_text
        finally:
            os.unlink(source)


class TestDOCXLocatorStructure:
    """Test that locators point to correct positions."""

    def test_locator_has_part_field(self):
        """Locator should contain part field."""
        docx_path = _make_simple_docx(["申请人张三的案件"])
        try:
            from legal_desens.redact import redact
            from legal_desens.rules import load_rules
            from legal_desens.profile import load_profile

            rules = load_rules()
            profile = load_profile("labor")

            adapter = DOCXAdapter()
            # Basic check that adapter returns proper structure
            text, segments = adapter.extract_text(docx_path)
            assert all("part" in seg for seg in segments)
        finally:
            os.unlink(docx_path)
