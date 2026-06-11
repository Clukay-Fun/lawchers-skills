"""Tests for NER engine integration (002 stage).

Tests that require a model are skipped if model dir is not available.
Tests that don't require a model (error paths, CLI) always run.
"""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.engine.ner import (
    NEREngine,
    _resolve_model_dir,
    _check_model_dir,
    _load_labels,
    _detect_tag_scheme,
    is_model_available,
    scan_ner,
    inspect_ner,
    decode_tags,
    TAG_SCHEME_BIO,
    TAG_SCHEME_BIOES,
)
from legal_desens.engine.span import Span
from legal_desens.redact import redact
from legal_desens.rules import load_rules

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")

MODEL_DIR = os.environ.get("LEGAL_DESENS_MODEL_DIR", "/Applications/Desensitization/ydner_onnx")
HAS_MODEL = is_model_available(MODEL_DIR)

skip_no_model = pytest.mark.skipif(not HAS_MODEL, reason="NER model not available")


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


# ── 1. Model directory resolution ────────────────────────────────────────────

class TestModelDirResolution:
    def test_explicit_dir(self):
        d = _resolve_model_dir("/some/path")
        assert str(d) == "/some/path"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("LEGAL_DESENS_MODEL_DIR", "/env/path")
        d = _resolve_model_dir(None)
        assert str(d) == "/env/path"

    def test_default_dir(self, monkeypatch):
        monkeypatch.delenv("LEGAL_DESENS_MODEL_DIR", raising=False)
        d = _resolve_model_dir(None)
        assert str(d) == "/Applications/Desensitization/ydner_onnx"


# ── 2. Model directory validation ────────────────────────────────────────────

class TestModelDirValidation:
    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            _check_model_dir(tmp_path / "nonexistent")

    def test_incomplete_dir_raises(self, tmp_path):
        d = tmp_path / "model"
        d.mkdir()
        (d / "vocab.txt").write_text("[PAD]\n[UNK]\n")
        with pytest.raises(FileNotFoundError, match="missing files"):
            _check_model_dir(d)


# ── 3. is_model_available ────────────────────────────────────────────────────

class TestModelAvailable:
    def test_returns_bool(self):
        result = is_model_available("/nonexistent")
        assert result is False

    def test_real_dir(self):
        result = is_model_available(MODEL_DIR)
        assert isinstance(result, bool)


# ── 4. Error paths (no model needed) ─────────────────────────────────────────

class TestErrorPaths:
    def test_scan_ner_no_model_raises(self):
        with pytest.raises((FileNotFoundError, RuntimeError)):
            scan_ner("test", model_dir="/nonexistent")

    def test_redact_regex_plus_ner_no_model(self, rules):
        with pytest.raises((FileNotFoundError, RuntimeError)):
            redact(
                text="电话13800138000。",
                rules=rules,
                source_sha256=hashlib.sha256("电话13800138000。".encode()).hexdigest(),
                mode="regex+ner",
                model_dir="/nonexistent",
            )

    def test_redact_regex_only_unaffected(self, rules):
        text = "电话13800138000。"
        sha = hashlib.sha256(text.encode()).hexdigest()
        redacted, map_data, _ = redact(text, rules, sha, mode="regex-only")
        assert "手机号1" in redacted
        assert map_data["mode"] == "regex-only"

    def test_inspect_ner_no_model(self):
        with pytest.raises((FileNotFoundError, RuntimeError)):
            inspect_ner("/nonexistent")


# ── 5. Tag scheme detection ──────────────────────────────────────────────────

class TestTagSchemeDetection:
    def test_bio(self):
        id2label = {0: "O", 1: "B-PER", 2: "I-PER"}
        assert _detect_tag_scheme(id2label) == TAG_SCHEME_BIO

    def test_bioes(self):
        id2label = {0: "O", 1: "B-PER", 2: "I-PER", 3: "E-PER", 4: "S-PER"}
        assert _detect_tag_scheme(id2label) == TAG_SCHEME_BIOES


# ── 6. Offset assertion tests (model required) ──────────────────────────────

