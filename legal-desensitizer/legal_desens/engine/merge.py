"""Deterministic span merge with overlap resolution."""

from __future__ import annotations

from typing import List, Tuple

from .span import Span

ENGINE_ORDER = {"regex": 0, "ner": 1}


def merge_spans(spans: List[Span]) -> Tuple[List[Span], List[Span]]:
    """Merge and resolve overlapping spans deterministically.

    Returns (kept, discarded).
    Strategy (from plan):
    1. Long span first
    2. Same length → higher priority wins
    3. Same priority → engine order: regex > ner
    4. Still tied → discovery_order (stable)
    """
    if not spans:
        return [], []

    def sort_key(s: Span):
        return (-s.length, -s.priority, ENGINE_ORDER.get(s.engine, 99), s.discovery_order)

    sorted_spans = sorted(spans, key=sort_key)

    kept: List[Span] = []
    discarded: List[Span] = []

    for span in sorted_spans:
        conflict = False
        for k in kept:
            if span.overlaps(k):
                conflict = True
                break
        if conflict:
            discarded.append(span)
        else:
            kept.append(span)

    kept.sort(key=lambda s: s.start)
    return kept, discarded
