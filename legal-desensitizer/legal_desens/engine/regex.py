"""Regex-based desensitization engine."""

from __future__ import annotations

from typing import List

from ..rules import Rule
from .span import Span


def scan_regex(text: str, rules: List[Rule]) -> List[Span]:
    """Run all regex rules against text and return spans."""
    spans: List[Span] = []
    order = 0
    for rule in sorted(rules, key=lambda r: (-r.priority, r.id)):
        for m in rule.compiled.finditer(text):
            spans.append(Span(
                entity_type=rule.entity_type,
                start=m.start(),
                end=m.end(),
                text=m.group(),
                engine="regex",
                rule_id=rule.id,
                priority=rule.priority,
                discovery_order=order,
            ))
            order += 1
    return spans
