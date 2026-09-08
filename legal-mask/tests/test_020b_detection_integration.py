"""020-B: Detection integration tests for rules, NER post-processing."""
import json
from pathlib import Path

import pytest

from legal_desens.engine.span import Span
from legal_desens.engine.ner_postprocess import (
    merge_compound_surnames,
    validate_org_suffix,
    merge_address_fragments,
    expand_entity_mentions,
    postprocess_ner_spans,
)


class TestLegalRules:
    """Verify legal regex rules."""

    def test_rules_load(self):
        """Rules should load successfully."""
        from legal_desens.rules import load_rules
        rules = load_rules()
        assert len(rules) >= 10

    def test_passport_rule(self):
        """Passport rule should match."""
        from legal_desens.rules import load_rules
        rules = load_rules()
        passport_rule = next((r for r in rules if r.id == "passport_cn"), None)
        assert passport_rule is not None
        assert passport_rule.pattern

    def test_plate_rule(self):
        """Plate rule should match."""
        from legal_desens.rules import load_rules
        rules = load_rules()
        plate_rule = next((r for r in rules if r.id == "plate_cn"), None)
        assert plate_rule is not None

    def test_bank_card_rule(self):
        """Bank card rule should match."""
        from legal_desens.rules import load_rules
        rules = load_rules()
        card_rule = next((r for r in rules if r.id == "bank_card_cn"), None)
        assert card_rule is not None

    def test_new_rules_reach_real_redaction_pipeline(self):
        """Configured rules must survive profile filtering and redact output."""
        import hashlib
        from legal_desens.profile import load_profile
        from legal_desens.redact import redact
        from legal_desens.rules import load_rules

        text = (
            "护照E12345678，银行卡6225880112345678，"
            "车牌粤B12345，密钥sk_abcdefghijklmnopqrstuvwxyz。"
        )
        output, map_data, _audit = redact(
            text,
            load_rules(),
            hashlib.sha256(text.encode()).hexdigest(),
            profile=load_profile("strict"),
        )
        assert "E12345678" not in output
        assert "6225880112345678" not in output
        assert "粤B12345" not in output
        assert "sk_abcdefghijklmnopqrstuvwxyz" not in output
        assert {e["entity_type"] for e in map_data["entities"]} >= {
            "PASSPORT", "BANK_CARD", "PLATE", "API_TOKEN",
        }


class TestCompoundSurnameMerge:
    """Test Chinese compound surname merging."""

    def test_ouyang_merge(self):
        """欧阳 should be merged with adjacent PER span."""
        spans = [
            Span(entity_type="PER", start=0, end=2, text="欧阳", engine="ner"),
            Span(entity_type="PER", start=2, end=4, text="修文", engine="ner"),
        ]
        result = merge_compound_surnames(spans, "欧阳修文向法院提交")
        assert len(result) == 1
        assert result[0].text == "欧阳修文"

    def test_sima_merge(self):
        """司马 should be merged."""
        spans = [
            Span(entity_type="PER", start=0, end=2, text="司马", engine="ner"),
            Span(entity_type="PER", start=2, end=4, text="光华", engine="ner"),
        ]
        result = merge_compound_surnames(spans, "司马光华签署合同")
        assert len(result) == 1
        assert result[0].text == "司马光华"

    def test_no_merge_regular(self):
        """Regular names should not be merged."""
        spans = [
            Span(entity_type="PER", start=0, end=2, text="张三", engine="ner"),
            Span(entity_type="PER", start=5, end=7, text="李四", engine="ner"),
        ]
        result = merge_compound_surnames(spans, "张三和李四签合同")
        assert len(result) == 2


class TestOrgSuffixValidation:
    """Test ORG suffix validation."""

    def test_company_with_suffix(self):
        """Company with 有限公司 suffix should pass."""
        spans = [
            Span(entity_type="ORG", start=0, end=10, text="深圳市海源节能科技有限公司", engine="ner"),
        ]
        result, warnings = validate_org_suffix(spans, "深圳市海源节能科技有限公司")
        assert len(result) == 1
        assert len(warnings) == 0

    def test_court_with_suffix(self):
        """Court with 法院 suffix should pass."""
        spans = [
            Span(entity_type="ORG", start=0, end=10, text="北京市朝阳区人民法院", engine="ner"),
        ]
        result, warnings = validate_org_suffix(spans, "北京市朝阳区人民法院受理此案")
        assert len(result) == 1

    def test_law_firm_with_suffix(self):
        """Law firm with 律师事务所 suffix should pass."""
        spans = [
            Span(entity_type="ORG", start=0, end=16, text="北京市隆安（深圳）律师事务所", engine="ner"),
        ]
        result, warnings = validate_org_suffix(spans, "北京市隆安（深圳）律师事务所代理此案")
        assert len(result) == 1

    def test_org_without_suffix(self):
        """ORG without suffix should generate warning."""
        spans = [
            Span(entity_type="ORG", start=0, end=3, text="考勤", engine="ner"),
        ]
        result, warnings = validate_org_suffix(spans, "考勤记录显示")
        assert len(warnings) == 1
        assert "org_no_suffix" in warnings[0]["type"]

    def test_org_with_context_trigger(self):
        """ORG with context trigger should pass even without suffix."""
        spans = [
            Span(entity_type="ORG", start=3, end=7, text="综合部", engine="ner"),
        ]
        result, warnings = validate_org_suffix(spans, "被申请人综合部的负责人")
        assert len(result) == 1


