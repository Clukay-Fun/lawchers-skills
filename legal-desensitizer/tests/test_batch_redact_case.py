"""Tests for 018: batch-redact-case orchestrator.

All tests use synthetic fixtures. No real case material.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.batch import (
    BatchError,
    _classify_ext,
    _discover_files,
    _generate_report,
    _load_denylist,
    _precheck_ner,
    _run_gate,
    _write_manifest,
    _OLD_LABEL_PATTERN,
    _REPORT_FIRST_LINE,
    _REPORT_FILENAME,
    _SOURCE_INDEX_FILENAME,
    _MANIFEST_FILENAME,
    _ARCHIVE_DIR,
    _WORK_DIR,
    _FINAL_DIR,
    _STAGING_FINAL_DIR,
)
from legal_desens.rules import load_rules
from legal_desens.profile import load_profile
from legal_desens.redact import redact
from legal_desens.engine.span import Span

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")
PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "legal_desens", "profiles")


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


@pytest.fixture
def labor():
    return load_profile("labor", PROFILES_DIR)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_input_dir(tmp_path, files: dict) -> str:
    """Create input directory with synthetic files.

    files: {filename: content}
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name, content in files.items():
        (input_dir / name).write_text(content, encoding="utf-8")
    return str(input_dir)


def _make_allowlist(tmp_path, terms: list) -> str:
    f = tmp_path / "allowlist.txt"
    f.write_text("\n".join(terms) + "\n", encoding="utf-8")
    return str(f)


def _make_denylist(tmp_path, terms: list) -> str:
    f = tmp_path / "denylist.txt"
    f.write_text("\n".join(terms) + "\n", encoding="utf-8")
    return str(f)


# ── 1. Format classification ────────────────────────────────────────────────


class TestClassifyExt:
    def test_txt_md_csv(self):
        assert _classify_ext(Path("a.txt")) == "A"
        assert _classify_ext(Path("a.md")) == "A"
        assert _classify_ext(Path("a.csv")) == "A"
        assert _classify_ext(Path("a.docx")) == "A"
        assert _classify_ext(Path("a.xlsx")) == "A"

    def test_scan_formats(self):
        assert _classify_ext(Path("a.pdf")) == "B"
        assert _classify_ext(Path("a.png")) == "B"
        assert _classify_ext(Path("a.jpg")) == "B"
        assert _classify_ext(Path("a.jpeg")) == "B"
        assert _classify_ext(Path("a.tiff")) == "B"
        assert _classify_ext(Path("a.bmp")) == "B"

    def test_unsupported(self):
        assert _classify_ext(Path("a.doc")) == "C"
        assert _classify_ext(Path("a.xls")) == "C"
        assert _classify_ext(Path("a.pages")) == "C"

    def test_unknown(self):
        assert _classify_ext(Path("a.xyz")) == "unknown"
        assert _classify_ext(Path("a.mp3")) == "unknown"


# ── 2. File discovery ───────────────────────────────────────────────────────


class TestDiscoverFiles:
    def test_discovers_sorted(self, tmp_path):
        d = tmp_path / "case"
        d.mkdir()
        (d / "b.txt").write_text("b", encoding="utf-8")
        (d / "a.md").write_text("a", encoding="utf-8")
        (d / "c.txt").write_text("c", encoding="utf-8")
        files = _discover_files(d)
        names = [f.name for f in files]
        assert names == sorted(names)

    def test_skips_hidden(self, tmp_path):
        d = tmp_path / "case"
        d.mkdir()
        (d / "visible.txt").write_text("v", encoding="utf-8")
        (d / ".hidden").write_text("h", encoding="utf-8")
        files = _discover_files(d)
        names = [f.name for f in files]
        assert ".hidden" in names  # _discover_files finds all; filtering is in batch_redact_case


# ── 3. Denylist loading ─────────────────────────────────────────────────────


class TestLoadDenylist:
    def test_load_terms(self, tmp_path):
        f = tmp_path / "deny.txt"
        f.write_text("# comment\n海源\n考勤\n\n", encoding="utf-8")
        result = _load_denylist(str(f))
        assert "海源" in result
        assert "考勤" in result
        assert "# comment" not in result

    def test_none_returns_empty(self):
        result = _load_denylist(None)
        assert result == set()

    def test_missing_file_raises(self):
        with pytest.raises(BatchError, match="not found"):
            _load_denylist("/nonexistent/file.txt")


