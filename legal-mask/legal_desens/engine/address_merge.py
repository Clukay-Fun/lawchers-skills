"""Address merge: combine adjacent LOC spans + address suffixes, stop at ORG boundary."""

from __future__ import annotations

import re
from typing import List

from .span import Span

# Address suffix tokens that can be part of a merged address
_ADDRESS_SUFFIX_PATTERN = re.compile(
    r"(?:路|街|道|巷|弄|号|楼|层|室|栋|座|区|村|镇|乡|县|市|省|旗|弄|苑|花园|新村|小区|大厦|广场|公寓|花园|别墅|号楼|单元|层|室|号院|院|胡同)"
)

# ORG boundary suffixes — if a LOC-like token ends with these, it's an org, not address
_ORG_SUFFIXES = (
    "公司", "事务所", "法院", "局", "院", "委", "办", "处", "所", "中心",
    "集团", "银行", "企业", "工厂", "厂", "店", "馆", "学校", "大学",
    "医院", "协会", "基金会", "研究院", "研究所",
)


def _is_org_boundary(text_between: str) -> bool:
    """Check if text between two spans looks like an ORG boundary."""
    stripped = text_between.strip()
    for suffix in _ORG_SUFFIXES:
        if suffix in stripped:
            return True
    return False


def merge_addresses(
    spans: List[Span],
    original_text: str,
) -> List[Span]:
    """Merge adjacent LOC fragments + address suffixes into single ADDRESS spans.

    Rules:
    - Adjacent LOC spans separated by address-suffix text → merge into one ADDRESS
    - Stop merging when ORG boundary detected (公司/事务所/法院 etc.)
    - Non-LOC, non-address-suffix gaps → stop merge
    - Output spans have entity_type="ADDRESS"
    """
    if not spans:
        return spans

    # Sort by start position
    sorted_spans = sorted(spans, key=lambda s: s.start)

    # Find LOC spans that could be merged
    loc_indices = [i for i, s in enumerate(sorted_spans) if s.entity_type == "LOC"]

    if not loc_indices:
        return spans

    # Group consecutive LOC spans that can be merged
    merge_groups: List[List[int]] = []  # groups of indices into sorted_spans
    current_group: List[int] = [loc_indices[0]]

    for i in range(1, len(loc_indices)):
        prev_idx = loc_indices[i - 1]
        curr_idx = loc_indices[i]
        prev_span = sorted_spans[prev_idx]
        curr_span = sorted_spans[curr_idx]

        # Check gap between prev end and curr start
        gap_text = original_text[prev_span.end:curr_span.start]

        # Check if gap is address-like suffix or empty/whitespace
        gap_stripped = gap_text.strip()
        if not gap_stripped:
            # Directly adjacent — merge
            current_group.append(curr_idx)
        elif _ADDRESS_SUFFIX_PATTERN.fullmatch(gap_stripped):
            # Address suffix in gap — merge
            current_group.append(curr_idx)
        elif _is_org_boundary(gap_text):
            # ORG boundary — stop current group, start new
            if len(current_group) > 0:
                merge_groups.append(current_group)
            current_group = [curr_idx]
        else:
            # Non-address gap — stop current group
            if len(current_group) > 0:
                merge_groups.append(current_group)
            current_group = [curr_idx]

    if len(current_group) > 0:
        merge_groups.append(current_group)

    # Only merge groups with 2+ LOC spans
    groups_to_merge = [g for g in merge_groups if len(g) >= 2]

    if not groups_to_merge:
        return spans

    # Build merged spans
    merged_spans: List[Span] = []
    skip_indices = set()

    for group in groups_to_merge:
        first_idx = group[0]
        last_idx = group[-1]
        first_span = sorted_spans[first_idx]
        last_span = sorted_spans[last_idx]

        # Include address suffix text in the merged span
        merge_start = first_span.start
        merge_end = last_span.end

        # Extend to include trailing address suffix if present
        tail_text = original_text[merge_end:merge_end + 10]
        suffix_match = _ADDRESS_SUFFIX_PATTERN.match(tail_text)
        if suffix_match:
            merge_end += suffix_match.end()

        merged_span = Span(
            entity_type="ADDRESS",
            start=merge_start,
            end=merge_end,
            text=original_text[merge_start:merge_end],
            engine=first_span.engine,
            rule_id=first_span.rule_id,
            priority=first_span.priority,
            discovery_order=first_span.discovery_order,
        )
        merged_spans.append(merged_span)

        for idx in group:
            skip_indices.add(idx)

    # Build result: non-LOC spans + merged ADDRESS spans
    result: List[Span] = []
    for i, span in enumerate(sorted_spans):
        if i in skip_indices:
            continue
        result.append(span)

    result.extend(merged_spans)
    result.sort(key=lambda s: s.start)

    return result