@skip_no_model
class TestNEROffsetAlignment:
    """Tests that verify text[start:end] == span.text for every NER span."""

    def test_basic_chinese(self):
        engine = NEREngine(MODEL_DIR)
        text = "张三向北京市朝阳区人民法院提交起诉状，请求判令北京某某科技有限公司支付货款人民币10000元。\n"
        spans, warnings = engine.scan(text)
        for s in spans:
            assert text[s.start:s.end] == s.text, (
                f"Offset mismatch: text[{s.start}:{s.end}] = "
                f"{repr(text[s.start:s.end])} != {repr(s.text)}"
            )

    def test_stress_fullwidth_emoji_crlf(self):
        """Offset must survive fullwidth digits, emoji, CRLF, consecutive spaces."""
        engine = NEREngine(MODEL_DIR)
        text = "张三  在上海市浦东新区签署合同，金额为１２０００元 😊\r\n联系电话13800138000。"
        spans, warnings = engine.scan(text)
        for s in spans:
            assert text[s.start:s.end] == s.text, (
                f"Offset mismatch at [{s.start}:{s.end}]: "
                f"{repr(text[s.start:s.end])} != {repr(s.text)}"
            )

    def test_empty_text(self):
        engine = NEREngine(MODEL_DIR)
        spans, warnings = engine.scan("")
        assert len(spans) == 0

    def test_all_ascii(self):
        engine = NEREngine(MODEL_DIR)
        text = "Contact John Smith at john@example.com"
        spans, warnings = engine.scan(text)
        for s in spans:
            assert text[s.start:s.end] == s.text


# ── 7. Model I/O inspection (model required) ─────────────────────────────────

@skip_no_model
class TestModelIOInspection:
    def test_inspect_returns_valid_info(self):
        info = inspect_ner(MODEL_DIR)
        assert "model_io" in info
        io = info["model_io"]
        assert len(io["input_names"]) > 0
        assert len(io["output_names"]) > 0
        assert "id2label" in info
        assert "tag_scheme" in info
        assert info["tag_scheme"] in ("BIO", "BIOES")

    def test_model_io_recorded(self):
        engine = NEREngine(MODEL_DIR)
        io = engine.model_io
        assert isinstance(io.input_names, list)
        assert isinstance(io.output_names, list)
        assert len(io.input_names) > 0


# ── 8. Full NER pipeline (model required) ────────────────────────────────────

@skip_no_model
class TestNERPipeline:
    def test_ner_spans_in_overlap_merge(self):
        """NER spans and regex spans can coexist in merge pipeline."""
        engine = NEREngine(MODEL_DIR)
        text = "张三向北京市朝阳区人民法院提交起诉状，请求判令北京某某科技有限公司支付货款人民币10000元。\n"
        spans, _ = engine.scan(text)
        # All spans should have engine="ner"
        for s in spans:
            assert s.engine == "ner"
            assert s.priority == 50

    def test_full_redact_restore_with_ner(self, rules):
        """Non regex-only redact → restore must be byte-identical."""
        text = "张三向北京市朝阳区人民法院提交起诉状，请求判令北京某某科技有限公司支付货款人民币10000元。\n"
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        redacted, map_data, audit_data = redact(
            text=text,
            rules=rules,
            source_sha256=sha,
            mode="regex+ner",
            model_dir=MODEL_DIR,
        )

        # Compute redacted sha
        redacted_sha = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        map_data["redacted_sha256"] = redacted_sha

        from legal_desens.restore import restore
        restored = restore(redacted, map_data, redacted_file_sha256=redacted_sha)

        assert restored == text, "Round-trip failed: restored != original"

    def test_ner_occurrences_in_map(self, rules):
        """NER occurrences correctly appear in map."""
        text = "张三向北京市朝阳区人民法院提交起诉状，请求判令北京某某科技有限公司支付货款人民币10000元。\n"
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _, map_data, _ = redact(text, rules, sha, mode="regex+ner", model_dir=MODEL_DIR)

        ner_occ = [o for o in map_data["occurrences"] if o["engine"] == "ner"]
        # There should be at least some NER occurrences
        # (exact count depends on model)
        for o in ner_occ:
            assert "entity_id" in o
            assert "redacted_start" in o
            assert "redacted_end" in o

    def test_overlap_regex_over_ner(self, rules):
        """When regex and NER spans overlap, regex wins."""
        text = "电话13800138000。"
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _, map_data, _ = redact(text, rules, sha, mode="regex+ner", model_dir=MODEL_DIR)

        # Phone should be handled by regex (priority 100 > NER's 50)
        phone_occ = [o for o in map_data["occurrences"] if o["engine"] == "regex"]
        assert len(phone_occ) > 0