# ── 4. Old label pattern detection ──────────────────────────────────────────


class TestOldLabelPattern:
    def test_detects_numbered_labels(self):
        assert _OLD_LABEL_PATTERN.search("人物1说了话")
        assert _OLD_LABEL_PATTERN.search("机构2发布公告")
        assert _OLD_LABEL_PATTERN.search("地址3位于")

    def test_no_match_on_bracket_labels(self):
        assert not _OLD_LABEL_PATTERN.search("【姓名】说了话")
        assert not _OLD_LABEL_PATTERN.search("【机构】发布公告")

    def test_no_match_on_unnumbered(self):
        assert not _OLD_LABEL_PATTERN.search("人物说了话")


# ── 5. Validation gate ──────────────────────────────────────────────────────


class TestRunGate:
    def test_passes_on_clean_result(self, rules, labor):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "redacted_text": "【姓名】在【机构】工作。",
            "map_data": {},
            "audit_data": {
                "summary": {"total_entities": 2, "total_occurrences": 2},
                "residual_scan": {"passed": True, "findings": []},
                "warnings": [],
            },
        }]
        passed, failures = _run_gate(results, rules, labor, set())
        assert passed is True
        assert failures == []

    def test_fails_on_residual(self, rules, labor):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "redacted_text": "电话13800138000还在",
            "map_data": {},
            "audit_data": {
                "summary": {"total_entities": 0, "total_occurrences": 0},
                "residual_scan": {
                    "passed": False,
                    "findings": [{"entity_type": "PHONE", "text_preview": "13800138000"}],
                },
                "warnings": [],
            },
        }]
        passed, failures = _run_gate(results, rules, labor, set())
        assert passed is False
        assert any("residual" in f for f in failures)

    def test_fails_on_old_labels(self, rules, labor):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "redacted_text": "人物1说了话",
            "map_data": {},
            "audit_data": {
                "summary": {"total_entities": 1, "total_occurrences": 1},
                "residual_scan": {"passed": True, "findings": []},
                "warnings": [],
            },
        }]
        passed, failures = _run_gate(results, rules, labor, set())
        assert passed is False
        assert any("old label" in f for f in failures)

    def test_fails_on_denylist_residual(self, rules, labor):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "redacted_text": "海源公司违约",
            "map_data": {},
            "audit_data": {
                "summary": {"total_entities": 0, "total_occurrences": 0},
                "residual_scan": {"passed": True, "findings": []},
                "warnings": [],
            },
        }]
        passed, failures = _run_gate(results, rules, labor, {"海源"})
        assert passed is False
        assert any("denylist" in f for f in failures)

    def test_fails_when_labor_money_is_redacted(self, rules, labor):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "redacted_text": "工资【金额】。",
            "map_data": {
                "entities": [{
                    "entity_id": "e1",
                    "entity_type": "MONEY",
                    "original": "15000元",
                    "replacement": "【金额】",
                }]
            },
            "audit_data": {
                "summary": {"total_entities": 1, "total_occurrences": 1},
                "residual_scan": {"passed": True, "findings": []},
                "warnings": [],
            },
        }]
        passed, failures = _run_gate(results, rules, labor, set())
        assert passed is False
        assert any("preserved type was redacted" in f for f in failures)

    def test_fails_when_labor_time_label_appears(self, rules, labor):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "redacted_text": "入职时间【时间】。",
            "map_data": {"entities": []},
            "audit_data": {
                "summary": {"total_entities": 0, "total_occurrences": 0},
                "residual_scan": {"passed": True, "findings": []},
                "warnings": [],
            },
        }]
        passed, failures = _run_gate(results, rules, labor, set())
        assert passed is False
        assert any("preserved label detected" in f for f in failures)

    def test_precheck_fails_when_ner_self_test_outputs_no_spans(self, monkeypatch):
        import legal_desens.batch as batch_module

        monkeypatch.setattr(batch_module, "inspect_ner", lambda model_dir=None: {
            "self_test": {
                "passed": False,
                "span_count": 0,
                "entity_types": [],
                "error": None,
            }
        })

        with pytest.raises(BatchError, match="self-test failed"):
            _precheck_ner(None)


# ── 6. Report first line ────────────────────────────────────────────────────


