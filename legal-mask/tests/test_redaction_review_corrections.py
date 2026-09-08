"""Tests for 017: Redaction review corrections (allowlist/denylist/ORG gate)."""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.io import read_text
from legal_desens.rules import load_rules
from legal_desens.profile import load_profile, resolve_profile_name
from legal_desens.redact import redact
from legal_desens.engine.span import Span
from legal_desens.engine.org_gate import validate_org, apply_org_gate, OrgGateResult
from legal_desens.engine.allowlist import (
    BUILTIN_ALLOWLIST,
    load_allowlist,
    is_allowlist_applicable,
    is_structural_pii,
)


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "rules", "rules.json")
PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "legal_desens", "profiles")


@pytest.fixture
def rules():
    return load_rules(RULES_PATH)


@pytest.fixture
def labor():
    return load_profile("labor", PROFILES_DIR)


# ── 1. ORG gate: suffix check ──────────────────────────────────────────────

class TestOrgGateSuffix:
    def test_org_with_suffix_passes(self):
        """ORG with company suffix should pass the gate."""
        span = Span("ORG", 0, 12, "某科技有限公司", "ner", priority=50)
        result = validate_org(span, "某科技有限公司成立后...")
        assert result.passed is True
        assert result.reason == "suffix"
        assert result.matched_suffix == "有限公司"

    def test_org_with_bank_suffix(self):
        span = Span("ORG", 0, 8, "平安银行深圳支行", "ner", priority=50)
        result = validate_org(span, "开户行平安银行深圳支行...")
        assert result.passed is True
        assert result.reason == "suffix"

    def test_org_with_court_suffix(self):
        span = Span("ORG", 0, 12, "深圳市中级人民法院", "ner", priority=50)
        result = validate_org(span, "由深圳市中级人民法院审理...")
        assert result.passed is True
        assert result.reason == "suffix"

    def test_org_with_arbitration_suffix(self):
        span = Span("ORG", 0, 12, "深圳仲裁委员会", "ner", priority=50)
        result = validate_org(span, "提交深圳仲裁委员会仲裁...")
        assert result.passed is True
        assert result.reason == "suffix"


# ── 2. ORG gate: context trigger ────────────────────────────────────────────

class TestOrgGateContext:
    def test_context_trigger_applicant(self):
        """Context trigger '被申请人' should pass the gate."""
        span = Span("ORG", 4, 8, "海源", "ner", priority=50)
        text = "被申请人海源应支付..."
        result = validate_org(span, text)
        assert result.passed is True
        assert result.reason == "context"
        assert result.matched_context == "被申请人"

    def test_context_trigger_employer(self):
        span = Span("ORG", 4, 8, "海源", "ner", priority=50)
        text = "用人单位海源未签订..."
        result = validate_org(span, text)
        assert result.passed is True
        assert result.reason == "context"

    def test_context_trigger_bank_account(self):
        span = Span("ORG", 4, 8, "海源", "ner", priority=50)
        text = "开户行海源账户..."
        result = validate_org(span, text)
        assert result.passed is True
        assert result.reason == "context"

    def test_context_trigger_legal_rep(self):
        span = Span("ORG", 6, 10, "海源", "ner", priority=50)
        text = "法定代表人海源张三..."
        result = validate_org(span, text)
        assert result.passed is True
        assert result.reason == "context"


# ── 3. ORG gate: bare short word → no match ────────────────────────────────

class TestOrgGateNoMatch:
    def test_bare_short_word_no_match(self):
        """Bare short word without suffix/context should NOT pass."""
        span = Span("ORG", 0, 2, "考勤", "ner", priority=50)
        text = "考勤负责..."
        result = validate_org(span, text)
        assert result.passed is False
        assert result.reason == "no_match"
        assert result.suggested_action == "疑似普通词，待复核"

    def test_bare_word_no_suffix(self):
        span = Span("ORG", 0, 3, "考勤", "ner", priority=50)
        text = "考勤记录显示..."
        result = validate_org(span, text)
        assert result.passed is False
        assert result.reason == "no_match"


# ── 4. Precedence: denylist > allowlist > gate ──────────────────────────────

class TestPrecedence:
    def test_denylist_overrides_allowlist(self):
        """Denylist should override allowlist."""
        span = Span("ORG", 0, 6, "海源公司", "ner", priority=50)
        text = "海源公司违约..."
        allowlist = {"海源公司"}  # In allowlist
        denylist = {"海源公司"}   # Also in denylist

        result = validate_org(span, text, allowlist=allowlist, denylist=denylist)
        assert result.passed is True
        assert result.reason == "denylist"

    def test_denylist_overrides_gate(self):
        """Denylist should override ORG gate (even without suffix)."""
        span = Span("ORG", 0, 4, "海源", "ner", priority=50)
        text = "海源违约..."
        denylist = {"海源"}

        result = validate_org(span, text, denylist=denylist)
        assert result.passed is True
        assert result.reason == "denylist"

    def test_allowlist_overrides_gate(self):
        """Allowlist should override ORG gate."""
        span = Span("ORG", 0, 4, "综合部", "ner", priority=50)
        text = "综合部负责..."
        allowlist = {"综合部"}

        result = validate_org(span, text, allowlist=allowlist)
        assert result.passed is False
        assert result.reason == "allowlist"

    def test_gate_used_when_no_list_match(self):
        """ORG gate should be used when no allowlist/denylist match."""
        span = Span("ORG", 0, 12, "某科技有限公司", "ner", priority=50)
        text = "某科技有限公司成立..."

        result = validate_org(span, text)
        assert result.passed is True
        assert result.reason == "suffix"


