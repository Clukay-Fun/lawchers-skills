"""Tests for 010-mainstream-format-support: .md/.csv reversible, format matrix routing."""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.io import read_text, write_text
from legal_desens.rules import load_rules
from legal_desens.redact import redact

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


def _txt_redact_fn(text, rules, source_sha256, mode, level, model_dir):
    """Wrapper to call text redact engine with standard signature."""
    return redact(text, rules, source_sha256, mode, level, model_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# .md Reversible Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkdownRedactRestore:
    """Markdown redact -> restore round-trip tests (byte-level, same as .txt)."""

    def test_md_basic_redact_restore(self, rules, tmp_path):
        """Basic .md redact/restore with byte-level verification."""
        src = os.path.join(FIXTURES, "sample.md")
        redacted = str(tmp_path / "sample.redacted.md")
        restored = str(tmp_path / "sample.restored.md")
        map_path = str(tmp_path / "sample.map.json")

        # Read source
        tf = read_text(src)
        source_sha = tf.sha256

        # Redact
        redacted_text, map_data, audit_data = redact(
            text=tf.text,
            rules=rules,
            source_sha256=source_sha,
            mode="regex-only",
            level="strict",
        )

        # Compute redacted SHA with byte-level treatment
        redacted_bytes = redacted_text.encode("utf-8")
        if tf.has_bom:
            redacted_bytes = b"\xef\xbb\xbf" + redacted_bytes
        redacted_sha = hashlib.sha256(redacted_bytes).hexdigest()

        map_data["source_file"] = "sample.md"
        map_data["redacted_file"] = "sample.redacted.md"
        map_data["redacted_sha256"] = redacted_sha
        map_data["byte_metadata"] = {
            "encoding": "utf-8-sig" if tf.has_bom else "utf-8",
            "has_bom": tf.has_bom,
            "newline": tf.newline,
            "has_trailing_newline": tf.has_trailing_newline,
        }

        # Write redacted
        write_text(redacted, redacted_text, tf)

        # Verify entities detected
        assert len(map_data["entities"]) > 0
        assert len(map_data["occurrences"]) > 0

        # Save map
        with open(map_path, "w") as f:
            json.dump(map_data, f, ensure_ascii=False, indent=2)

        # Restore
        from legal_desens.restore import restore
        tf_redacted = read_text(redacted)
        restored_text = restore(
            redacted_text=tf_redacted.text,
            map_data=map_data,
            redacted_file_sha256=tf_redacted.sha256,
        )
        write_text(restored, restored_text, tf_redacted)

        # Byte-level verification
        assert tf.sha256 == read_text(restored).sha256, "MD round-trip byte mismatch"

    def test_md_with_bom(self, rules, tmp_path):
        """BOM-preserved .md round-trip."""
        src = os.path.join(FIXTURES, "with_bom.md")
        tf = read_text(src)
        assert tf.has_bom is True

        redacted = str(tmp_path / "bom.redacted.md")
        restored = str(tmp_path / "bom.restored.md")

        redacted_text, map_data, _ = redact(tf.text, rules, tf.sha256, mode="regex-only")

        redacted_bytes = redacted_text.encode("utf-8")
        if tf.has_bom:
            redacted_bytes = b"\xef\xbb\xbf" + redacted_bytes
        redacted_sha = hashlib.sha256(redacted_bytes).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        map_data["byte_metadata"] = {
            "has_bom": tf.has_bom,
            "newline": tf.newline,
            "has_trailing_newline": tf.has_trailing_newline,
        }

        write_text(redacted, redacted_text, tf)

        from legal_desens.restore import restore
        tf_redacted = read_text(redacted)
        restored_text = restore(tf_redacted.text, map_data, tf_redacted.sha256)
        write_text(restored, restored_text, tf_redacted)

        assert tf.sha256 == read_text(restored).sha256

    def test_md_crlf(self, rules, tmp_path):
        """CRLF-preserved .md round-trip."""
        src = os.path.join(FIXTURES, "crlf.md")
        tf = read_text(src)
        assert tf.newline == "\r\n"

        redacted = str(tmp_path / "crlf.redacted.md")
        restored = str(tmp_path / "crlf.restored.md")

        redacted_text, map_data, _ = redact(tf.text, rules, tf.sha256, mode="regex-only")

        redacted_bytes = redacted_text.encode("utf-8")
        if tf.has_bom:
            redacted_bytes = b"\xef\xbb\xbf" + redacted_bytes
        redacted_sha = hashlib.sha256(redacted_bytes).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        map_data["byte_metadata"] = {
            "has_bom": tf.has_bom,
            "newline": tf.newline,
            "has_trailing_newline": tf.has_trailing_newline,
        }

        write_text(redacted, redacted_text, tf)

        from legal_desens.restore import restore
        tf_redacted = read_text(redacted)
        restored_text = restore(tf_redacted.text, map_data, tf_redacted.sha256)
        write_text(restored, restored_text, tf_redacted)

        assert tf.sha256 == read_text(restored).sha256

    def test_md_no_trailing_newline(self, rules, tmp_path):
        """No trailing newline .md round-trip."""
        src = os.path.join(FIXTURES, "no_trailing_newline.md")
        tf = read_text(src)
        assert tf.has_trailing_newline is False

        redacted = str(tmp_path / "no_nl.redacted.md")
        restored = str(tmp_path / "no_nl.restored.md")

        redacted_text, map_data, _ = redact(tf.text, rules, tf.sha256, mode="regex-only")

        redacted_bytes = redacted_text.encode("utf-8")
        if tf.has_bom:
            redacted_bytes = b"\xef\xbb\xbf" + redacted_bytes
        redacted_sha = hashlib.sha256(redacted_bytes).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        map_data["byte_metadata"] = {
            "has_bom": tf.has_bom,
            "newline": tf.newline,
            "has_trailing_newline": tf.has_trailing_newline,
        }

        write_text(redacted, redacted_text, tf)

        from legal_desens.restore import restore
        tf_redacted = read_text(redacted)
        restored_text = restore(tf_redacted.text, map_data, tf_redacted.sha256)
        write_text(restored, restored_text, tf_redacted)

        assert tf.sha256 == read_text(restored).sha256


# ═══════════════════════════════════════════════════════════════════════════════
# .csv Reversible Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCSVRedactRestore:
    """CSV redact -> restore round-trip tests (byte-level)."""

    def test_csv_basic_redact_restore(self, rules, tmp_path):
        """Basic CSV redact/restore with byte-level verification."""
        from legal_desens.adapters.csv_adapter import csv_redact, csv_restore

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "sample.redacted.csv")
        restored = str(tmp_path / "sample.restored.csv")
        map_path = str(tmp_path / "sample.map.json")

        # Redact
        map_data, audit_data = csv_redact(
            source_path=src,
            redacted_path=redacted,
            redact_fn=_txt_redact_fn,
            rules=rules,
            mode="regex-only",
            level="strict",
        )

        assert map_data["schema_version"] == "1.1"
        assert map_data["document_type"] == "csv"
        assert map_data["verification"] == "byte"
        assert len(map_data["entities"]) > 0
        assert len(map_data["occurrences"]) > 0

        # Save map
        with open(map_path, "w") as f:
            json.dump(map_data, f, ensure_ascii=False, indent=2)

        # Restore
        csv_restore(redacted, restored, map_data)

        # Byte-level verification
        source_sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
        restored_sha = hashlib.sha256(open(restored, "rb").read()).hexdigest()
        assert source_sha == restored_sha, "CSV round-trip byte mismatch"

    def test_csv_shared_strings(self, rules, tmp_path):
        """CSV with shared strings (same name in multiple rows)."""
        from legal_desens.adapters.csv_adapter import csv_redact, csv_restore

        src = os.path.join(FIXTURES, "shared_strings.csv")
        redacted = str(tmp_path / "shared.redacted.csv")
        restored = str(tmp_path / "shared.restored.csv")

        map_data, _ = csv_redact(src, redacted, _txt_redact_fn, rules, mode="regex-only")

        # Verify entities detected
        phone_entities = [e for e in map_data["entities"] if e["entity_type"] == "PHONE"]
        assert len(phone_entities) > 0

        # Restore and verify
        csv_restore(redacted, restored, map_data)
        source_sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
        restored_sha = hashlib.sha256(open(restored, "rb").read()).hexdigest()
        assert source_sha == restored_sha

    def test_csv_quoted_fields(self, rules, tmp_path):
        """CSV with quoted fields containing commas and quotes."""
        from legal_desens.adapters.csv_adapter import csv_redact, csv_restore

        src = os.path.join(FIXTURES, "quoted_fields.csv")
        redacted = str(tmp_path / "quoted.redacted.csv")
        restored = str(tmp_path / "quoted.restored.csv")

        map_data, _ = csv_redact(src, redacted, _txt_redact_fn, rules, mode="regex-only")

        # Verify entities detected
        assert len(map_data["entities"]) > 0

        # Restore and verify
        csv_restore(redacted, restored, map_data)
        source_sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
        restored_sha = hashlib.sha256(open(restored, "rb").read()).hexdigest()
        assert source_sha == restored_sha

    def test_csv_empty_cells(self, rules, tmp_path):
        """CSV with empty cells should not crash."""
        from legal_desens.adapters.csv_adapter import csv_redact

        src = os.path.join(FIXTURES, "empty_cells.csv")
        redacted = str(tmp_path / "empty.redacted.csv")

        map_data, audit_data = csv_redact(src, redacted, _txt_redact_fn, rules, mode="regex-only")

        # Should not crash, phone should be redacted
        assert len(map_data["occurrences"]) > 0

    def test_csv_crlf_and_trailing_empty_cell_roundtrip(self, rules, tmp_path):
        """CSV CRLF line endings and trailing empty cells are byte-preserved."""
        from legal_desens.adapters.csv_adapter import csv_redact, csv_restore

        src = tmp_path / "crlf.csv"
        redacted = tmp_path / "crlf.redacted.csv"
        restored = tmp_path / "crlf.restored.csv"
        src.write_bytes("name,phone,note\r\n张三,13800138000,\r\n".encode("utf-8"))

        map_data, _ = csv_redact(
            str(src),
            str(redacted),
            _txt_redact_fn,
            rules,
            mode="regex-only",
        )
        csv_restore(str(redacted), str(restored), map_data)

        assert hashlib.sha256(src.read_bytes()).hexdigest() == hashlib.sha256(
            restored.read_bytes()
        ).hexdigest()
        assert b"\r\r\n" not in redacted.read_bytes()

    def test_csv_locator_is_csv_coordinate(self, rules, tmp_path):
        """Verify locator points to CSV cell coordinates."""
        from legal_desens.adapters.csv_adapter import csv_redact

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "redacted.csv")

        map_data, _ = csv_redact(src, redacted, _txt_redact_fn, rules, mode="regex-only")

        # All locators must have type=csv
        for occ in map_data["occurrences"]:
            loc = occ["locator"]
            assert loc["type"] == "csv"
            assert "row" in loc
            assert "column" in loc

    def test_csv_redacted_sha256_precheck(self, rules, tmp_path):
        """Restore must abort if redacted SHA-256 doesn't match."""
        from legal_desens.adapters.csv_adapter import csv_redact, csv_restore

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "redacted.csv")
        restored = str(tmp_path / "restored.csv")

        map_data, _ = csv_redact(src, redacted, _txt_redact_fn, rules, mode="regex-only")

        # Tamper with map
        map_data["redacted_sha256"] = "0" * 64

        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            csv_restore(redacted, restored, map_data)

    def test_csv_audit(self, rules, tmp_path):
        """CSV audit should produce proper schema."""
        from legal_desens.adapters.csv_adapter import csv_redact, csv_audit

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "redacted.csv")

        map_data, _ = csv_redact(src, redacted, _txt_redact_fn, rules, mode="regex-only")

        result = csv_audit(redacted, map_data, rules)
        assert result["schema_version"] == "1.1"
        assert result["document_type"] == "csv"
        assert "summary" in result
        assert "residual_scan" in result


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Format Routing Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLIRouting:
    """Test CLI format matrix routing: A reversible, B irreversible, C unsupported."""

    def test_cli_redact_md(self, tmp_path):
        """CLI redact command with .md file (A: reversible)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.md")
        out = str(tmp_path / "out.redacted.md")
        map_out = str(tmp_path / "map.json")
        audit_out = str(tmp_path / "audit.json")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
            "--map", map_out,
            "--audit", audit_out,
        ])
        assert ret == 0
        assert os.path.exists(out)
        assert os.path.exists(map_out)

    def test_cli_redact_csv(self, tmp_path):
        """CLI redact command with .csv file (A: reversible)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.csv")
        out = str(tmp_path / "out.redacted.csv")
        map_out = str(tmp_path / "map.json")
        audit_out = str(tmp_path / "audit.json")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
            "--map", map_out,
            "--audit", audit_out,
        ])
        assert ret == 0
        assert os.path.exists(out)
        assert os.path.exists(map_out)

    def test_cli_restore_md(self, tmp_path):
        """CLI restore command with .md file (A: reversible)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.md")
        redacted = str(tmp_path / "redacted.md")
        map_out = str(tmp_path / "map.json")
        restored = str(tmp_path / "restored.md")

        # Redact
        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        # Restore
        ret = main([
            "restore", redacted,
            "--map", map_out,
            "--out", restored,
        ])
        assert ret == 0

    def test_cli_restore_csv(self, tmp_path):
        """CLI restore command with .csv file (A: reversible)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "redacted.csv")
        map_out = str(tmp_path / "map.json")
        restored = str(tmp_path / "restored.csv")

        # Redact
        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        # Restore
        ret = main([
            "restore", redacted,
            "--map", map_out,
            "--out", restored,
        ])
        assert ret == 0

    def test_cli_audit_md(self, tmp_path):
        """CLI audit command with .md file."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.md")
        redacted = str(tmp_path / "redacted.md")
        map_out = str(tmp_path / "map.json")
        audit_out = str(tmp_path / "audit.json")

        # Redact first
        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        # Audit
        ret = main([
            "audit", redacted,
            "--map", map_out,
            "--out", audit_out,
        ])
        assert ret == 0
        assert os.path.exists(audit_out)

    def test_cli_audit_csv(self, tmp_path):
        """CLI audit command with .csv file."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "redacted.csv")
        map_out = str(tmp_path / "map.json")
        audit_out = str(tmp_path / "audit.json")

        # Redact first
        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        # Audit
        ret = main([
            "audit", redacted,
            "--map", map_out,
            "--out", audit_out,
        ])
        assert ret == 0
        assert os.path.exists(audit_out)

    def test_cli_audit_missing_map_returns_error(self, tmp_path):
        """CLI audit with missing map should return clean error, not traceback."""
        from legal_desens.cli import main

        src = str(tmp_path / "sample.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("联系电话 13800138000")

        ret = main([
            "audit", src,
            "--map", str(tmp_path / "missing.map.json"),
        ])
        assert ret == 1

    def test_cli_audit_invalid_map_json_returns_error(self, tmp_path):
        """CLI audit with invalid map JSON should return clean error."""
        from legal_desens.cli import main

        src = str(tmp_path / "sample.txt")
        bad_map = str(tmp_path / "bad.map.json")
        with open(src, "w", encoding="utf-8") as f:
            f.write("联系电话 13800138000")
        with open(bad_map, "w", encoding="utf-8") as f:
            f.write("{not json")

        ret = main([
            "audit", src,
            "--map", bad_map,
        ])
        assert ret == 1

    def test_cli_redact_pptx_irreversible(self, tmp_path):
        """CLI redact with .pptx should return irreversible error (B: route to 009)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.pptx")
        out = str(tmp_path / "out.pptx")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
        ])
        assert ret == 1

    def test_cli_redact_html_irreversible(self, tmp_path):
        """CLI redact with .html should return irreversible error (B: route to 009)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.html")
        out = str(tmp_path / "out.html")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
        ])
        assert ret == 1

    def test_cli_redact_doc_unsupported(self, tmp_path):
        """CLI redact with .doc should return unsupported error with conversion guidance (C)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.doc")
        out = str(tmp_path / "out.doc")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
        ])
        assert ret == 1

    def test_cli_redact_xls_unsupported(self, tmp_path):
        """CLI redact with .xls should return unsupported error with conversion guidance (C)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.xls")
        out = str(tmp_path / "out.xls")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
        ])
        assert ret == 1

    def test_cli_redact_unknown_ext(self, tmp_path):
        """CLI redact with unknown extension should return error."""
        from legal_desens.cli import main

        src = str(tmp_path / "file.xyz")
        with open(src, "w") as f:
            f.write("test")
        out = str(tmp_path / "out.xyz")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", out,
        ])
        assert ret == 1

    def test_cli_restore_pptx_irreversible(self, tmp_path):
        """CLI restore with .pptx should return irreversible error (B)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.pptx")
        map_out = str(tmp_path / "map.json")
        with open(map_out, "w") as f:
            json.dump({"source_sha256": "", "redacted_sha256": ""}, f)

        ret = main([
            "restore", src,
            "--map", map_out,
            "--out", str(tmp_path / "out.pptx"),
        ])
        assert ret == 1

    def test_cli_restore_doc_unsupported(self, tmp_path):
        """CLI restore with .doc should return unsupported error (C)."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.doc")
        map_out = str(tmp_path / "map.json")
        with open(map_out, "w") as f:
            json.dump({"source_sha256": "", "redacted_sha256": ""}, f)

        ret = main([
            "restore", src,
            "--map", map_out,
            "--out", str(tmp_path / "out.doc"),
        ])
        assert ret == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Existing Format Regression Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestExistingFormatRegression:
    """Verify existing txt/docx/xlsx behavior is not regressed."""

    def test_txt_redact_restore(self, rules, tmp_path):
        """TXT redact/restore still works."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.txt")
        redacted = str(tmp_path / "redacted.txt")
        map_out = str(tmp_path / "map.json")
        restored = str(tmp_path / "restored.txt")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        ret = main([
            "restore", redacted,
            "--map", map_out,
            "--out", restored,
        ])
        assert ret == 0

    def test_docx_redact_restore(self, rules, tmp_path):
        """DOCX redact/restore still works."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "docx", "sample.docx")
        redacted = str(tmp_path / "redacted.docx")
        map_out = str(tmp_path / "map.json")
        restored = str(tmp_path / "restored.docx")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        ret = main([
            "restore", redacted,
            "--map", map_out,
            "--out", restored,
        ])
        assert ret == 0

    def test_xlsx_redact_restore(self, rules, tmp_path):
        """XLSX redact/restore still works."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "xlsx", "sample.xlsx")
        redacted = str(tmp_path / "redacted.xlsx")
        map_out = str(tmp_path / "map.json")
        restored = str(tmp_path / "restored.xlsx")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        ret = main([
            "restore", redacted,
            "--map", map_out,
            "--out", restored,
        ])
        assert ret == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Map Schema Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMapSchema010:
    """Verify map schema for 010 formats."""

    def test_md_map_schema(self, rules, tmp_path):
        """MD map should have byte-level verification."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.md")
        redacted = str(tmp_path / "redacted.md")
        map_out = str(tmp_path / "map.json")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        with open(map_out, encoding="utf-8") as f:
            map_data = json.load(f)

        assert map_data["schema_version"] == "1.0"
        assert "byte_metadata" in map_data
        assert "entities" in map_data
        assert "occurrences" in map_data

    def test_csv_map_schema(self, rules, tmp_path):
        """CSV map should have byte-level verification and csv locator."""
        from legal_desens.cli import main

        src = os.path.join(FIXTURES, "sample.csv")
        redacted = str(tmp_path / "redacted.csv")
        map_out = str(tmp_path / "map.json")

        ret = main([
            "redact", src,
            "--regex-only",
            "--out", redacted,
            "--map", map_out,
        ])
        assert ret == 0

        with open(map_out, encoding="utf-8") as f:
            map_data = json.load(f)

        assert map_data["schema_version"] == "1.1"
        assert map_data["document_type"] == "csv"
        assert map_data["verification"] == "byte"
        assert "byte_metadata" in map_data
        assert "entities" in map_data
        assert "occurrences" in map_data

        for occ in map_data["occurrences"]:
            loc = occ["locator"]
            assert loc["type"] == "csv"
            assert "row" in loc
            assert "column" in loc
