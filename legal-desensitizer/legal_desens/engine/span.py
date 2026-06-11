"""Unified span representation for all engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Span:
    entity_type: str
    start: int
    end: int
    text: str
    engine: str  # "regex" | "ner"
    rule_id: Optional[str] = None
    priority: int = 100
    discovery_order: int = 0

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        return self.start <= other.start and self.end >= other.end