# ── 5. Allowlist: only for NER types, not structural PII ────────────────────

class TestAllowlistRestrictions:
    def test_allowlist_only_for_org_address(self):
        """Allowlist should only apply to ORG and ADDRESS types."""
        assert is_allowlist_applicable("ORG") is True
        assert is_allowlist_applicable("ADDRESS") is True
        assert is_allowlist_applicable("PERSON") is False
        assert is_allowlist_applicable("PHONE") is False
        assert is_allowlist_applicable("ID_CARD") is False

    def test_structural_pii_types(self):
        """Structural PII types should be identified correctly."""
        assert is_structural_pii("PHONE") is True
        assert is_structural_pii("ID_CARD") is True
        assert is_structural_pii("BANK_ACCOUNT") is True
        assert is_structural_pii("ORG") is False
        assert is_structural_pii("ADDRESS") is False


# ── 6. Denylist: forces redaction ────────────────────────────────────────────

class TestDenylist:
    def test_denylist_forces_redaction(self):
        """Denylist term should be forced redacted even if in allowlist."""
        span = Span("ORG", 0, 6, "海源公司", "ner", priority=50)
        text = "海源公司违约后..."
        allowlist = {"海源公司"}
        denylist = {"海源公司"}

        result = validate_org(span, text, allowlist=allowlist, denylist=denylist)
        assert result.passed is True
        assert result.reason == "denylist"
        assert "强制脱敏" in result.suggested_action


# ── 7. Full integration: redact with ORG gate ────────────────────────────────