class TestAddressMerge:
    """Test address fragment merging."""

    def test_adjacent_loc_merge(self):
        """Adjacent LOC fragments should be merged."""
        spans = [
            Span(entity_type="LOC", start=0, end=3, text="深圳市", engine="ner"),
            Span(entity_type="LOC", start=3, end=6, text="福田区", engine="ner"),
        ]
        result = merge_address_fragments(spans, "深圳市福田区荣超商务中心")
        assert len(result) == 1
        assert result[0].entity_type == "ADDRESS"

    def test_separate_address_no_merge(self):
        """Separate addresses should not merge."""
        spans = [
            Span(entity_type="LOC", start=0, end=3, text="深圳市", engine="ner"),
            Span(entity_type="LOC", start=20, end=23, text="北京市", engine="ner"),
        ]
        result = merge_address_fragments(spans, "深圳市的公司和北京市的法院")
        assert len(result) == 2


class TestEntityExpansion:
    """Test entity mention expansion."""

    def test_expand_same_name(self):
        """Same person name should be expanded throughout text."""
        text = "张三向法院提交申请。张三的身份证号已验证。"
        spans = [
            Span(entity_type="PER", start=0, end=2, text="张三", engine="ner"),
        ]
        result = expand_entity_mentions(spans, text)
        assert len(result) >= 2
        per_spans = [s for s in result if s.entity_type == "PER"]
        assert len(per_spans) == 2


class TestPostprocessIntegration:
    """Integration test for full post-processing pipeline."""

    def test_full_pipeline(self):
        """Full pipeline should process correctly."""
        text = "申请人张三于2022年9月入职深圳市海源节能科技有限公司。"
        spans = [
            Span(entity_type="PER", start=3, end=5, text="张三", engine="ner"),
            Span(entity_type="ORG", start=12, end=25, text="深圳市海源节能科技有限公司", engine="ner"),
        ]
        result, warnings = postprocess_ner_spans(spans, text)
        assert len(result) >= 2
        # Should not have org_no_suffix warnings for valid company
        org_warnings = [w for w in warnings if "org_no_suffix" in w.get("type", "")]
        assert len(org_warnings) == 0

    def test_redact_calls_ner_postprocess(self, monkeypatch):
        """The production redact path must merge compound-surname NER spans."""
        import hashlib
        import legal_desens.redact as redact_module
        from legal_desens.profile import load_profile

        text = "欧阳修文提交申请"
        monkeypatch.setattr(
            redact_module,
            "scan_ner_with_warnings",
            lambda _text, _model_dir=None: ([
                Span(entity_type="PER", start=0, end=2, text="欧阳", engine="ner"),
                Span(entity_type="PER", start=2, end=4, text="修文", engine="ner"),
            ], []),
        )
        output, map_data, _audit = redact_module.redact(
            text,
            [],
            hashlib.sha256(text.encode()).hexdigest(),
            mode="regex+ner",
            profile=load_profile("labor"),
        )
        assert output == "【姓名】提交申请"
        assert map_data["entities"][0]["original"] == "欧阳修文"

    def test_cluener_labels_map_to_canonical_policy(self, monkeypatch):
        """CLUENER labels must use canonical labels and preserve non-PII classes."""
        import hashlib
        import legal_desens.redact as redact_module
        from legal_desens.profile import load_profile

        text = "张三在海源科技有限公司任律师"
        monkeypatch.setattr(
            redact_module,
            "scan_ner_with_warnings",
            lambda _text, _model_dir=None: ([
                Span(entity_type="name", start=0, end=2, text="张三", engine="ner"),
                Span(entity_type="company", start=3, end=11, text="海源科技有限公司", engine="ner"),
                Span(entity_type="position", start=12, end=14, text="律师", engine="ner"),
            ], []),
        )
        output, map_data, _audit = redact_module.redact(
            text,
            [],
            hashlib.sha256(text.encode()).hexdigest(),
            mode="regex+ner",
            profile=load_profile("labor"),
        )
        assert output == "【姓名】在【机构】任律师"
        assert {e["entity_type"] for e in map_data["entities"]} == {"PERSON", "ORG"}