# ── 9. CLI subcommands ───────────────────────────────────────────────────────

class TestNERCLI:
    def test_ner_inspect_no_model(self):
        from legal_desens.cli import main
        ret = main(["ner-inspect", "--model-dir", "/nonexistent"])
        assert ret == 1

    def test_ner_spans_no_model(self):
        from legal_desens.cli import main
        ret = main([
            "ner-spans",
            os.path.join(FIXTURES, "ner_sample.txt"),
            "--model-dir", "/nonexistent",
        ])
        assert ret == 1

    @skip_no_model
    def test_ner_inspect_cli(self):
        from legal_desens.cli import main
        # Should succeed and return 0
        assert main(["ner-inspect", "--model-dir", MODEL_DIR]) == 0

    @skip_no_model
    def test_ner_spans_cli(self, tmp_path):
        from legal_desens.cli import main
        out_file = str(tmp_path / "spans.json")
        ret = main([
            "ner-spans",
            os.path.join(FIXTURES, "ner_sample.txt"),
            "--model-dir", MODEL_DIR,
            "--out", out_file,
        ])
        assert ret == 0
        with open(out_file) as f:
            data = json.load(f)
        assert "spans" in data
        for s in data["spans"]:
            assert "start" in s
            assert "end" in s
            assert "text" in s

    @skip_no_model
    def test_redact_with_model_dir(self, tmp_path, rules):
        from legal_desens.cli import main
        out_file = str(tmp_path / "redacted.txt")
        map_file = str(tmp_path / "map.json")
        audit_file = str(tmp_path / "audit.json")
        ret = main([
            "redact",
            os.path.join(FIXTURES, "ner_sample.txt"),
            "--model-dir", MODEL_DIR,
            "--out", out_file,
            "--map", map_file,
            "--audit", audit_file,
        ])
        assert ret == 0
        assert os.path.exists(out_file)
        assert os.path.exists(map_file)
        with open(map_file) as f:
            data = json.load(f)
        assert data["mode"] == "regex+ner"

    @skip_no_model
    def test_redact_restore_roundtrip_cli(self, tmp_path):
        from legal_desens.cli import main
        redacted_file = str(tmp_path / "redacted.txt")
        map_file = str(tmp_path / "map.json")
        audit_file = str(tmp_path / "audit.json")
        restored_file = str(tmp_path / "restored.txt")

        input_file = os.path.join(FIXTURES, "ner_sample.txt")

        assert main([
            "redact", input_file,
            "--model-dir", MODEL_DIR,
            "--out", redacted_file,
            "--map", map_file,
            "--audit", audit_file,
        ]) == 0

        assert main([
            "restore", redacted_file,
            "--map", map_file,
            "--out", restored_file,
        ]) == 0

        # Byte-level check
        import hashlib
        with open(input_file, "rb") as f:
            orig_sha = hashlib.sha256(f.read()).hexdigest()
        with open(restored_file, "rb") as f:
            rest_sha = hashlib.sha256(f.read()).hexdigest()
        assert orig_sha == rest_sha, "Round-trip SHA mismatch"


# ── 10. Offset stress with regex+NER overlap (model required) ────────────────

@skip_no_model
class TestOffsetStress:
    def test_stress_text_offsets(self):
        """Fullwidth, emoji, CRLF, consecutive spaces don't break offsets."""
        engine = NEREngine(MODEL_DIR)
        text = "张三  在上海市浦东新区签署合同，金额为１２０００元 😊\r\n联系电话13800138000。"
        spans, warnings = engine.scan(text)
        for s in spans:
            assert text[s.start:s.end] == s.text

    def test_stress_with_regex_overlap(self, rules):
        """Regex and NER spans from stress text merge correctly."""
        text = "张三  在上海市浦东新区签署合同，金额为１２０００元 😊\r\n联系电话13800138000。"
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        redacted, map_data, audit_data = redact(
            text=text, rules=rules, source_sha256=sha,
            mode="regex+ner", model_dir=MODEL_DIR,
        )

        # Verify round-trip
        redacted_sha = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        from legal_desens.restore import restore
        restored = restore(redacted, map_data, redacted_file_sha256=redacted_sha)
        assert restored == text