class TestRedactWithOrgGate:
    def test_ordinary_word_not_redacted(self, rules, labor, monkeypatch):
        """Ordinary word labeled as ORG should NOT be redacted."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"考勤", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "考勤记录显示员工迟到。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, audit_data = redact(text, rules, source_sha, mode="regex+ner", profile=labor)

        # "考勤" should NOT be redacted
        assert "考勤" in redacted
        # Should have warning about bare short word
        bare_warnings = [w for w in audit_data["warnings"] if w.get("type") == "org_bare_short_word"]
        assert len(bare_warnings) >= 1

    def test_org_with_suffix_redacted(self, rules, labor, monkeypatch):
        """ORG with suffix should be redacted."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"某科技有限公司", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "某科技有限公司成立后..."
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, audit_data = redact(text, rules, source_sha, mode="regex+ner", profile=labor)

        # "某科技有限公司" should be redacted
        assert "某科技有限公司" not in redacted
        assert "【机构】" in redacted

    def test_context_trigger_redacted(self, rules, labor, monkeypatch):
        """ORG with context trigger should be redacted."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"海源", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "被申请人海源应支付..."
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, audit_data = redact(text, rules, source_sha, mode="regex+ner", profile=labor)

        # "海源" should be redacted (context trigger)
        assert "海源" not in redacted
        assert "【机构】" in redacted

    def test_denylist_forces_redaction(self, rules, labor, monkeypatch):
        """Denylist term should be forced redacted."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"海源", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "海源违约后..."
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        denylist = {"海源"}
        redacted, map_data, audit_data = redact(
            text, rules, source_sha, mode="regex+ner", profile=labor, denylist=denylist,
        )

        # "海源" should be redacted
        assert "海源" not in redacted
        assert "【机构】" in redacted

    def test_allowlist_not_redacted(self, rules, labor, monkeypatch):
        """Allowlist term should NOT be redacted."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"考勤", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "考勤记录显示..."
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        allowlist = {"考勤"}
        redacted, map_data, audit_data = redact(
            text, rules, source_sha, mode="regex+ner", profile=labor, allowlist=allowlist,
        )

        # "考勤" should NOT be redacted
        assert "考勤" in redacted

    def test_structural_pii_not_affected_by_allowlist(self, rules, labor):
        """Structural PII (PHONE, ID_CARD, etc.) should NOT be affected by allowlist."""
        text = "电话13800138000，身份证号110101199001011234。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        allowlist = {"13800138000", "110101199001011234"}  # Try to allowlist PII
        redacted, map_data, audit_data = redact(
            text, rules, source_sha, mode="regex+ner", profile=labor, allowlist=allowlist,
        )

        # PII should still be redacted
        assert "13800138000" not in redacted
        assert "110101199001011234" not in redacted
        assert "【手机号】" in redacted
        assert "【身份证号】" in redacted


# ── 8. Audit warnings ────────────────────────────────────────────────────────

class TestAuditWarnings:
    def test_bare_short_word_warning(self, rules, labor, monkeypatch):
        """Bare short word ORG should generate audit warning."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"考勤", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "考勤记录显示..."
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        redacted, map_data, audit_data = redact(text, rules, source_sha, mode="regex+ner", profile=labor)

        # Should have warning
        bare_warnings = [w for w in audit_data["warnings"] if w.get("type") == "org_bare_short_word"]
        assert len(bare_warnings) >= 1
        assert "疑似普通词，待复核" in bare_warnings[0]["message"]

    def test_allowlist_warning(self, rules, labor, monkeypatch):
        """Allowlisted ORG should generate audit warning with suggested action."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            for m in re.finditer(r"考勤", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "考勤记录显示..."
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        allowlist = {"考勤"}
        redacted, map_data, audit_data = redact(
            text, rules, source_sha, mode="regex+ner", profile=labor, allowlist=allowlist,
        )

        # Should have warning with suggested action
        allowlist_warnings = [w for w in audit_data["warnings"] if w.get("type") == "org_allowlisted"]
        assert len(allowlist_warnings) >= 1
        assert "建议 allowlist" in allowlist_warnings[0]["suggested_action"]


# ── 9. Built-in allowlist ────────────────────────────────────────────────────

class TestBuiltinAllowlist:
    def test_builtin_allowlist_contains_common_terms(self):
        """Built-in allowlist should contain common labor-case terms."""
        assert "综合部" in BUILTIN_ALLOWLIST
        assert "人力资源" in BUILTIN_ALLOWLIST
        assert "劳动合同" in BUILTIN_ALLOWLIST
        assert "经济补偿金" in BUILTIN_ALLOWLIST

    def test_load_allowlist_builtin(self):
        """Loading allowlist with builtin should include built-in terms."""
        allowlist = load_allowlist(builtin=True)
        assert "综合部" in allowlist
        assert "人力资源" in allowlist

    def test_load_allowlist_case_file(self, tmp_path):
        """Loading allowlist with case file should include case-specific terms."""
        case_file = tmp_path / "allowlist.txt"
        case_file.write_text("# Case-specific allowlist\n综合部\n项目组\n", encoding="utf-8")

        allowlist = load_allowlist(builtin=False, case_file=str(case_file))
        assert "综合部" in allowlist
        assert "项目组" in allowlist
        # Built-in terms should NOT be included
        assert "人力资源" not in allowlist


# ── 10. Entity policy ────────────────────────────────────────────────────────

class TestEntityPolicy:
    def test_entity_policy_preserve_types(self, rules):
        """Entity policy preserve_types should prevent redaction."""
        from legal_desens.profile import EntityPolicy

        policy = EntityPolicy(preserve_types={"ORG"})
        profile = load_profile("labor", PROFILES_DIR, entity_policy_file=None)
        profile.entity_policy = policy

        # ORG should be preserved
        assert profile.should_redact("ORG") is False
        # Other types should follow profile
        assert profile.should_redact("PERSON") is True
        assert profile.should_redact("PHONE") is True

    def test_entity_policy_force_redact_types(self, rules):
        """Entity policy force_redact_types should force redaction."""
        from legal_desens.profile import EntityPolicy

        policy = EntityPolicy(force_redact_types={"TIME"})
        profile = load_profile("labor", PROFILES_DIR, entity_policy_file=None)
        profile.entity_policy = policy

        # TIME should be force redacted
        assert profile.should_redact("TIME") is True
        # Other types should follow profile
        assert profile.should_redact("MONEY") is False


# ── 11. Precedence test with all three levels ────────────────────────────────

class TestPrecedenceIntegration:
    def test_precedence_denylist_allowlist_gate(self, rules, labor, monkeypatch):
        """Test precedence: denylist > allowlist > gate."""
        def fake_scan_ner(text, model_dir=None):
            spans = []
            import re
            # 海源: in denylist → should be redacted
            for m in re.finditer(r"海源", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=0))
            # 考勤: in allowlist → should NOT be redacted
            for m in re.finditer(r"考勤", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=1))
            # 某科技有限公司: has suffix → should be redacted
            for m in re.finditer(r"某科技有限公司", text):
                spans.append(Span("ORG", m.start(), m.end(), m.group(), "ner", priority=50, discovery_order=2))
            return spans, []

        monkeypatch.setattr("legal_desens.redact.scan_ner_with_warnings", fake_scan_ner)

        text = "海源与考勤在某科技有限公司开会。"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        denylist = {"海源"}
        allowlist = {"考勤"}

        redacted, map_data, audit_data = redact(
            text, rules, source_sha, mode="regex+ner", profile=labor,
            allowlist=allowlist, denylist=denylist,
        )

        # denylist: 海源 → redacted
        assert "海源" not in redacted
        # allowlist: 考勤 → NOT redacted
        assert "考勤" in redacted
        # gate: 某科技有限公司 → redacted (has suffix)
        assert "某科技有限公司" not in redacted
        assert "【机构】" in redacted
