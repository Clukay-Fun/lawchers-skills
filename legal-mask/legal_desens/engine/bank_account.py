"""Context-aware BANK_ACCOUNT detection: trigger words + digit sequences."""

from __future__ import annotations

import re
from typing import List, Tuple

from .span import Span

# Trigger words that indicate a nearby digit sequence is a bank account
_BANK_CONTEXT_PATTERN = re.compile(
    r"(?:账号|银行卡号|收款账户|开户行|银行|尾号|卡号|账户|汇款账号|收款账号)"
)

# Bare long digit sequence (12-19 digits) — potential bank account
_BARE_LONG_DIGITS = re.compile(r"(?<!\d)\d{12,19}(?!\d)")

# Context window: how far to look for trigger words around a digit sequence
_CONTEXT_WINDOW = 30


def detect_bank_accounts(
    text: str,
    existing_spans: List[Span],
) -> Tuple[List[Span], List[dict]]:
    """Detect bank account numbers using context-aware heuristics.

    Returns (new_spans, warnings):
    - new_spans: BANK_ACCOUNT spans where context confirmed account nature
    - warnings: audit warnings for bare long digits without context
    """
    new_spans: List[Span] = []
    warnings: List[dict] = []

    # Regions already covered by existing spans (e.g., ID_CARD, PHONE)
    covered_regions = [(s.start, s.end) for s in existing_spans]

    def is_covered(start: int, end: int) -> bool:
        for cs, ce in covered_regions:
            if start < ce and end > cs:
                return True
        return False

    order = max((s.discovery_order for s in existing_spans), default=0) + 1

    for match in _BARE_LONG_DIGITS.finditer(text):
        start, end = match.start(), match.end()
        digit_seq = match.group()

        # Skip if already covered by a higher-priority span
        if is_covered(start, end):
            continue

        # Check for trigger words within context window
        ctx_start = max(0, start - _CONTEXT_WINDOW)
        ctx_end = min(len(text), end + _CONTEXT_WINDOW)
        context = text[ctx_start:ctx_end]

        if _BANK_CONTEXT_PATTERN.search(context):
            # Context confirms this is likely a bank account
            new_spans.append(Span(
                entity_type="BANK_ACCOUNT",
                start=start,
                end=end,
                text=digit_seq,
                engine="regex",
                rule_id="bank_account_context",
                priority=110,  # Above MONEY (100) — account takes precedence
                discovery_order=order,
            ))
            order += 1
        else:
            # Bare long digit without context → warning, not auto-redact
            warnings.append({
                "type": "bare_long_digits_no_context",
                "start": start,
                "end": end,
                "text_preview": digit_seq[:20],
                "message": (
                    f"Long digit sequence ({len(digit_seq)} digits) found without "
                    f"bank-account context keywords nearby. Not auto-redacted. "
                    f"Review manually if this is a bank account number."
                ),
            })

    return new_spans, warnings