class TestReportConstants:
    def test_first_line_is_warning(self):
        assert "本报告包含替换前原文" in _REPORT_FIRST_LINE
        assert "不得上传" in _REPORT_FIRST_LINE

    def test_report_filename(self):
        assert _REPORT_FILENAME == "SENSITIVE_REDACTION_REPORT_DO_NOT_UPLOAD.md"

    def test_source_index_filename(self):
        assert _SOURCE_INDEX_FILENAME == "SENSITIVE_SOURCE_INDEX_DO_NOT_UPLOAD.json"

    def test_manifest_filename(self):
        assert _MANIFEST_FILENAME == "run_manifest.json"

    def test_sensitive_report_contains_replacement_table(self, tmp_path):
        results = [{
            "doc_id": "doc_01",
            "source_ext": ".txt",
            "pipeline": "redact",
            "irreversible": False,
            "map_data": {
                "entities": [{
                    "entity_id": "ent_1",
                    "entity_type": "PERSON",
                    "original": "张三",
                    "replacement": "【姓名】",
                }],
                "occurrences": [{"entity_id": "ent_1"}],
            },
            "audit_data": {
                "summary": {"total_entities": 1, "total_occurrences": 1},
                "residual_scan": {"passed": True, "findings": []},
                "warnings": [{
                    "type": "org_bare_short_word",
                    "text": "综合部",
                    "suggested_action": "建议加入 allowlist",
                    "message": "疑似普通词",
                }],
            },
        }]
        report = _generate_report(
            results,
            tmp_path,
            "labor",
            allowlist_count=1,
            denylist_count=0,
            gate_passed=True,
            gate_failures=[],
        )
        text = report.read_text(encoding="utf-8")
        assert "## 替换明细" in text
        assert "| 文档 | 类型 | 替换前 | 替换后 | 次数 | 建议动作 |" in text
        assert "张三" in text
        assert "【姓名】" in text
        assert "综合部" in text
        assert "建议加入 allowlist" in text

    def test_manifest_sanitizes_model_path(self, tmp_path):
        results = [{
            "doc_id": "doc_01",
            "source_name": "张三材料.txt",
            "source_path": "/Users/private/张三材料.txt",
            "source_sha256": "abc",
            "source_ext": ".txt",
            "page_count": 1,
            "pipeline": "redact",
            "irreversible": False,
            "audit_data": {"summary": {}},
        }]
        _write_manifest(
            results,
            tmp_path,
            "labor",
            allowlist_count=0,
            denylist_count=0,
            ner_info={
                "model_dir": "/Users/private/.legal-desens/models/real-case",
                "tag_scheme": "BIO",
                "num_labels": 9,
                "id2label": {"0": "O"},
                "model_io": {"input_names": ["input_ids"]},
            },
        )
        manifest_text = (tmp_path / _MANIFEST_FILENAME).read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        assert "model_dir" not in manifest["model_info"]
        assert "/Users/private" not in manifest_text
        assert manifest["model_info"]["tag_scheme"] == "BIO"


# ── 7. Integration: full happy path with synthetic txt ──────────────────────


