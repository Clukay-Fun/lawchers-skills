"""Evaluation harness for NER models (012 stage).

Computes per-entity recall/precision/F1, boundary errors,
false negative list, and gate decisions.

No model loading. Takes gold + predicted Annotations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .schema import Annotation, Entity


@dataclass
class EvalResult:
    """Metrics for a single entity type."""
    entity_type: str
    true_positives: int
    false_positives: int
    false_negatives: int
    boundary_errors: int
    false_negative_details: List[dict] = field(default_factory=list)

    @property
    def precision(self) -> float:
        if self.true_positives + self.false_positives == 0:
            return 0.0
        return self.true_positives / (self.true_positives + self.false_positives)

    @property
    def recall(self) -> float:
        if self.true_positives + self.false_negatives == 0:
            return 0.0
        return self.true_positives / (self.true_positives + self.false_negatives)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)


@dataclass
class EvalReport:
    """Full evaluation report across all entity types."""
    per_type: Dict[str, EvalResult]
    boundary_errors: List[dict] = field(default_factory=list)

    @property
    def overall_precision(self) -> float:
        tp = sum(r.true_positives for r in self.per_type.values())
        fp = sum(r.false_positives for r in self.per_type.values())
        if tp + fp == 0:
            return 0.0
        return tp / (tp + fp)

    @property
    def overall_recall(self) -> float:
        tp = sum(r.true_positives for r in self.per_type.values())
        fn = sum(r.false_negatives for r in self.per_type.values())
        if tp + fn == 0:
            return 0.0
        return tp / (tp + fn)

    @property
    def overall_f1(self) -> float:
        p, r = self.overall_precision, self.overall_recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    @property
    def total_boundary_errors(self) -> int:
        return sum(r.boundary_errors for r in self.per_type.values())

    @property
    def total_false_negatives(self) -> int:
        return sum(r.false_negatives for r in self.per_type.values())

    @property
    def all_false_negative_details(self) -> List[dict]:
        details = []
        for r in self.per_type.values():
            details.extend(r.false_negative_details)
        return details

    def summary(self) -> dict:
        return {
            "overall": {
                "precision": round(self.overall_precision, 4),
                "recall": round(self.overall_recall, 4),
                "f1": round(self.overall_f1, 4),
                "boundary_errors": self.total_boundary_errors,
                "false_negatives": self.total_false_negatives,
            },
            "per_type": {
                etype: {
                    "precision": round(r.precision, 4),
                    "recall": round(r.recall, 4),
                    "f1": round(r.f1, 4),
                    "tp": r.true_positives,
                    "fp": r.false_positives,
                    "fn": r.false_negatives,
                    "boundary_errors": r.boundary_errors,
                }
                for etype, r in sorted(self.per_type.items())
            },
            "false_negative_details": self.all_false_negative_details,
            "boundary_error_details": self.boundary_errors,
        }


@dataclass
class GateResult:
    """Result of a gate check."""
    name: str
    passed: bool
    metric: str
    value: float
    threshold: float
    detail: str = ""


def _match_entity(
    gold: Entity,
    pred: Entity,
) -> str:
    """Classify how a predicted entity matches a gold entity.

    Returns: 'exact', 'boundary_error', or 'mismatch'.
    """
    if gold.entity_type != pred.entity_type:
        return "mismatch"
    if gold.start == pred.start and gold.end == pred.end:
        return "exact"
    # Partial overlap = boundary error
    if gold.start < pred.end and pred.start < gold.end:
        return "boundary_error"
    return "mismatch"


def compare_annotations(
    gold: Annotation,
    pred: Annotation,
) -> EvalReport:
    """Compare gold and predicted annotations.

    Matching strategy:
    - Exact match (same type, same span): TP
    - Partial overlap (same type, different span): boundary error (counted as FP+FN)
    - Predicted entity with no gold match: FP
    - Gold entity with no predicted match: FN
    """
    per_type: Dict[str, EvalResult] = {}
    boundary_errors: List[dict] = []

    # Track which gold/pred entities have been matched
    gold_matched: Set[int] = set()
    pred_matched: Set[int] = set()

    # Index gold and pred by entity type
    gold_by_type: Dict[str, List[Tuple[int, Entity]]] = {}
    for i, ent in enumerate(gold.entities):
        gold_by_type.setdefault(ent.entity_type, []).append((i, ent))

    pred_by_type: Dict[str, List[Tuple[int, Entity]]] = {}
    for i, ent in enumerate(pred.entities):
        pred_by_type.setdefault(ent.entity_type, []).append((i, ent))

    all_types = set(gold_by_type.keys()) | set(pred_by_type.keys())

    for etype in sorted(all_types):
        gold_list = gold_by_type.get(etype, [])
        pred_list = pred_by_type.get(etype, [])

        tp = 0
        fp = 0
        fn = 0
        boundary_err = 0
        fn_details: List[dict] = []

        # First pass: exact matches
        for gi, g_ent in gold_list:
            for pi, p_ent in pred_list:
                if gi in gold_matched or pi in pred_matched:
                    continue
                if g_ent.start == p_ent.start and g_ent.end == p_ent.end:
                    tp += 1
                    gold_matched.add(gi)
                    pred_matched.add(pi)
                    break

        # Second pass: boundary errors (partial overlap, same type)
        for gi, g_ent in gold_list:
            if gi in gold_matched:
                continue
            for pi, p_ent in pred_list:
                if pi in pred_matched:
                    continue
                if g_ent.start < p_ent.end and p_ent.start < g_ent.end:
                    boundary_err += 1
                    gold_matched.add(gi)
                    pred_matched.add(pi)
                    boundary_errors.append({
                        "entity_type": etype,
                        "gold": {"start": g_ent.start, "end": g_ent.end, "text": g_ent.text},
                        "pred": {"start": p_ent.start, "end": p_ent.end, "text": p_ent.text},
                    })
                    # Count as both FP and FN
                    fp += 1
                    fn += 1
                    fn_details.append({
                        "entity_type": etype,
                        "start": g_ent.start,
                        "end": g_ent.end,
                        "text": g_ent.text,
                        "reason": "boundary_error",
                    })
                    break

        # Remaining unmatched gold = FN
        for gi, g_ent in gold_list:
            if gi not in gold_matched:
                fn += 1
                fn_details.append({
                    "entity_type": etype,
                    "start": g_ent.start,
                    "end": g_ent.end,
                    "text": g_ent.text,
                    "reason": "missed",
                })

        # Remaining unmatched pred = FP
        for pi, p_ent in pred_list:
            if pi not in pred_matched:
                fp += 1

        per_type[etype] = EvalResult(
            entity_type=etype,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            boundary_errors=boundary_err,
            false_negative_details=fn_details,
        )

    return EvalReport(per_type=per_type, boundary_errors=boundary_errors)


def recall_gate(
    report: EvalReport,
    threshold: float = 0.90,
    entity_types: Optional[List[str]] = None,
) -> GateResult:
    """Check if recall meets the threshold.

    If entity_types is specified, only check those types.
    Returns FAIL if any checked type falls below threshold.
    """
    types_to_check = entity_types or list(report.per_type.keys())

    worst_recall = 1.0
    worst_type = ""
    for etype in types_to_check:
        if etype not in report.per_type:
            continue
        r = report.per_type[etype]
        if r.recall < worst_recall:
            worst_recall = r.recall
            worst_type = etype

    passed = worst_recall >= threshold
    detail = ""
    if not passed:
        detail = f"FAIL: {worst_type} recall={worst_recall:.4f} < {threshold}"
    else:
        detail = f"PASS: all types recall >= {threshold}"

    return GateResult(
        name="recall_gate",
        passed=passed,
        metric="recall",
        value=worst_recall,
        threshold=threshold,
        detail=detail,
    )


def int8_gate(
    report_fp32: EvalReport,
    report_int8: EvalReport,
    max_drop: float = 0.03,
    entity_types: Optional[List[str]] = None,
) -> GateResult:
    """Check if INT8 quantization recall drop is within tolerance.

    Returns FAIL if any type's recall drops more than max_drop.
    """
    types_to_check = entity_types or list(report_fp32.per_type.keys())

    worst_drop = 0.0
    worst_type = ""
    details = []

    for etype in types_to_check:
        fp32_r = report_fp32.per_type.get(etype)
        int8_r = report_int8.per_type.get(etype)
        if fp32_r is None or int8_r is None:
            continue
        drop = fp32_r.recall - int8_r.recall
        details.append(f"{etype}: fp32={fp32_r.recall:.4f} int8={int8_r.recall:.4f} drop={drop:.4f}")
        if drop > worst_drop:
            worst_drop = drop
            worst_type = etype

    passed = worst_drop <= max_drop
    detail_parts = ["; ".join(details)]
    if not passed:
        detail_parts.append(f"FAIL: {worst_type} drop={worst_drop:.4f} > {max_drop}")
    else:
        detail_parts.append(f"PASS: all drops <= {max_drop}")

    return GateResult(
        name="int8_gate",
        passed=passed,
        metric="recall_drop",
        value=worst_drop,
        threshold=max_drop,
        detail=" | ".join(detail_parts),
    )
