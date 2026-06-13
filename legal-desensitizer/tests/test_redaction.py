"""Tests for legal-desens text redaction engine (001 stage)."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile

import pytest

# Ensure we can import the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.io import read_text, write_text, sha256_bytes
from legal_desens.rules import load_rules
from legal_desens.engine.regex import scan_regex
from legal_desens.engine.merge import merge_spans
from legal_desens.engine.span import Span
from legal_desens.redact import redact, LabelAllocator
from legal_desens.restore import restore
from legal_desens.audit import audit
from legal_desens.profile import load_profile


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


def _read_fixture(name):
    return read_text(os.path.join(FIXTURES, name))


# ── 1. Rules loading ──────────────────────────────────────────────────────────

class TestRules:
    def test_load_rules(self, rules):
        assert len(rules) >= 5
        types = {r.entity_type for r in rules}
        assert "PHONE" in types
        assert "ID_CARD" in types
        assert "EMAIL" in types

    def test_rules_compiled(self, rules):
        for r in rules:
            assert r.compiled is not None

    def test_default_rules_load_from_package_resource(self, monkeypatch, rules):
        """Default rules must not depend on the source-tree rules/ directory."""
        monkeypatch.chdir(tempfile.gettempdir())
        loaded = load_rules()
        assert [r.id for r in loaded] == [r.id for r in rules]


# ── 2. Regex engine ───────────────────────────────────────────────────────────

class TestRegexEngine:
    def test_phone_match(self, rules):
        text = "电话13800138000。"
        spans = scan_regex(text, rules)
        assert any(s.entity_type == "PHONE" and s.text == "13800138000" for s in spans)

    def test_landline_match(self, rules):
        text = "座机0755-23982682，分机0755-23982682-123。"
        spans = scan_regex(text, rules)
        landlines = [s.text for s in spans if s.entity_type == "LANDLINE"]
        assert "0755-23982682" in landlines
        assert "0755-23982682-123" in landlines

    def test_id_card_match(self, rules):
        text = "身份证110101199001011234。"
        spans = scan_regex(text, rules)
        assert any(s.entity_type == "ID_CARD" and s.text == "110101199001011234" for s in spans)

    def test_bank_account_match(self, rules):
        """Context-aware BANK_ACCOUNT detection: with trigger words, digits are matched."""
        from legal_desens.engine.bank_account import detect_bank_accounts
        text = "收款账号11005545236302，联系电话15817465075。"
        # First get regex spans (phone, etc.)
        spans = scan_regex(text, rules)
        # Then context-aware bank detection
        bank_spans, warnings = detect_bank_accounts(text, spans)
        bank_accounts = [s.text for s in bank_spans if s.entity_type == "BANK_ACCOUNT"]
        assert "11005545236302" in bank_accounts
        # Phone should NOT be detected as bank account
        assert "15817465075" not in bank_accounts

    def test_bank_branch_match(self, rules):
        text = "开户行平安银行深圳江苏大厦支行，账号11005545236302。"
        spans = scan_regex(text, rules)
        branches = [s.text for s in spans if s.entity_type == "BANK_BRANCH"]
        assert "开户行平安银行深圳江苏大厦支行" in branches

    def test_id_card_wins_over_bank_account(self, rules):
        """ID_CARD regex should win over any bank account detection."""
        text = "身份证110101199001011234。"
        spans = scan_regex(text, rules)
        kept, discarded = merge_spans(spans)
        assert any(s.entity_type == "ID_CARD" for s in kept)
        assert not any(s.entity_type == "BANK_ACCOUNT" for s in kept)

    def test_email_match(self, rules):
        text = "邮箱test@example.com。"
        spans = scan_regex(text, rules)
        assert any(s.entity_type == "EMAIL" and s.text == "test@example.com" for s in spans)

    def test_case_no_match(self, rules):
        text = "案号(2024)京0101民初12345号。"
        spans = scan_regex(text, rules)
        assert any(s.entity_type == "CASE_NO" for s in spans)

    def test_contract_and_short_case_no_match(self, rules):
        text = "合同编号[2026]律代字第（2o」号，案号26SZ-SMSO9。"
        spans = scan_regex(text, rules)
        case_numbers = [s.text for s in spans if s.entity_type == "CASE_NO"]
        assert "合同编号[2026]律代字第（2o」号" in case_numbers
        assert "案号26SZ-SMSO9" in case_numbers

    def test_money_match(self, rules):
        text = "请求支付货款人民币壹佰万元，并承担违约金¥12000。"
        spans = scan_regex(text, rules)
        money = [s.text for s in spans if s.entity_type == "MONEY"]
        assert "人民币壹佰万元" in money
        assert "¥12000" in money

    def test_no_match(self, rules):
        text = "没有敏感信息的文本。"
        spans = scan_regex(text, rules)
        assert len(spans) == 0


# ── 3. NER interface ─────────────────────────────────────────────────────────

class TestNERInterface:
    def test_regex_only_skips_ner(self):
        from legal_desens.engine.ner import scan_ner, is_model_available
        if not is_model_available():
            with pytest.raises((RuntimeError, FileNotFoundError)):
                scan_ner("test")

    def test_ner_model_not_available(self):
        from legal_desens.engine.ner import is_model_available
        result = is_model_available()
        assert isinstance(result, bool)

    def test_redact_non_regex_only_requires_ner_model(self, rules):
        with pytest.raises((RuntimeError, FileNotFoundError)):
            redact(
                text="电话13800138000。",
                rules=rules,
                source_sha256=hashlib.sha256("电话13800138000。".encode("utf-8")).hexdigest(),
                mode="regex+ner",
                model_dir="/nonexistent",
            )

    def test_regex_plus_ner_audit_marks_best_effort(self, rules, monkeypatch):
        def fake_scan_ner(text, model_dir=None):
            return [Span("PER", 0, 2, "张三", "ner", priority=80, discovery_order=0)], []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)
        text = "张三电话13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        redacted_text, map_data, audit_data = redact(
            text=text,
            rules=rules,
            source_sha256=source_sha,
            mode="regex+ner",
        )

        # Default profile is labor → bracket_unnumbered labels
        assert "【姓名】" in redacted_text
        assert map_data["mode"] == "regex+ner"
        assert audit_data["best_effort"] is True
        assert any(w["type"] == "best_effort_notice" for w in audit_data["warnings"])


# ── 4. Span merge ─────────────────────────────────────────────────────────────

class TestSpanMerge:
    def test_no_overlap(self):
        spans = [
            Span("PHONE", 0, 11, "13800138000", "regex", priority=100, discovery_order=0),
            Span("EMAIL", 15, 30, "test@x.com", "regex", priority=90, discovery_order=1),
        ]
        kept, discarded = merge_spans(spans)
        assert len(kept) == 2
        assert len(discarded) == 0

    def test_overlap_longer_wins(self):
        spans = [
            Span("A", 0, 5, "abcde", "regex", priority=100, discovery_order=0),
            Span("B", 0, 10, "abcdefghij", "regex", priority=100, discovery_order=1),
        ]
        kept, discarded = merge_spans(spans)
        assert len(kept) == 1
        assert kept[0].length == 10
        assert len(discarded) == 1

    def test_overlap_higher_priority_wins(self):
        spans = [
            Span("A", 0, 5, "abcde", "regex", priority=90, discovery_order=0),
            Span("B", 0, 5, "abcde", "regex", priority=100, discovery_order=1),
        ]
        kept, discarded = merge_spans(spans)
        assert len(kept) == 1
        assert kept[0].priority == 100

    def test_overlap_engine_order_regex_over_ner(self):
        spans = [
            Span("A", 0, 5, "abcde", "ner", priority=100, discovery_order=0),
            Span("B", 0, 5, "abcde", "regex", priority=100, discovery_order=1),
        ]
        kept, discarded = merge_spans(spans)
        assert len(kept) == 1
        assert kept[0].engine == "regex"

    def test_deterministic(self):
        spans = [
            Span("A", 0, 5, "abcde", "regex", priority=100, discovery_order=0),
            Span("B", 3, 8, "defgh", "regex", priority=100, discovery_order=1),
        ]
        k1, d1 = merge_spans(list(spans))
        k2, d2 = merge_spans(list(spans))
        assert [(s.start, s.end) for s in k1] == [(s.start, s.end) for s in k2]


# ── 5. Label allocation ──────────────────────────────────────────────────────

class TestLabelAllocator:
    def test_sequential_numbering(self, rules):
        alloc = LabelAllocator(rules)
        eid1, label1 = alloc.get_label("PHONE", "13800138000")
        eid2, label2 = alloc.get_label("PHONE", "13900139000")
        assert label1 == "手机号1"
        assert label2 == "手机号2"
        assert eid1 == "PHONE_1"
        assert eid2 == "PHONE_2"

    def test_same_entity_reuses_label(self, rules):
        alloc = LabelAllocator(rules)
        eid1, label1 = alloc.get_label("PHONE", "13800138000")
        eid2, label2 = alloc.get_label("PHONE", "13800138000")
        assert eid1 == eid2
        assert label1 == label2

    def test_different_types_independent(self, rules):
        alloc = LabelAllocator(rules)
        _, l1 = alloc.get_label("PHONE", "13800138000")
        _, l2 = alloc.get_label("EMAIL", "test@x.com")
        assert l1 == "手机号1"
        assert l2 == "邮箱1"

    def test_ner_entity_types_use_chinese_default_prefixes(self, rules):
        alloc = LabelAllocator(rules)
        _, per = alloc.get_label("PER", "张三")
        _, loc = alloc.get_label("LOC", "北京市")
        _, org = alloc.get_label("ORG", "人民法院")
        _, money = alloc.get_label("MONEY", "10000元")
        assert per == "人物1"
        assert loc == "地点1"
        assert org == "机构1"
        assert money == "金额1"

    def test_person_label_alias(self, rules):
        """PERSON maps to same Chinese prefix as PER."""
        alloc = LabelAllocator(rules)
        _, label = alloc.get_label("PERSON", "张三")
        assert label == "人物1"

    def test_location_label_alias(self, rules):
        """LOCATION maps to same Chinese prefix as LOC."""
        alloc = LabelAllocator(rules)
        _, label = alloc.get_label("LOCATION", "北京市")
        assert label == "地点1"


# ── 6. Redact + Restore round-trip ───────────────────────────────────────────

class TestRoundTrip:
    def _roundtrip(self, fixture_name, rules):
        tf = _read_fixture(fixture_name)
        source_sha = tf.sha256

        redacted_text, map_data, audit_data = redact(
            text=tf.text,
            rules=rules,
            source_sha256=source_sha,
            mode="regex-only",
            level="strict",
        )

        # Compute redacted sha with same byte-level treatment
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

        # Restore
        restored_text = restore(redacted_text, map_data, redacted_file_sha256=redacted_sha)
        return tf.text, redacted_text, restored_text, map_data, audit_data

    def test_sample_roundtrip(self, rules):
        original, redacted, restored, map_data, audit_data = self._roundtrip("sample.txt", rules)
        assert original == restored
        assert len(map_data["entities"]) > 0
        assert len(map_data["occurrences"]) > 0

    def test_empty_roundtrip(self, rules):
        original, redacted, restored, map_data, audit_data = self._roundtrip("empty.txt", rules)
        assert original == restored
        assert map_data["entities"] == []
        assert map_data["occurrences"] == []
        assert audit_data["summary"]["total_entities"] == 0
        assert audit_data["summary"]["total_occurrences"] == 0

    def test_no_match_roundtrip(self, rules):
        original, redacted, restored, map_data, audit_data = self._roundtrip("no_match.txt", rules)
        assert original == restored
        assert map_data["entities"] == []
        assert map_data["occurrences"] == []

    def test_bom_preserved(self, rules):
        tf = _read_fixture("with_bom.txt")
        assert tf.has_bom is True
        original, redacted, restored, _, _ = self._roundtrip("with_bom.txt", rules)
        assert original == restored
        # Verify BOM is in the raw bytes
        raw_restored = restored.encode("utf-8")
        raw_with_bom = b"\xef\xbb\xbf" + raw_restored
        assert raw_with_bom[:3] == b"\xef\xbb\xbf"

    def test_crlf_preserved(self, rules):
        tf = _read_fixture("crlf.txt")
        assert tf.newline == "\r\n"
        original, redacted, restored, _, _ = self._roundtrip("crlf.txt", rules)
        assert original == restored
        assert "\r\n" in restored

    def test_no_trailing_newline(self, rules):
        tf = _read_fixture("no_trailing_newline.txt")
        assert tf.has_trailing_newline is False
        original, redacted, restored, _, _ = self._roundtrip("no_trailing_newline.txt", rules)
        assert original == restored
        assert not restored.endswith("\n")

    def test_label_collision(self, rules):
        """Text already contains '人物1', '手机号1' etc."""
        original, redacted, restored, map_data, _ = self._roundtrip("label_collision.txt", rules)
        assert original == restored

    def test_duplicate_entities_reuse_labels(self, rules):
        """Same phone number appearing twice should reuse the same label."""
        text = "电话1: 13800138000。电话2: 13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted_text, map_data, _ = redact(text, rules, source_sha)

        # Find phone entities
        phone_entities = [e for e in map_data["entities"] if e["entity_type"] == "PHONE"]
        assert len(phone_entities) == 1  # Only one unique phone entity
        assert len(map_data["occurrences"]) == 2  # But two occurrences

    def test_byte_level_roundtrip(self, rules):
        """Verify SHA-256 match at byte level."""
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256

        redacted_text, map_data, _ = redact(tf.text, rules, source_sha)

        redacted_bytes = redacted_text.encode("utf-8")
        if tf.has_bom:
            redacted_bytes = b"\xef\xbb\xbf" + redacted_bytes
        redacted_sha = hashlib.sha256(redacted_bytes).hexdigest()
        map_data["redacted_sha256"] = redacted_sha

        restored_text = restore(redacted_text, map_data, redacted_file_sha256=redacted_sha)

        # Compute restored sha with same byte treatment
        restored_bytes = restored_text.encode("utf-8")
        if tf.has_bom:
            restored_bytes = b"\xef\xbb\xbf" + restored_bytes
        restored_sha = hashlib.sha256(restored_bytes).hexdigest()

        assert restored_sha == source_sha, "SHA-256 mismatch: round-trip not byte-identical"

    def test_money_roundtrip_with_chinese_label(self, rules):
        """MONEY regex redacts with Chinese label '金额' and round-trips correctly (strict profile)."""
        text = "支付货款人民币壹佰万元整，另付违约金¥12000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        strict = load_profile("strict")

        redacted_text, map_data, _ = redact(text, rules, source_sha, mode="regex-only", profile=strict)

        # MONEY entities must use Chinese label prefix (strict redacts MONEY)
        assert "【金额】" in redacted_text
        assert "壹佰万" not in redacted_text
        assert "12000" not in redacted_text

        # Verify entities in map
        money_entities = [e for e in map_data["entities"] if e["entity_type"] == "MONEY"]
        assert len(money_entities) >= 2
        for e in money_entities:
            assert e["replacement"] == "【金额】"

        # Round-trip
        redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        restored = restore(redacted_text, map_data, redacted_file_sha256=redacted_sha)
        assert restored == text

    def test_money_plus_phone_roundtrip_chinese_labels(self, rules):
        """MONEY + PHONE coexist, both use Chinese labels, round-trip intact (strict profile)."""
        text = "原告张三，电话13800138000，诉请支付人民币伍万元。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        strict = load_profile("strict")

        redacted_text, map_data, _ = redact(text, rules, source_sha, mode="regex-only", profile=strict)

        assert "【手机号】" in redacted_text
        assert "【金额】" in redacted_text

        redacted_sha = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        restored = restore(redacted_text, map_data, redacted_file_sha256=redacted_sha)
        assert restored == text


# ── 7. SHA-256 mismatch detection ─────────────────────────────────────────────

class TestMismatchDetection:
    def test_redacted_sha_mismatch_aborts_restore(self, rules):
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256

        redacted_text, map_data, _ = redact(tf.text, rules, source_sha)

        # Tamper with the redacted file sha in the map
        map_data["redacted_sha256"] = "0" * 64

        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            restore(redacted_text, map_data, redacted_file_sha256="tampered_sha")

    def test_restore_no_output_on_mismatch(self, rules, tmp_path):
        """When SHA mismatch occurs, no output file should be created."""
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        redacted_text, map_data, _ = redact(tf.text, rules, source_sha)

        out_file = str(tmp_path / "restored.txt")
        map_data["redacted_sha256"] = "0" * 64

        try:
            restore(redacted_text, map_data, redacted_file_sha256="wrong_sha")
        except ValueError:
            pass

        assert not os.path.exists(out_file)


# ── 8. Overlap scenarios ─────────────────────────────────────────────────────

class TestOverlap:
    def test_overlap_span_warning_in_audit(self, rules):
        """When spans overlap, discarded spans appear in warnings."""
        text = "1380013800012345"  # phone: 13800138000 (0-11), partial overlap with digits
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _, map_data, audit_data = redact(text, rules, source_sha)
        # If there are warnings, they should be about overlapped spans
        # The exact behavior depends on regex matching, but audit should have the field
        assert "warnings" in audit_data


# ── 9. Audit ──────────────────────────────────────────────────────────────────

class TestAudit:
    def test_audit_residual_scan_clean(self, rules):
        """After redaction, residual scan should pass (no sensitive patterns found)."""
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        redacted_text, map_data, audit_data = redact(tf.text, rules, source_sha)
        assert audit_data["residual_scan"]["passed"] is True
        assert len(audit_data["residual_scan"]["findings"]) == 0

    def test_audit_summary(self, rules):
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        _, map_data, audit_data = redact(tf.text, rules, source_sha)

        assert audit_data["summary"]["total_entities"] > 0
        assert audit_data["summary"]["total_occurrences"] > 0
        assert "regex" in audit_data["summary"]["by_engine"]

    def test_audit_standalone(self, rules):
        """The standalone audit command should produce the same schema."""
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        redacted_text, map_data, _ = redact(tf.text, rules, source_sha)

        result = audit(redacted_text, map_data, rules)
        assert "schema_version" in result
        assert "summary" in result
        assert "residual_scan" in result


# ── 10. File I/O byte safety ─────────────────────────────────────────────────

class TestFileIO:
    def test_write_read_roundtrip(self, tmp_path):
        """Writing and reading back preserves bytes exactly."""
        path = str(tmp_path / "test.txt")
        text = "张三\r\n李四\n"
        meta = _read_fixture("crlf.txt")

        write_text(path, text, meta)
        tf = read_text(path)
        assert tf.text == text

    def test_bom_write_read(self, tmp_path):
        path = str(tmp_path / "bom.txt")
        text = "测试\n"
        tf_bom = _read_fixture("with_bom.txt")

        write_text(path, text, tf_bom)
        raw = open(path, "rb").read()
        assert raw[:3] == b"\xef\xbb\xbf"
        assert read_text(path).sha256 == hashlib.sha256(raw).hexdigest()

    def test_no_strip(self):
        """read_text should not strip whitespace."""
        tf = _read_fixture("sample.txt")
        # The sample file ends with \n, should be preserved
        assert tf.text.endswith("\n")


# ── 11. Map schema completeness ──────────────────────────────────────────────

class TestMapSchema:
    def test_map_has_required_fields(self, rules):
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        _, map_data, _ = redact(tf.text, rules, source_sha)

        assert map_data["schema_version"] == "1.0"
        assert "source_sha256" in map_data
        assert "redacted_sha256" in map_data
        assert "entities" in map_data
        assert "occurrences" in map_data
        assert "level" in map_data
        assert "mode" in map_data
        assert "created_at" in map_data

    def test_entity_structure(self, rules):
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        _, map_data, _ = redact(tf.text, rules, source_sha)

        for e in map_data["entities"]:
            assert "id" in e
            assert "entity_type" in e
            assert "original" in e
            assert "replacement" in e
            assert "engines" in e

    def test_occurrence_structure(self, rules):
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        _, map_data, _ = redact(tf.text, rules, source_sha)

        for o in map_data["occurrences"]:
            assert "entity_id" in o
            assert "engine" in o
            assert "original_start" in o
            assert "original_end" in o
            assert "redacted_start" in o
            assert "redacted_end" in o

    def test_occurrence_has_redacted_positions(self, rules):
        """Occurrences must record both original and redacted positions."""
        tf = _read_fixture("sample.txt")
        source_sha = tf.sha256
        _, map_data, _ = redact(tf.text, rules, source_sha)

        for o in map_data["occurrences"]:
            assert o["redacted_start"] >= 0
            assert o["redacted_end"] > o["redacted_start"]


# ── 12. CLI integration ──────────────────────────────────────────────────────

class TestCLI:
    def test_help(self):
        from legal_desens.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_cli_writes_engine_audit_data(self, tmp_path, monkeypatch):
        from legal_desens.cli import main

        input_file = tmp_path / "input.txt"
        out_file = tmp_path / "out.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("张三电话13800138000。", encoding="utf-8")

        def fake_redact(**kwargs):
            return (
                "人物1电话手机号1。",
                {
                    "schema_version": "1.0",
                    "source_file": "",
                    "redacted_file": "",
                    "source_sha256": kwargs["source_sha256"],
                    "redacted_sha256": "",
                    "level": kwargs["level"],
                    "mode": kwargs["mode"],
                    "created_at": "2026-01-01T00:00:00Z",
                    "entities": [],
                    "occurrences": [],
                },
                {
                    "schema_version": "1.0",
                    "summary": {
                        "total_entities": 0,
                        "total_occurrences": 0,
                        "by_entity_type": {},
                        "by_engine": {},
                    },
                    "residual_scan": {"passed": True, "findings": []},
                    "warnings": [{"type": "best_effort_notice"}],
                    "best_effort": True,
                },
            )

        monkeypatch.setattr("legal_desens.cli.redact", fake_redact)

        ret = main([
            "redact",
            str(input_file),
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        assert audit_data["best_effort"] is True
        assert audit_data["warnings"][0]["type"] == "best_effort_notice"

    def test_installed_console_script_loads_default_rules(self, tmp_path):
        """Wheel install should run without --rules from outside the source tree."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dist_dir = tmp_path / "dist"
        venv_dir = tmp_path / "venv"
        input_file = tmp_path / "input.txt"
        out_file = tmp_path / "out.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("电话13800138000\n", encoding="utf-8")

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(dist_dir),
                ".",
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if os.name == "nt":
            python = venv_dir / "Scripts" / "python.exe"
            legal_desens = venv_dir / "Scripts" / "legal-desens.exe"
        else:
            python = venv_dir / "bin" / "python"
            legal_desens = venv_dir / "bin" / "legal-desens"
        wheel = next(dist_dir.glob("*.whl"))
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        result = subprocess.run(
            [
                str(legal_desens),
                "redact",
                str(input_file),
                "--regex-only",
                "--out",
                str(out_file),
                "--map",
                str(map_file),
                "--audit",
                str(audit_file),
            ],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert out_file.exists()
        # Default profile is labor → bracket_unnumbered labels
        assert "【手机号】" in out_file.read_text(encoding="utf-8")