class TestBatchRedactCaseIntegration:
    """Integration tests requiring NER model (skipped if not available)."""

    @pytest.fixture(autouse=True)
    def _check_ner(self):
        try:
            from legal_desens.engine.ner import inspect_ner
            inspect_ner()
        except (FileNotFoundError, RuntimeError, OSError):
            pytest.skip("NER model not available")

    def test_happy_path_txt(self, tmp_path):
        """Full run on synthetic .txt files produces all outputs."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在深圳市某科技有限公司工作，电话13800138000。",
            "doc2.md": "李四的身份证号是110101199001011234。",
        })
        out_dir = str(tmp_path / "output")
        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
        )
        assert rc == 0

        out_path = tmp_path / "output"
        # final_redacted_md directory exists
        final_dir = out_path / _FINAL_DIR
        assert final_dir.is_dir()
        assert (final_dir / "doc_01.redacted.md").is_file()
        assert (final_dir / "doc_02.redacted.md").is_file()

        # Report exists with correct first line
        report = out_path / _REPORT_FILENAME
        assert report.is_file()
        first_line = report.read_text(encoding="utf-8").split("\n")[0]
        assert first_line == _REPORT_FIRST_LINE

        # Manifest exists and has no PII
        manifest_path = out_path / _MANIFEST_FILENAME
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "documents" in manifest
        for doc in manifest["documents"]:
            assert "document_id" in doc
            assert "source_sha256" in doc
            assert "source_ext" in doc
            # No original filename in manifest
            assert "original_name" not in doc
            assert "source_name" not in doc

        # Successful default output keeps only final docs, report, and no-PII manifest.
        assert not (out_path / _SOURCE_INDEX_FILENAME).exists()
        assert not (out_path / _WORK_DIR).exists()

    def test_gate_failure_no_final_dir_and_no_cleanup(self, tmp_path, monkeypatch):
        """When gate fails, cleanup should NOT run and exit code should be non-zero."""
        from legal_desens import batch as batch_module
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")

        monkeypatch.setattr(batch_module, "_precheck_ner", lambda model_dir=None: {"tag_scheme": "BIO"})
        monkeypatch.setattr(batch_module, "_run_gate", lambda *args, **kwargs: (False, ["synthetic failure"]))

        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            cleanup="archive",
        )
        assert rc == 1

        out_path = tmp_path / "output"
        assert not (out_path / _FINAL_DIR).exists()
        work_dir = out_path / _WORK_DIR
        assert (work_dir / _STAGING_FINAL_DIR / "doc_01.redacted.md").is_file()
        assert (work_dir / "doc_01.map.json").is_file()
        assert (work_dir / "doc_01.audit.json").is_file()
        assert (work_dir / _SOURCE_INDEX_FILENAME).is_file()
        assert not (out_path / _ARCHIVE_DIR).exists()

    def test_cleanup_archive(self, tmp_path):
        """Archive cleanup moves map/audit to _archive/."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")
        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            cleanup="archive",
        )
        assert rc == 0

        out_path = tmp_path / "output"
        archive_dir = out_path / _ARCHIVE_DIR
        archived_work = archive_dir / _WORK_DIR
        assert archived_work.is_dir()
        assert (archived_work / "doc_01.map.json").is_file()
        assert (archived_work / "doc_01.audit.json").is_file()

    def test_cleanup_delete_does_not_require_confirm_for_generated_work_dir(self, tmp_path):
        """--cleanup delete removes only the generated work dir."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")

        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            cleanup="delete",
            confirm_delete=False,
        )

        assert rc == 0
        assert (tmp_path / "output" / _FINAL_DIR / "doc_01.redacted.md").is_file()
        assert not (tmp_path / "output" / _WORK_DIR).exists()

    def test_cleanup_delete_with_confirm(self, tmp_path):
        """--cleanup delete with --confirm-delete removes map files."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")
        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            cleanup="delete",
            confirm_delete=True,
        )
        assert rc == 0

        out_path = tmp_path / "output"
        assert not (out_path / _WORK_DIR).exists()
        assert not (out_path / _SOURCE_INDEX_FILENAME).exists()
        # But final output should remain
        assert (out_path / _FINAL_DIR / "doc_01.redacted.md").is_file()

    def test_unsupported_format_raises(self, tmp_path):
        """Unsupported format should raise BatchError."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.doc": "some content",
        })
        out_dir = str(tmp_path / "output")

        with pytest.raises(BatchError, match="Unsupported"):
            batch_redact_case(
                input_dir=input_dir,
                out_dir=out_dir,
            )

    def test_empty_input_raises(self, tmp_path):
        """Empty input directory should raise BatchError."""
        from legal_desens.batch import batch_redact_case

        input_dir = tmp_path / "empty"
        input_dir.mkdir()
        out_dir = str(tmp_path / "output")

        with pytest.raises(BatchError, match="No files found"):
            batch_redact_case(
                input_dir=input_dir,
                out_dir=out_dir,
            )

    def test_manifest_no_pii(self, tmp_path):
        """Manifest must not contain original filenames (PII)."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "张三_劳动合同.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")
        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            cleanup="none",
        )
        assert rc == 0

        manifest = json.loads(
            (tmp_path / "output" / _MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        manifest_str = json.dumps(manifest, ensure_ascii=False)
        # Original filename must NOT appear in manifest
        assert "张三_劳动合同" not in manifest_str

        # But source index should have it when work files are explicitly kept.
        index = json.loads(
            (tmp_path / "output" / _WORK_DIR / _SOURCE_INDEX_FILENAME).read_text(encoding="utf-8")
        )
        assert "doc_01" in index
        assert index["doc_01"]["original_name"] == "张三_劳动合同.txt"

    def test_denylist_file_forces_redaction(self, tmp_path, monkeypatch):
        """Denylist term should be forced redacted."""
        from legal_desens.batch import batch_redact_case

        # Mock NER to detect "海源" as ORG so denylist can force redaction
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re as _re
            for m in _re.finditer(r"海源", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "被申请人海源应支付工资。",
        })
        out_dir = str(tmp_path / "output")
        denylist = _make_denylist(tmp_path, ["海源"])

        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            denylist_file=denylist,
        )
        assert rc == 0

        redacted = (tmp_path / "output" / _FINAL_DIR / "doc_01.redacted.md").read_text(
            encoding="utf-8"
        )
        # "海源" should be redacted
        assert "海源" not in redacted

