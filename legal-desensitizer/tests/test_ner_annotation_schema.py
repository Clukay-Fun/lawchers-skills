"""Unit tests for annotation JSON schema and validator (012 stage)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.ner_eval.schema import (
    Annotation,
    AnnotationValidationError,
    Entity,
    validate_annotation,
    validate_annotation_file,
    _generate_bio_tags,
    NER_ENTITY_TYPES,
)


# ── Entity construction ───────────────────────────────────────────────────────

class TestEntity:
    def test_basic(self):
        e = Entity(id="e1", entity_type="PERSON", start=0, end=2, text="张三")
        assert e.span_length() == 2

    def test_single_char(self):
        e = Entity(id="e1", entity_type="PERSON", start=0, end=1, text="张")
        assert e.span_length() == 1


# ── Annotation construction ───────────────────────────────────────────────────

class TestAnnotation:
    def test_from_dict_and_to_dict_roundtrip(self):
        data = {
            "text": "张三在北京",
            "entities": [
                {"id": "e1", "entity_type": "PERSON", "start": 0, "end": 2, "text": "张三"},
                {"id": "e2", "entity_type": "LOCATION", "start": 3, "end": 5, "text": "北京"},
            ],
            "bio_tags": ["B-PER", "I-PER", "O", "B-LOC", "I-LOC"],
        }
        ann = Annotation.from_dict(data)
        assert ann.text == "张三在北京"
        assert len(ann.entities) == 2
        assert ann.entities[0].text == "张三"

        back = ann.to_dict()
        assert back["text"] == data["text"]
        assert len(back["entities"]) == 2
        assert back["bio_tags"] == data["bio_tags"]

    def test_from_dict_with_id(self):
        data = {
            "id": "sample_1",
            "text": "测试",
            "entities": [],
            "bio_tags": ["O", "O"],
        }
        ann = Annotation.from_dict(data)
        assert ann.id == "sample_1"


# ── Validation: hard rules (must raise) ───────────────────────────────────────

class TestValidationHardRules:
    def test_text_start_end_mismatch_raises(self):
        ann = Annotation(
            text="张三在北京",
            entities=[Entity(id="e1", entity_type="PERSON", start=0, end=2, text="李四")],
            bio_tags=["B-PER", "I-PER", "O", "O", "O"],
        )
        with pytest.raises(AnnotationValidationError, match="text\\[0:2\\]"):
            validate_annotation(ann)

    def test_start_ge_end_raises(self):
        ann = Annotation(
            text="张三",
            entities=[Entity(id="e1", entity_type="PERSON", start=2, end=2, text="")],
            bio_tags=["O", "O"],
        )
        with pytest.raises(AnnotationValidationError, match="start.*>=.*end"):
            validate_annotation(ann)

    def test_invalid_entity_type_raises(self):
        ann = Annotation(
            text="电话138001380000",
            entities=[Entity(id="e1", entity_type="PHONE", start=0, end=14, text="电话138001380000")],
            bio_tags=["B-PHONE"] + ["I-PHONE"] * 13,
        )
        with pytest.raises(AnnotationValidationError, match="not a NER type"):
            validate_annotation(ann)

    def test_bio_tags_length_mismatch_raises(self):
        ann = Annotation(
            text="张三在北京",
            entities=[Entity(id="e1", entity_type="PERSON", start=0, end=2, text="张三")],
            bio_tags=["B-PER", "I-PER"],  # missing 3 tags
        )
        with pytest.raises(AnnotationValidationError, match="bio_tags length"):
            validate_annotation(ann)


# ── Validation: soft rules (warnings) ─────────────────────────────────────────

class TestValidationSoftRules:
    def test_bio_mismatch_warning(self):
        ann = Annotation(
            text="张三在北京",
            entities=[Entity(id="e1", entity_type="PERSON", start=0, end=2, text="张三")],
            bio_tags=["O", "O", "O", "O", "O"],  # wrong: should be B-PER I-PER O O O
        )
        warnings = validate_annotation(ann)
        assert len(warnings) >= 2  # at least 2 mismatched positions
        assert "BIO mismatch" in warnings[0]

    def test_overlap_warning(self):
        ann = Annotation(
            text="张三在北京",
            entities=[
                Entity(id="e1", entity_type="PERSON", start=0, end=3, text="张三在"),
                Entity(id="e2", entity_type="LOCATION", start=2, end=5, text="在北京"),
            ],
            bio_tags=["B-PER", "I-PER", "I-PER", "I-LOC", "I-LOC"],
        )
        warnings = validate_annotation(ann)
        assert any("overlap" in w for w in warnings)

    def test_valid_annotation_no_warnings(self):
        ann = Annotation(
            text="张三在北京",
            entities=[
                Entity(id="e1", entity_type="PERSON", start=0, end=2, text="张三"),
                Entity(id="e2", entity_type="LOCATION", start=3, end=5, text="北京"),
            ],
            bio_tags=["B-PERSON", "I-PERSON", "O", "B-LOCATION", "I-LOCATION"],
        )
        warnings = validate_annotation(ann)
        assert len(warnings) == 0


# ── BIO tag generation ────────────────────────────────────────────────────────

class TestBIOGeneration:
    def test_basic_bio(self):
        text = "张三在北京"
        entities = [
            Entity(id="e1", entity_type="PERSON", start=0, end=2, text="张三"),
            Entity(id="e2", entity_type="LOCATION", start=3, end=5, text="北京"),
        ]
        tags = _generate_bio_tags(text, entities, scheme="BIO")
        assert tags == ["B-PERSON", "I-PERSON", "O", "B-LOCATION", "I-LOCATION"]

    def test_no_entities(self):
        tags = _generate_bio_tags("无关文本", [], scheme="BIO")
        assert tags == ["O", "O", "O", "O"]

    def test_single_char_entity_bio(self):
        text = "甲说"
        entities = [Entity(id="e1", entity_type="PERSON", start=0, end=1, text="甲")]
        tags = _generate_bio_tags(text, entities, scheme="BIO")
        assert tags == ["B-PERSON", "O"]

    def test_bioes_single_char(self):
        text = "甲说"
        entities = [Entity(id="e1", entity_type="PERSON", start=0, end=1, text="甲")]
        tags = _generate_bio_tags(text, entities, scheme="BIOES")
        assert tags == ["S-PERSON", "O"]

    def test_bioes_multi_char(self):
        text = "张三说"
        entities = [Entity(id="e1", entity_type="PERSON", start=0, end=2, text="张三")]
        tags = _generate_bio_tags(text, entities, scheme="BIOES")
        assert tags == ["B-PERSON", "E-PERSON", "O"]

    def test_bioes_long_entity(self):
        text = "某某公司"
        entities = [Entity(id="e1", entity_type="ORG", start=0, end=4, text="某某公司")]
        tags = _generate_bio_tags(text, entities, scheme="BIOES")
        assert tags == ["B-ORG", "I-ORG", "I-ORG", "E-ORG"]


# ── File validation ───────────────────────────────────────────────────────────

class TestFileValidation:
    def test_load_list_format(self, tmp_path):
        data = [
            {
                "text": "张三在北京",
                "entities": [
                    {"id": "e1", "entity_type": "PERSON", "start": 0, "end": 2, "text": "张三"},
                ],
                "bio_tags": ["B-PER", "I-PER", "O", "O", "O"],
            }
        ]
        p = tmp_path / "test.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        anns, warnings = validate_annotation_file(p)
        assert len(anns) == 1
        assert anns[0].text == "张三在北京"

    def test_load_dict_format(self, tmp_path):
        data = {
            "annotations": [
                {
                    "text": "测试文本",
                    "entities": [],
                    "bio_tags": ["O", "O", "O", "O"],
                }
            ]
        }
        p = tmp_path / "test.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        anns, warnings = validate_annotation_file(p)
        assert len(anns) == 1

    def test_invalid_format_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"bad": "format"}', encoding="utf-8")
        with pytest.raises(AnnotationValidationError, match="Expected"):
            validate_annotation_file(p)

    def test_validation_error_collected_as_warning(self, tmp_path):
        data = [
            {
                "text": "张三",
                "entities": [
                    {"id": "e1", "entity_type": "PHONE", "start": 0, "end": 2, "text": "张三"},
                ],
                "bio_tags": ["B-PHONE", "I-PHONE"],
            }
        ]
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        anns, warnings = validate_annotation_file(p)
        assert len(anns) == 0
        assert len(warnings) == 1
        assert "ERROR" in warnings[0]


# ── NER entity type constants ─────────────────────────────────────────────────

class TestNEREntityTypes:
    def test_excludes_regex_types(self):
        assert "PHONE" not in NER_ENTITY_TYPES
        assert "ID_CARD" not in NER_ENTITY_TYPES
        assert "EMAIL" not in NER_ENTITY_TYPES

    def test_includes_ner_types(self):
        assert "PERSON" in NER_ENTITY_TYPES
        assert "ORG" in NER_ENTITY_TYPES
        assert "LOCATION" in NER_ENTITY_TYPES
        assert "MONEY" in NER_ENTITY_TYPES
