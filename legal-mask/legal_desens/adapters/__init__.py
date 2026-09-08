"""Document format adapters for redact / restore / audit."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ExtractedText:
    """A text segment with positional metadata for locator construction."""
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditWarning:
    """A warning emitted during redact or audit."""
    type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


class DocumentAdapter(ABC):
    """Minimal interface for document format adapters."""

    @abstractmethod
    def extract_text(self, path: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Extract plain text and segment metadata from document.

        Returns (full_text, segments) where each segment has positional info
        needed to build locators.
        """
        ...

    @abstractmethod
    def redact(
        self,
        source_path: str,
        redacted_path: str,
        redact_fn,
        rules,
        mode: str = "regex-only",
        level: str = "strict",
        model_dir: Optional[str] = None,
    ) -> Tuple[dict, dict]:
        """Redact document content. Returns (map_data, audit_data).

        redact_fn(text, rules, source_sha256, mode, level, model_dir)
        is called per text segment; returns (redacted_text, segment_map, segment_audit).
        """
        ...

    @abstractmethod
    def restore(self, redacted_path: str, restored_path: str, map_data: dict) -> None:
        """Restore redacted document using locator-based reversal."""
        ...

    @abstractmethod
    def audit(self, path: str, map_data: dict, rules) -> dict:
        """Audit a redacted document for residual sensitive data."""
        ...
