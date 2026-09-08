"""Tests for 015: profile-based desensitization policy."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.io import read_text
from legal_desens.rules import load_rules
from legal_desens.profile import load_profile, resolve_profile_name
from legal_desens.redact import redact, LabelAllocator, _scan_time_expressions
from legal_desens.restore import restore
from legal_desens.audit import audit
from legal_desens.engine.span import Span
from legal_desens.engine.merge import merge_spans


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")
PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "legal_desens", "profiles")


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


@pytest.fixture
def labor():
    return load_profile("labor", PROFILES_DIR)


@pytest.fixture
def strict():
    return load_profile("strict", PROFILES_DIR)


# ── 1. Profile loading ─────────────────────────────────────────────────────

class TestProfileLoading:
    def test_load_labor(self, labor):
        assert labor.name == "labor"
        assert labor.label_style == "bracket_unnumbered"
        assert labor.should_redact("PERSON") is True
        assert labor.should_redact("TIME") is False
        assert labor.should_redact("MONEY") is False

    def test_load_strict(self, strict):
        assert strict.name == "strict"
        assert strict.should_redact("PERSON") is True
        assert strict.should_redact("TIME") is True
        assert strict.should_redact("MONEY") is True

    def test_resolve_profile_name_default(self):
        assert resolve_profile_name(None, None) == "labor"

    def test_resolve_profile_name_explicit(self):
        assert resolve_profile_name("strict", None) == "strict"

    def test_resolve_profile_name_level_compat(self):
        assert resolve_profile_name(None, "strict") == "strict"

    def test_profile_label_text(self, labor):
        assert labor.get_label_text("PERSON") == "【姓名】"
        assert labor.get_label_text("PHONE") == "【手机号】"
        assert labor.get_label_text("ADDRESS") == "【地址】"
        assert labor.get_label_text("MONEY") is None  # preserve, no label

    def test_unknown_type_defaults_to_redact(self, labor):
        assert labor.should_redact("UNKNOWN_TYPE") is True


# ── 2. Bracket unnumbered labels ──────────────────────────────────────────

class TestBracketLabels:
    def test_unnumbered_labels(self, rules, labor):
        alloc = LabelAllocator(rules, profile=labor)
        _, label1 = alloc.get_label("PERSON", "张三")
        _, label2 = alloc.get_label("PERSON", "李四")
        assert label1 == "【姓名】"
        assert label2 == "【姓名】"

    def test_entity_ids_still_unique(self, rules, labor):
        alloc = LabelAllocator(rules, profile=labor)
        eid1, _ = alloc.get_label("PERSON", "张三")
        eid2, _ = alloc.get_label("PERSON", "李四")
        assert eid1 != eid2
        assert eid1 == "PERSON_1"
        assert eid2 == "PERSON_2"

    def test_same_entity_reuses(self, rules, labor):
        alloc = LabelAllocator(rules, profile=labor)
        eid1, label1 = alloc.get_label("PHONE", "13800138000")
        eid2, label2 = alloc.get_label("PHONE", "13800138000")
        assert eid1 == eid2
        assert label1 == label2

    def test_different_types_different_labels(self, rules, labor):
        alloc = LabelAllocator(rules, profile=labor)
        _, l_phone = alloc.get_label("PHONE", "13800138000")
        _, l_id = alloc.get_label("ID_CARD", "110101199001011234")
        _, l_email = alloc.get_label("EMAIL", "test@x.com")
        assert l_phone == "【手机号】"
        assert l_id == "【身份证号】"
        assert l_email == "【邮箱】"


# ── 3. Redact/preserve split ──────────────────────────────────────────────

class TestRedactPreserve:
    @pytest.mark.parametrize("date_text", [
        "2026年6月20日",
        "2026 年 6 月 20 日",
        "2026-06-20",
        "2026/6/20",
        "2026年6月",
    ])
    def test_time_detection_uses_complete_date(self, date_text):
        spans = _scan_time_expressions(f"日期为{date_text}。")
        assert [span.text for span in spans] == [date_text]

    def test_prepare_entity_policy_preserves_dates(self, tmp_path):
        source = tmp_path / "source.txt"
        source.write_text("入职日期为2026年6月20日。", encoding="utf-8")
        policy = tmp_path / "policy.json"
        policy.write_text(
            json.dumps({"preserve_types": ["DATE", "TIME"]}),
            encoding="utf-8",
        )
        manifest = tmp_path / "manifest.json"

        result = subprocess.run(
            [
                sys.executable, "-m", "legal_desens.cli", "prepare",
                str(source), "--level", "strict", "--regex-only",
                "--entity-policy", str(policy), "--manifest", str(manifest),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert not any(
            candidate["entityType"] in {"DATE", "TIME"}
            for candidate in data["candidates"]
        )

    def test_labor_preserves_time(self, rules, labor):
        text = "申请人于2022年9月1日入职。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)
        # TIME should be preserved
        assert "2022年9月1日" in redacted
        time_entities = [e for e in map_data["entities"] if e["entity_type"] == "TIME"]
        assert len(time_entities) == 0

    def test_labor_preserves_money(self, rules, labor):
        text = "月工资15000元，经济补偿金30000元。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)
        assert "15000元" in redacted
        assert "30000元" in redacted
        money_entities = [e for e in map_data["entities"] if e["entity_type"] == "MONEY"]
        assert len(money_entities) == 0

    def test_strict_redacts_time(self, rules, strict):
        text = "申请人于2022年9月1日入职。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=strict)
        assert "2022年9月1日" not in redacted
        assert "【时间】" in redacted
        time_entities = [e for e in map_data["entities"] if e["entity_type"] == "TIME"]
        assert len(time_entities) == 1

    def test_strict_redacts_money(self, rules, strict):
        text = "月工资15000元。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=strict)
        assert "15000元" not in redacted
        assert "【金额】" in redacted
        money_entities = [e for e in map_data["entities"] if e["entity_type"] == "MONEY"]
        assert len(money_entities) >= 1


# ── 4. Full labor profile integration ─────────────────────────────────────

class TestLaborProfile:
    def test_labor_example(self, rules, labor, monkeypatch):
        """The canonical example from the plan doc."""
        # Simulate NER finding PERSON and ORG
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"张三", text):
                spans.append(Span("PERSON", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            for m in re.finditer(r"深圳市某科技有限公司", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=1))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "申请人张三于2022年9月1日入职深圳市某科技有限公司，月工资15000元，住址深圳市福田区某路某号，联系电话15812345678。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, audit_data = redact(text, rules, source_sha, mode="regex+ner", profile=labor)

        # TIME preserved
        assert "2022年9月1日" in redacted
        # MONEY preserved
        assert "15000元" in redacted
        # PERSON redacted
        assert "张三" not in redacted
        assert "【姓名】" in redacted
        # PHONE redacted
        assert "15812345678" not in redacted
        assert "【手机号】" in redacted

    def test_labor_roundtrip(self, rules, labor):
        """redact→restore roundtrip with labor profile."""
        text = "月工资15000元，电话13800138000，邮箱test@example.com。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)

        # MONEY preserved, PHONE redacted, EMAIL redacted
        assert "15000元" in redacted
        assert "13800138000" not in redacted

        redacted_sha = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        restored = restore(redacted, map_data, redacted_file_sha256=redacted_sha)
        assert restored == text

    def test_strict_roundtrip(self, rules, strict):
        """redact→restore roundtrip with strict profile."""
        text = "月工资15000元，电话13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=strict)

        # Both MONEY and PHONE redacted in strict
        assert "15000元" not in redacted
        assert "13800138000" not in redacted

        redacted_sha = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        map_data["redacted_sha256"] = redacted_sha
        restored = restore(redacted, map_data, redacted_file_sha256=redacted_sha)
        assert restored == text

    def test_labor_id_card_redacted(self, rules, labor):
        text = "身份证号110101199001011234。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, _, _ = redact(text, rules, source_sha, profile=labor)
        assert "110101199001011234" not in redacted
        assert "【身份证号】" in redacted

    def test_labor_email_redacted(self, rules, labor):
        text = "邮箱test@example.com。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, _, _ = redact(text, rules, source_sha, profile=labor)
        assert "test@example.com" not in redacted
        assert "【邮箱】" in redacted

    def test_labor_org_code_redacted(self, rules, labor):
        text = "统一社会信用代码91440300MA5F1234AB。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, _, _ = redact(text, rules, source_sha, profile=labor)
        assert "91440300MA5F1234AB" not in redacted
        assert "【统一社会信用代码】" in redacted


# ── 5. Residual scan profile-aware ────────────────────────────────────────

class TestProfileAwareResidual:
    def test_labor_residual_passes_with_preserved_money(self, rules, labor):
        """After labor redaction, residual scan should not flag preserved MONEY."""
        text = "月工资15000元，电话13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, _, audit_data = redact(text, rules, source_sha, profile=labor)
        # MONEY is preserved in labor → residual scan should NOT flag it
        assert audit_data["residual_scan"]["passed"] is True
        money_findings = [
            f for f in audit_data["residual_scan"]["findings"]
            if f["entity_type"] == "MONEY"
        ]
        assert len(money_findings) == 0

    def test_strict_residual_finds_money(self, rules, strict):
        """With strict profile, MONEY in redacted text IS a residual finding."""
        # First redact with labor (preserve money), then audit with strict
        text = "月工资15000元。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        labor = load_profile("labor", PROFILES_DIR)
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)
        # Now audit with strict — the preserved MONEY should be flagged
        result = audit(redacted, map_data, rules, profile=strict)
        # strict checks MONEY, so residual should fail
        money_findings = [
            f for f in result["residual_scan"]["findings"]
            if f["entity_type"] == "MONEY"
        ]
        assert len(money_findings) > 0

    def test_audit_standalone_profile_aware(self, rules, labor):
        """Standalone audit command respects profile."""
        text = "月工资15000元，电话13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)
        result = audit(redacted, map_data, rules, profile=labor)
        assert result["residual_scan"]["passed"] is True


# ── 6. Map schema with profile ────────────────────────────────────────────

class TestMapWithProfile:
    def test_map_contains_profile(self, rules, labor):
        text = "电话13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _, map_data, _ = redact(text, rules, source_sha, profile=labor)
        assert map_data["profile"] == "labor"

    def test_map_strict_profile(self, rules, strict):
        text = "电话13800138000。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _, map_data, _ = redact(text, rules, source_sha, profile=strict)
        assert map_data["profile"] == "strict"


# ── 7. Address merge ──────────────────────────────────────────────────────

class TestAddressMerge:
    def test_loc_fragments_merge(self, rules, labor):
        """Adjacent LOC fragments should merge into single ADDRESS."""
        from legal_desens.engine.address_merge import merge_addresses
        text = "住址福田区某路某号。"
        # "福"=2, "田"=3, "区"=4, "某"=5, "路"=6, "某"=7, "号"=8
        spans = [
            Span("LOC", 2, 5, "福田区", "ner", priority=50, discovery_order=0),
            Span("LOC", 5, 8, "某路某", "ner", priority=50, discovery_order=1),
        ]
        merged = merge_addresses(spans, text)
        addresses = [s for s in merged if s.entity_type == "ADDRESS"]
        assert len(addresses) >= 1
        if addresses:
            assert "福田区" in addresses[0].text

    def test_address_merge_stops_at_org(self, rules, labor):
        """Address merge should not consume ORG boundaries."""
        from legal_desens.engine.address_merge import merge_addresses
        text = "福田区某科技有限公司"
        # "福"=0, "田"=1, "区"=2, "某"=3, "科"=4, "技"=5
        spans = [
            Span("LOC", 0, 3, "福田区", "ner", priority=50, discovery_order=0),
            Span("ORG", 3, 9, "某科技有限公司", "ner", priority=50, discovery_order=1),
        ]
        merged = merge_addresses(spans, text)
        # ORG should not be consumed into ADDRESS
        orgs = [s for s in merged if s.entity_type == "ORG"]
        assert len(orgs) == 1
        assert "科技有限公司" in orgs[0].text

    def test_single_loc_becomes_address(self, rules, labor, monkeypatch):
        """A single unmerged LOC span should still be redacted as ADDRESS."""
        def fake_scan_ner(text, model_dir=None):
            start = text.index("福田区")
            return [Span("LOC", start, start + 3, "福田区", "ner", priority=50, discovery_order=0)], []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)
        text = "住址福田区。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, mode="regex+ner", profile=labor)
        assert "福田区" not in redacted
        assert "【地址】" in redacted
        assert map_data["entities"][0]["entity_type"] == "ADDRESS"


# ── 8. Abbreviation dictionary ────────────────────────────────────────────

class TestAbbreviation:
    def test_abbrev_dict_extraction(self):
        from legal_desens.engine.abbrev import build_abbrev_dict
        d = build_abbrev_dict(["深圳市海源科技有限公司"])
        # Stem: "深圳市" stripped → "海源科技有限公司" → "有限公司" stripped → "海源科技"
        assert "海源科技公司" in d

    def test_abbrev_stem_min_length(self):
        from legal_desens.engine.abbrev import build_abbrev_dict
        # "大" is too short (< 2 chars)
        d = build_abbrev_dict(["深圳市大有限公司"])
        # stem "大" → too short, should be excluded
        assert "大公司" not in d

    def test_abbrev_finds_in_text(self):
        from legal_desens.engine.abbrev import find_abbreviations
        text = "深圳市海源科技有限公司成立后，海源科技公司多次违约。"
        existing = [
            Span("ORG", 0, 11, "深圳市海源科技有限公司", "regex", priority=100, discovery_order=0),
        ]
        org_full_names = ["深圳市海源科技有限公司"]
        abbrev_spans = find_abbreviations(text, org_full_names, existing)
        assert any("海源科技公司" in s.text for s in abbrev_spans)

    def test_abbrev_only_after_full_name_in_doc(self):
        """Abbreviations only found when full name appears in the document."""
        from legal_desens.engine.abbrev import find_abbreviations
        text = "海源公司违约。"  # No full name in doc
        abbrev_spans = find_abbreviations(text, [], [])
        assert len(abbrev_spans) == 0


# ── 9. BANK_ACCOUNT context-aware ─────────────────────────────────────────

class TestBankAccountContext:
    def test_context_trigger_redacts(self, rules, labor):
        """With context keywords, digit sequence → BANK_ACCOUNT."""
        text = "收款账号11005545236302，联系电话15817465075。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)
        assert "11005545236302" not in redacted
        assert "【银行账号】" in redacted

    def test_bare_long_digits_warning(self, rules, labor):
        """Bare long digits without context → warning, not auto-redact."""
        text = "工号100234567890。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, audit_data = redact(text, rules, source_sha, profile=labor)
        # Should NOT be auto-redacted
        assert "100234567890" in redacted
        # Should have a warning
        bare_warnings = [
            w for w in audit_data["warnings"]
            if w.get("type") == "bare_long_digits_no_context"
        ]
        assert len(bare_warnings) >= 1

    def test_money_and_bank_account_no_cross(self, rules, labor):
        """MONEY preserved, BANK_ACCOUNT redacted, no cross-contamination."""
        text = "月工资15000元，银行账号1234567890123456789。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, _ = redact(text, rules, source_sha, profile=labor)
        # MONEY preserved
        assert "15000元" in redacted
        # BANK_ACCOUNT redacted (has context keyword 银行账号)
        assert "1234567890123456789" not in redacted

    def test_bank_branch_redacted(self, rules, labor):
        text = "开户行平安银行深圳支行。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, _, _ = redact(text, rules, source_sha, profile=labor)
        assert "平安银行深圳支行" not in redacted
        assert "【银行信息】" in redacted


# ── 10. LANDLINE ──────────────────────────────────────────────────────────

class TestLandline:
    def test_landline_redacted_in_labor(self, rules, labor):
        text = "座机0755-23982682。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, _, _ = redact(text, rules, source_sha, profile=labor)
        assert "0755-23982682" not in redacted
        assert "【电话】" in redacted


# ── 11. CLI --profile integration ─────────────────────────────────────────

class TestCLIProfile:
    def test_cli_profile_labor(self, tmp_path):
        from legal_desens.cli import main
        input_file = tmp_path / "input.txt"
        out_file = tmp_path / "out.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("月工资15000元，电话13800138000。", encoding="utf-8")

        ret = main([
            "redact", str(input_file),
            "--profile", "labor",
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        output = out_file.read_text(encoding="utf-8")
        assert "15000元" in output  # MONEY preserved
        assert "13800138000" not in output  # PHONE redacted
        assert "【手机号】" in output

        map_data = json.loads(map_file.read_text(encoding="utf-8"))
        assert map_data["profile"] == "labor"

    def test_cli_profile_strict(self, tmp_path):
        from legal_desens.cli import main
        input_file = tmp_path / "input.txt"
        out_file = tmp_path / "out.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("月工资15000元，电话13800138000。", encoding="utf-8")

        ret = main([
            "redact", str(input_file),
            "--profile", "strict",
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        output = out_file.read_text(encoding="utf-8")
        assert "15000元" not in output  # MONEY redacted in strict
        assert "【金额】" in output

    def test_cli_level_strict_compat(self, tmp_path):
        from legal_desens.cli import main
        input_file = tmp_path / "input.txt"
        out_file = tmp_path / "out.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("月工资15000元。", encoding="utf-8")

        ret = main([
            "redact", str(input_file),
            "--level", "strict",
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        map_data = json.loads(map_file.read_text(encoding="utf-8"))
        assert map_data["profile"] == "strict"

    def test_cli_default_is_labor(self, tmp_path):
        from legal_desens.cli import main
        input_file = tmp_path / "input.txt"
        out_file = tmp_path / "out.txt"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("月工资15000元。", encoding="utf-8")

        ret = main([
            "redact", str(input_file),
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        output = out_file.read_text(encoding="utf-8")
        assert "15000元" in output  # Default labor preserves MONEY
        map_data = json.loads(map_file.read_text(encoding="utf-8"))
        assert map_data["profile"] == "labor"

    def test_csv_labor_residual_ignores_preserved_money(self, tmp_path):
        from legal_desens.cli import main
        input_file = tmp_path / "input.csv"
        out_file = tmp_path / "out.csv"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        input_file.write_text("name,wage,phone\n张三,15000元,13800138000\n", encoding="utf-8")

        ret = main([
            "redact", str(input_file),
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        assert audit_data["profile"] == "labor"
        assert audit_data["residual_scan"]["passed"] is True

    def test_docx_uses_profile_bracket_labels(self, tmp_path):
        from legal_desens.cli import main
        from legal_desens.adapters.docx_adapter import DOCXAdapter
        from docx import Document

        input_file = tmp_path / "input.docx"
        out_file = tmp_path / "out.docx"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        doc = Document()
        doc.add_paragraph("联系电话13800138000。")
        doc.save(input_file)

        ret = main([
            "redact", str(input_file),
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        text, _ = DOCXAdapter().extract_text(str(out_file))
        assert "手机号1" not in text
        assert "【手机号】" in text
        map_data = json.loads(map_file.read_text(encoding="utf-8"))
        assert map_data["profile"] == "labor"

    def test_xlsx_uses_profile_bracket_labels(self, tmp_path):
        from legal_desens.cli import main
        from legal_desens.adapters.xlsx_adapter import XLSXAdapter
        from openpyxl import Workbook

        input_file = tmp_path / "input.xlsx"
        out_file = tmp_path / "out.xlsx"
        map_file = tmp_path / "map.json"
        audit_file = tmp_path / "audit.json"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "联系电话13800138000。"
        wb.save(input_file)

        ret = main([
            "redact", str(input_file),
            "--regex-only",
            "--out", str(out_file),
            "--map", str(map_file),
            "--audit", str(audit_file),
        ])

        assert ret == 0
        text, _ = XLSXAdapter().extract_text(str(out_file))
        assert "手机号1" not in text
        assert "【手机号】" in text
        map_data = json.loads(map_file.read_text(encoding="utf-8"))
        assert map_data["profile"] == "labor"
