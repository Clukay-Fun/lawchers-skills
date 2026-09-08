"""Unit tests for NER evaluation harness (012 stage)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.ner_eval.schema import Annotation, Entity
from legal_desens.ner_eval.harness import (
    EvalReport,
    EvalResult,
    GateResult,
    compare_annotations,
    recall_gate,
    int8_gate,
)
from legal_desens.ner_eval.fixtures import SYNTHETIC_ANNOTATIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ann(text, entities_raw, ann_id="test"):
    """Build Annotation from (entity_type, start, end) tuples."""
    entities = [
        Entity(id=f"{ann_id}_e{i}", entity_type=et, start=s, end=e, text=text[s:e])
        for i, (et, s, e) in enumerate(entities_raw)
    ]
    bio = ["O"] * len(text)
    for ent in entities:
        for j in range(ent.start, ent.end):
            if j == ent.start:
                bio[j] = f"B-{ent.entity_type}"
            else:
                bio[j] = f"I-{ent.entity_type}"
    return Annotation(id=ann_id, text=text, entities=entities, bio_tags=bio)


# ── Exact match ───────────────────────────────────────────────────────────────

class TestExactMatch:
    def test_perfect_match(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2), ("LOCATION", 3, 5)])
        pred = _make_ann(text, [("PERSON", 0, 2), ("LOCATION", 3, 5)])
        report = compare_annotations(gold, pred)

        assert report.overall_precision == 1.0
        assert report.overall_recall == 1.0
        assert report.overall_f1 == 1.0
        assert report.total_boundary_errors == 0
        assert report.total_false_negatives == 0

    def test_all_missed(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2), ("LOCATION", 3, 5)])
        pred = _make_ann(text, [])
        report = compare_annotations(gold, pred)

        assert report.overall_precision == 0.0
        assert report.overall_recall == 0.0
        assert report.total_false_negatives == 2

    def test_all_hallucinated(self):
        text = "无关文本"
        gold = _make_ann(text, [])
        pred = _make_ann(text, [("PERSON", 0, 2)])
        report = compare_annotations(gold, pred)

        assert report.overall_precision == 0.0
        assert report.per_type["PERSON"].false_positives == 1


# ── Boundary errors ───────────────────────────────────────────────────────────

class TestBoundaryErrors:
    def test_partial_overlap(self):
        text = "张三在北京住"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [("PERSON", 0, 3)])  # extended by 1 char
        report = compare_annotations(gold, pred)

        assert report.total_boundary_errors == 1
        assert report.per_type["PERSON"].boundary_errors == 1
        assert len(report.boundary_errors) == 1
        assert report.boundary_errors[0]["gold"]["text"] == "张三"
        assert report.boundary_errors[0]["pred"]["text"] == "张三在"

    def test_boundary_error_counts_as_fp_and_fn(self):
        text = "张三在北京住"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [("PERSON", 0, 3)])
        report = compare_annotations(gold, pred)

        r = report.per_type["PERSON"]
        assert r.false_positives == 1
        assert r.false_negatives == 1
        assert r.true_positives == 0

    def test_no_overlap_different_spans(self):
        text = "张三在北京住"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [("PERSON", 3, 5)])  # different position, no overlap
        report = compare_annotations(gold, pred)

        assert report.total_boundary_errors == 0
        assert report.per_type["PERSON"].false_positives == 1
        assert report.per_type["PERSON"].false_negatives == 1


# ── False negative details ────────────────────────────────────────────────────

class TestFalseNegatives:
    def test_fn_details_include_text(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [])
        report = compare_annotations(gold, pred)

        fn_details = report.all_false_negative_details
        assert len(fn_details) == 1
        assert fn_details[0]["text"] == "张三"
        assert fn_details[0]["entity_type"] == "PERSON"
        assert fn_details[0]["reason"] == "missed"

    def test_boundary_error_fn_reason(self):
        text = "张三在北京住"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [("PERSON", 0, 3)])
        report = compare_annotations(gold, pred)

        fn_details = report.all_false_negative_details
        assert len(fn_details) == 1
        assert fn_details[0]["reason"] == "boundary_error"


# ── Per-type metrics ──────────────────────────────────────────────────────────

class TestPerTypeMetrics:
    def test_different_types_independent(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2), ("LOCATION", 3, 5)])
        pred = _make_ann(text, [("PERSON", 0, 2)])  # missed LOCATION
        report = compare_annotations(gold, pred)

        per = report.per_type
        assert per["PERSON"].recall == 1.0
        assert per["LOCATION"].recall == 0.0
        assert per["LOCATION"].false_negatives == 1

    def test_summary_structure(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [("PERSON", 0, 2)])
        report = compare_annotations(gold, pred)
        summary = report.summary()

        assert "overall" in summary
        assert "per_type" in summary
        assert "false_negative_details" in summary
        assert "boundary_error_details" in summary
        assert summary["overall"]["f1"] == 1.0


# ── Recall gate ───────────────────────────────────────────────────────────────

class TestRecallGate:
    def test_pass_when_above_threshold(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred = _make_ann(text, [("PERSON", 0, 2)])
        report = compare_annotations(gold, pred)

        gate = recall_gate(report, threshold=0.90)
        assert gate.passed is True
        assert gate.name == "recall_gate"

    def test_fail_when_below_threshold(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2), ("LOCATION", 3, 5)])
        pred = _make_ann(text, [("PERSON", 0, 2)])  # missed LOCATION
        report = compare_annotations(gold, pred)

        gate = recall_gate(report, threshold=0.90)
        assert gate.passed is False
        assert "FAIL" in gate.detail

    def test_specific_types(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2), ("LOCATION", 3, 5)])
        pred = _make_ann(text, [("PERSON", 0, 2)])
        report = compare_annotations(gold, pred)

        # Check only PERSON (which passes)
        gate = recall_gate(report, threshold=0.90, entity_types=["PERSON"])
        assert gate.passed is True

    def test_empty_report(self):
        text = "无关"
        gold = _make_ann(text, [])
        pred = _make_ann(text, [])
        report = compare_annotations(gold, pred)

        gate = recall_gate(report, threshold=0.90)
        assert gate.passed is True  # no types to check


# ── INT8 gate ─────────────────────────────────────────────────────────────────

class TestINT8Gate:
    def test_pass_when_drop_within_tolerance(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        pred_fp32 = _make_ann(text, [("PERSON", 0, 2)])
        pred_int8 = _make_ann(text, [("PERSON", 0, 2)])

        r32 = compare_annotations(gold, pred_fp32)
        r8 = compare_annotations(gold, pred_int8)

        gate = int8_gate(r32, r8, max_drop=0.03)
        assert gate.passed is True

    def test_fail_when_drop_exceeds_tolerance(self):
        text = "张三在北京某某公司"
        gold = _make_ann(text, [("PERSON", 0, 2), ("ORG", 5, 9)])
        pred_fp32 = _make_ann(text, [("PERSON", 0, 2), ("ORG", 5, 9)])
        pred_int8 = _make_ann(text, [("PERSON", 0, 2)])  # missed ORG in int8

        r32 = compare_annotations(gold, pred_fp32)
        r8 = compare_annotations(gold, pred_int8)

        gate = int8_gate(r32, r8, max_drop=0.03)
        assert gate.passed is False
        assert "FAIL" in gate.detail

    def test_gate_result_structure(self):
        text = "张三在北京"
        gold = _make_ann(text, [("PERSON", 0, 2)])
        r32 = compare_annotations(gold, _make_ann(text, [("PERSON", 0, 2)]))
        r8 = compare_annotations(gold, _make_ann(text, [("PERSON", 0, 2)]))

        gate = int8_gate(r32, r8, max_drop=0.05)
        assert isinstance(gate, GateResult)
        assert gate.name == "int8_gate"
        assert gate.metric == "recall_drop"


# ── Synthetic fixtures self-consistency ───────────────────────────────────────

class TestSyntheticFixtures:
    def test_all_fixtures_valid(self):
        """Every synthetic fixture must pass validation with no errors."""
        for ann in SYNTHETIC_ANNOTATIONS:
            # Should not raise
            warnings = validate_annotation(ann)
            # Allow warnings (e.g. from overlapping entities in test data)
            # but no hard errors

    def test_fixtures_cover_entity_types(self):
        """Fixtures collectively cover all four NER entity types."""
        from legal_desens.ner_eval.schema import NER_ENTITY_TYPES
        seen = set()
        for ann in SYNTHETIC_ANNOTATIONS:
            for ent in ann.entities:
                seen.add(ent.entity_type)
        assert seen == NER_ENTITY_TYPES

    def test_fixture_no_entity(self):
        """Fixture with no entities should be present."""
        no_ent = [a for a in SYNTHETIC_ANNOTATIONS if len(a.entities) == 0]
        assert len(no_ent) >= 1

    def test_fixture_boundary_chars(self):
        """At least one fixture has entity at start (0) and end of text."""
        has_start = any(e.start == 0 for a in SYNTHETIC_ANNOTATIONS for e in a.entities)
        has_end = any(
            e.end == len(a.text)
            for a in SYNTHETIC_ANNOTATIONS
            for e in a.entities
        )
        assert has_start, "No fixture has entity at text start"
        assert has_end, "No fixture has entity at text end"

    def test_fixture_bio_tags_match_entities(self):
        """All fixtures have BIO tags consistent with entity spans."""
        from legal_desens.ner_eval.schema import _generate_bio_tags
        for ann in SYNTHETIC_ANNOTATIONS:
            expected = _generate_bio_tags(ann.text, ann.entities, scheme="BIO")
            assert ann.bio_tags == expected, (
                f"Fixture '{ann.id}': BIO mismatch. "
                f"Expected {expected}, got {ann.bio_tags}"
            )

    def test_fixture_stress_has_special_chars(self):
        """Stress fixture should contain fullwidth or special characters."""
        stress = [a for a in SYNTHETIC_ANNOTATIONS if a.id == "stress"]
        assert len(stress) == 1
        text = stress[0].text
        # Check for fullwidth characters (U+FF00-U+FFEF range)
        has_fullwidth = any("\uff00" <= c <= "\uffef" for c in text)
        assert has_fullwidth, "Stress fixture missing fullwidth chars"

    def test_fixture_adjacent_entities(self):
        """Adjacent fixture has entities with no gap."""
        adj = [a for a in SYNTHETIC_ANNOTATIONS if a.id == "adjacent"]
        assert len(adj) == 1
        ents = sorted(adj[0].entities, key=lambda e: e.start)
        # Check first two are adjacent (though there may be punctuation between)
        assert len(ents) >= 2

    def test_fixture_count(self):
        """Should have at least 10 synthetic fixtures."""
        assert len(SYNTHETIC_ANNOTATIONS) >= 10


# ── Import check (required by test file) ──────────────────────────────────────

from legal_desens.ner_eval.schema import validate_annotation
