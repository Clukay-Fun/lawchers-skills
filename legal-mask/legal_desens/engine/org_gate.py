"""ORG secondary validation gate: suffix + context triggers.

NER-labeled ORG entities are not directly redacted; they must pass
either a suffix check or a context trigger check. If neither passes,
the entity is not redacted and gets an audit warning "疑似普通词，待复核".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .span import Span

# ORG suffixes that indicate real organizations
_ORG_SUFFIXES = [
    "公司", "有限公司", "有限责任公司", "股份有限公司", "股份公司",
    "集团", "集团公司",
    "律师事务所", "法律服务所", "法律援助中心", "事务所",
    "银行", "支行", "分行", "信用社",
    "法院", "中级人民法院", "基层人民法院", "最高人民法院",
    "检察院", "人民检察院",
    "仲裁委", "仲裁委员会",
    "中心", "研究院", "研究所", "研究中心",
    "大学", "学院", "学校",
    "医院", "人民医院",
    "管委会", "管理委员会",
    "协会", "学会", "商会",
    "基金会",
    "局", "厅",
]

# Context triggers: keywords near ORG span that indicate it's a real org
_CONTEXT_TRIGGERS = [
    "被申请人", "申请人", "用人单位", "用工单位",
    "开户行", "开户银行", "收款行",
    "住所地", "注册地", "经营地", "所在地",
    "法定代表人", "负责人", "代表人",
    "甲方", "乙方", "丙方",
    "原告", "被告", "上诉人", "被上诉人",
    "委托人", "受托人",
    "发包人", "承包人", "分包人",
    "买方", "卖方",
    "借款人", "贷款人",
    "出租人", "承租人",
    "转让方", "受让方",
    "质押人", "质权人",
    "担保人", "保证人",
    "监护人",
    "股东", "董事", "监事",
    "公司", "企业", "机构",
]

# Window size for context checking (characters before/after ORG span)
_CONTEXT_WINDOW = 20


@dataclass
class OrgGateResult:
    """Result of ORG secondary validation."""
    passed: bool  # True if ORG should be redacted
    reason: str   # "suffix", "context", "denylist", "allowlist", "no_match"
    matched_suffix: Optional[str] = None
    matched_context: Optional[str] = None
    suggested_action: str = "保留脱敏"  # For audit report


def _has_org_suffix(text: str) -> Tuple[bool, Optional[str]]:
    """Check if text ends with an ORG suffix."""
    for suffix in sorted(_ORG_SUFFIXES, key=len, reverse=True):
        if text.endswith(suffix):
            return True, suffix
    return False, None


def _has_context_trigger(full_text: str, start: int, end: int) -> Tuple[bool, Optional[str]]:
    """Check if context triggers exist near the ORG span."""
    # Extract context window
    ctx_start = max(0, start - _CONTEXT_WINDOW)
    ctx_end = min(len(full_text), end + _CONTEXT_WINDOW)
    context = full_text[ctx_start:ctx_end]

    for trigger in _CONTEXT_TRIGGERS:
        if trigger in context:
            return True, trigger
    return False, None


def validate_org(
    span: Span,
    full_text: str,
    allowlist: Optional[Set[str]] = None,
    denylist: Optional[Set[str]] = None,
) -> OrgGateResult:
    """Validate an ORG span using the precedence pipeline.

    Precedence (highest to lowest):
    1. denylist → redact (forced)
    2. allowlist → no redact
    3. ORG gate (suffix or context) → redact
    4. No match → no redact + audit warning

    Args:
        span: The ORG span to validate.
        full_text: The full document text for context checking.
        allowlist: Set of terms that should NOT be redacted (case-insensitive).
        denylist: Set of terms that MUST be redacted (case-insensitive).

    Returns:
        OrgGateResult with validation decision.
    """
    text = span.text.strip()
    text_lower = text.lower()

    # 1. Check denylist (highest priority)
    if denylist and text_lower in {d.lower() for d in denylist}:
        return OrgGateResult(
            passed=True,
            reason="denylist",
            suggested_action="强制脱敏（denylist）",
        )

    # 2. Check allowlist
    if allowlist and text_lower in {a.lower() for a in allowlist}:
        return OrgGateResult(
            passed=False,
            reason="allowlist",
            suggested_action="建议 allowlist",
        )

    # 3. Check ORG gate (suffix or context)
    has_suffix, matched_suffix = _has_org_suffix(text)
    if has_suffix:
        return OrgGateResult(
            passed=True,
            reason="suffix",
            matched_suffix=matched_suffix,
            suggested_action="保留脱敏",
        )

    has_context, matched_context = _has_context_trigger(full_text, span.start, span.end)
    if has_context:
        return OrgGateResult(
            passed=True,
            reason="context",
            matched_context=matched_context,
            suggested_action="保留脱敏",
        )

    # 4. No match → bare short word, don't redact + warning
    return OrgGateResult(
        passed=False,
        reason="no_match",
        suggested_action="疑似普通词，待复核",
    )


def apply_org_gate(
    spans: List[Span],
    full_text: str,
    allowlist: Optional[Set[str]] = None,
    denylist: Optional[Set[str]] = None,
) -> Tuple[List[Span], List[Span], List[dict]]:
    """Apply ORG gate to all ORG spans.

    Returns:
        - passed_spans: ORG spans that passed the gate (should be redacted)
        - filtered_spans: ORG spans that failed the gate (should NOT be redacted)
        - warnings: Audit warnings for filtered spans
    """
    passed = []
    filtered = []
    warnings = []

    for span in spans:
        if span.entity_type != "ORG":
            passed.append(span)
            continue

        result = validate_org(span, full_text, allowlist, denylist)

        if result.passed:
            # Add metadata about why it passed
            span._gate_reason = result.reason
            span._gate_detail = result.matched_suffix or result.matched_context or ""
            passed.append(span)
        else:
            # Don't redact this span
            span._gate_reason = result.reason
            filtered.append(span)

            # Add audit warning for bare short words
            if result.reason == "no_match":
                warnings.append({
                    "type": "org_bare_short_word",
                    "entity_type": "ORG",
                    "start": span.start,
                    "end": span.end,
                    "text": span.text,
                    "message": f"疑似普通词，待复核: '{span.text}'",
                    "suggested_action": result.suggested_action,
                })
            elif result.reason == "allowlist":
                warnings.append({
                    "type": "org_allowlisted",
                    "entity_type": "ORG",
                    "start": span.start,
                    "end": span.end,
                    "text": span.text,
                    "message": f"命中 allowlist，不脱敏: '{span.text}'",
                    "suggested_action": result.suggested_action,
                })

    return passed, filtered, warnings
