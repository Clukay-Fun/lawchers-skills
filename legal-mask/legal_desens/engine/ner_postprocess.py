"""NER post-processing: compound surname merge, ORG gate, address merge, etc."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .span import Span

# Chinese compound surnames (common ones)
COMPOUND_SURNAMES = {
    "欧阳", "司马", "上官", "诸葛", "公孙", "皇甫", "令狐", "慕容", "宇文",
    "东方", "西门", "南宫", "独孤", "长孙", "百里", "鲜于", "轩辕", "端木",
}

# ORG suffixes (must end with one of these to be considered real ORG)
ORG_SUFFIXES = [
    "公司", "有限公司", "股份有限公司", "集团", "集团有限公司",
    "律师事务所", "事务所", "律所",
    "银行", "信用社",
    "法院", "中级人民法院", "基层人民法院",
    "检察院", "人民检察院",
    "仲裁委", "仲裁委员会",
    "中心", "研究院", "研究院有限公司",
    "大学", "学院", "学校",
    "医院", "卫生院",
    "管委会", "管理委员会",
    "局", "部", "厅", "处", "所", "站",
]

# Context triggers that indicate ORG
ORG_CONTEXT_TRIGGERS = [
    "被申请人", "申请人", "用人单位", "用工单位",
    "开户行", "住所地", "注册地", "经营地",
    "法定代表人", "负责人", "联系人",
    "甲方", "乙方", "丙方", "委托方", "受托方",
]

# Address suffixes for merging
ADDRESS_SUFFIXES = [
    "路", "街", "道", "巷", "弄", "号", "室", "栋", "楼", "层",
    "区", "镇", "乡", "村", "组", "弄", "园", "苑", "城", "村",
    "大厦", "大楼", "广场", "中心", "小区", "公寓", "花园",
]

# English detection pattern
ENGLISH_PATTERN = re.compile(r'[a-zA-Z]{3,}')


def is_chinese_char(c: str) -> bool:
    """Check if character is Chinese."""
    cp = ord(c)
    return (
        (0x4E00 <= cp <= 0x9FFF) or
        (0x3400 <= cp <= 0x4DBF) or
        (0x20000 <= cp <= 0x2A6DF) or
        (0x2A700 <= cp <= 0x2B73F) or
        (0x2B740 <= cp <= 0x2B81F) or
        (0x2B820 <= cp <= 0x2CEAF) or
        (0xF900 <= cp <= 0xFAFF) or
        (0x2F800 <= cp <= 0x2FA1F)
    )


def merge_compound_surnames(
    spans: List[Span],
    text: str,
) -> List[Span]:
    """Merge compound surname + first name into single PERSON span.

    If '欧阳' is detected as a separate PER span adjacent to another PER span,
    merge them.
    """
    if not spans:
        return spans

    result = []
    i = 0
    while i < len(spans):
        current = spans[i]

        # Check if this is a compound surname case
        if current.entity_type == "PER" and i + 1 < len(spans):
            next_span = spans[i + 1]
            if next_span.entity_type == "PER":
                # Check if they are adjacent and form a compound surname
                gap = text[current.end:next_span.start]
                if not gap or gap.isspace():
                    combined = text[current.start:next_span.end]
                    # Check if starts with compound surname
                    for surname in COMPOUND_SURNAMES:
                        if combined.startswith(surname):
                            # Merge
                            current = Span(
                                entity_type="PER",
                                start=current.start,
                                end=next_span.end,
                                text=combined,
                                engine=current.engine,
                                rule_id=current.rule_id,
                                priority=current.priority,
                            )
                            i += 1
                            break

        result.append(current)
        i += 1

    return result


def filter_by_confidence(
    spans: List[Span],
    min_confidence: float = 0.5,
    confidence_field: str = "confidence",
) -> Tuple[List[Span], List[dict]]:
    """Filter spans by confidence threshold."""
    result = []
    warnings = []
    for span in spans:
        conf = getattr(span, confidence_field, None)
        if conf is not None and conf < min_confidence:
            warnings.append({
                "type": "low_confidence",
                "entity_type": span.entity_type,
                "text": span.text,
                "confidence": conf,
                "detail": f"Entity '{span.text}' dropped: confidence {conf:.2f} < {min_confidence}",
            })
        else:
            result.append(span)
    return result, warnings


def validate_org_suffix(
    spans: List[Span],
    text: str,
) -> Tuple[List[Span], List[dict]]:
    """Validate ORG spans: must end with organization suffix or have context trigger."""
    result = []
    warnings = []

    for span in spans:
        if span.entity_type != "ORG":
            result.append(span)
            continue

        # Get text from span or source
        span_text = span.text if span.text else text[span.start:span.end]

        # Check suffix
        has_suffix = any(span_text.endswith(suffix) for suffix in ORG_SUFFIXES)

        # Check context triggers (look in surrounding text)
        has_context = False
        context_start = max(0, span.start - 20)
        context_end = min(len(text), span.end + 20)
        context = text[context_start:context_end]
        for trigger in ORG_CONTEXT_TRIGGERS:
            if trigger in context:
                has_context = True
                break

        if has_suffix or has_context:
            result.append(span)
        else:
            warnings.append({
                "type": "org_no_suffix",
                "text": span_text,
                "detail": f"ORG '{span_text}' has no suffix or context trigger, may be false positive",
            })

    return result, warnings


def expand_entity_mentions(
    spans: List[Span],
    text: str,
) -> List[Span]:
    """After first reliable identification, expand same-name entities throughout text."""
    if not spans:
        return spans

    # Find all unique entity texts per type
    entity_texts = {}  # type -> set of texts
    for span in spans:
        if span.entity_type not in entity_texts:
            entity_texts[span.entity_type] = set()
        entity_texts[span.entity_type].add(span.text)

    # Search for additional mentions
    result = list(spans)
    for etype, texts in entity_texts.items():
        for etext in texts:
            # Find all occurrences not already covered
            start = 0
            while True:
                pos = text.find(etext, start)
                if pos == -1:
                    break
                end = pos + len(etext)

                # Check if already covered
                covered = False
                for span in result:
                    if span.start <= pos and span.end >= end:
                        covered = True
                        break

                if not covered:
                    result.append(Span(
                        entity_type=etype,
                        start=pos,
                        end=end,
                        text=etext,
                        engine="ner_expanded",
                        rule_id=None,
                        priority=45,  # Lower priority than original NER
                    ))

                start = pos + 1

    # Sort by position
    result.sort(key=lambda s: s.start)
    return result


def merge_address_fragments(
    spans: List[Span],
    text: str,
) -> List[Span]:
    """Merge adjacent LOC fragments into single ADDRESS span."""
    if not spans:
        return spans

    result = []
    current_group: List[Span] = []

    def flush_group():
        if not current_group:
            return
        if len(current_group) == 1:
            result.append(current_group[0])
        else:
            # Merge
            start = current_group[0].start
            end = current_group[-1].end
            merged_text = text[start:end]
            result.append(Span(
                entity_type="ADDRESS",
                start=start,
                end=end,
                text=merged_text,
                engine=current_group[0].engine,
                rule_id=current_group[0].rule_id,
                priority=current_group[0].priority,
            ))
        current_group.clear()

    for span in spans:
        if span.entity_type in ("LOC", "ADDRESS"):
            # Check if should merge with previous
            if current_group:
                last = current_group[-1]
                gap = text[last.end:span.start]
                # Merge if gap is short and contains address-like characters
                if len(gap) <= 2 and all(c in " ,，、·" or is_chinese_char(c) for c in gap):
                    current_group.append(span)
                    continue

            flush_group()
            current_group.append(span)
        else:
            flush_group()
            result.append(span)

    flush_group()
    return result


def filter_english_paragraphs(
    text: str,
) -> Tuple[str, bool]:
    """Check if text contains significant English content.

    Returns (text, has_english).
    """
    english_matches = ENGLISH_PATTERN.findall(text)
    if len(english_matches) > 5 or any(len(m) > 20 for m in english_matches):
        return text, True
    return text, False


def postprocess_ner_spans(
    spans: List[Span],
    text: str,
    confidence_threshold: float = 0.5,
    validate_org: bool = True,
    merge_address_parts: bool = True,
) -> Tuple[List[Span], List[dict]]:
    """Full NER post-processing pipeline.

    Returns (processed_spans, all_warnings).
    """
    all_warnings = []

    # 1. Filter by confidence (if available)
    spans, warnings = filter_by_confidence(spans, confidence_threshold)
    all_warnings.extend(warnings)

    # 2. Merge compound surnames
    spans = merge_compound_surnames(spans, text)

    # 3. Validate ORG suffixes
    if validate_org:
        spans, warnings = validate_org_suffix(spans, text)
        all_warnings.extend(warnings)

    # 4. Merge address fragments
    if merge_address_parts:
        spans = merge_address_fragments(spans, text)

    # 5. Expand entity mentions
    spans = expand_entity_mentions(spans, text)

    return spans, all_warnings