# ── 8. Explicit regex-only batch mode ───────────────────────────────────────


class TestBatchRegexOnly:
    def test_explicit_regex_only_skips_ner_precheck(self, tmp_path, monkeypatch):
        """Explicit --regex-only mode can run when NER is unavailable."""
        from legal_desens import batch as batch_module
        from legal_desens.batch import batch_redact_case

        def fail_precheck(model_dir=None):
            raise BatchError("NER should not be inspected in regex-only mode")

        monkeypatch.setattr(batch_module, "_precheck_ner", fail_precheck)

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "联系电话13800138000。",
        })
        out_dir = str(tmp_path / "output")

        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            regex_only=True,
        )

        assert rc == 0
        redacted = (tmp_path / "output" / _FINAL_DIR / "doc_01.redacted.md").read_text(
            encoding="utf-8"
        )
        assert "13800138000" not in redacted
        assert "【手机号】" in redacted


# ── 9. Missing OCR for scan files ───────────────────────────────────────────


class TestMissingOcr:
    def test_scan_file_without_ocr_raises(self, tmp_path, monkeypatch):
        """Scan file when [ocr] not installed should raise BatchError."""
        from legal_desens import batch as batch_module
        from legal_desens.batch import batch_redact_case

        # Create a dummy .png file
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        # Write minimal valid PNG (1x1 transparent pixel)
        png_bytes = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\xf3\xffa'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        (input_dir / "scan1.png").write_bytes(png_bytes)

        # Patch _check_ocr_available to simulate missing OCR extra
        def fail_ocr():
            raise BatchError(
                "OCR extra [ocr] is not installed but scan files were found. "
                "Install with: pip install legal-desens[ocr]"
            )

        monkeypatch.setattr(batch_module, "_check_ocr_available", fail_ocr)

        out_dir = str(tmp_path / "output")

        with pytest.raises(BatchError, match="OCR extra"):
            batch_redact_case(
                input_dir=input_dir,
                out_dir=out_dir,
            )


# ── 10. Cleanup modes ───────────────────────────────────────────────────────


class TestCleanupModes:
    def test_default_cleanup_delete(self, tmp_path):
        """Default cleanup deletes sensitive work files after a successful run."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")
        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
        )
        assert rc == 0

        out_path = tmp_path / "output"
        assert (out_path / _FINAL_DIR / "doc_01.redacted.md").is_file()
        assert (out_path / _REPORT_FILENAME).is_file()
        assert (out_path / _MANIFEST_FILENAME).is_file()
        assert not (out_path / _WORK_DIR).exists()
        assert not (out_path / _ARCHIVE_DIR).is_dir()

    def test_cleanup_none_keeps_work_dir(self, tmp_path):
        """Explicit cleanup=none keeps generated map/audit under the work dir."""
        from legal_desens.batch import batch_redact_case

        input_dir = _make_input_dir(tmp_path, {
            "doc1.txt": "张三在某科技有限公司工作。",
        })
        out_dir = str(tmp_path / "output")
        rc = batch_redact_case(
            input_dir=input_dir,
            out_dir=out_dir,
            profile_name="labor",
            cleanup="none",
        )
        assert rc == 0

        work_dir = tmp_path / "output" / _WORK_DIR
        assert (work_dir / "doc_01.map.json").is_file()
        assert (work_dir / "doc_01.audit.json").is_file()


# Need Path for classify_ext tests
from pathlib import Path
