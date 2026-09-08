"""Shared regex scanning helper for document adapters."""

from __future__ import annotations

from typing import List

from ..engine.regex import scan_regex
from ..engine.span import Span
from ..rules import Rule


def scan_regex_for_audit(text: str, rules: List[Rule]) -> List[Span]:
    """Scan text for residual sensitive patterns. Used by adapter audit methods."""
    return scan_regex(text, rules)
