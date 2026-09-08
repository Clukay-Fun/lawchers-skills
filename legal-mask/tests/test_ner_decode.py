"""Tests for NER tag decode logic (002 stage). No model required."""

import pytest
from legal_desens.engine.ner import decode_tags, TAG_SCHEME_BIO, TAG_SCHEME_BIOES


# ── Label maps for testing ────────────────────────────────────────────────────

BIO_LABELS = {
    0: "O",
    1: "B-PER",
    2: "I-PER",
    3: "B-LOC",
    4: "I-LOC",
    5: "B-ORG",
    6: "I-ORG",
}

BIOES_LABELS = {
    0: "O",
    1: "B-PER",
    2: "I-PER",
    3: "E-PER",
    4: "S-PER",
    5: "B-LOC",
    6: "I-LOC",
    7: "E-LOC",
    8: "S-LOC",
}


# ── BIO scheme tests ─────────────────────────────────────────────────────────

class TestBIODecode:
    def test_simple_entity(self):
        """B-PER I-PER → one PER entity."""
        tag_ids = [1, 2, 0]  # B-PER I-PER O
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 1
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 2
        assert len(warnings) == 0

    def test_multiple_entities(self):
        """B-PER O B-LOC → two entities."""
        tag_ids = [1, 0, 3]  # B-PER O B-LOC
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 2
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 1
        assert entities[1].entity_type == "LOC"
        assert entities[1].token_start == 2
        assert entities[1].token_end == 3

    def test_all_o(self):
        """All O → no entities."""
        tag_ids = [0, 0, 0]
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 0
        assert len(warnings) == 0

    def test_empty_input(self):
        """Empty tag_ids → no entities."""
        entities, warnings = decode_tags([], BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 0

    def test_isolated_i_treated_as_b(self):
        """Isolated I-PER (no B-PER before) → treated as B-PER + warning."""
        tag_ids = [2, 2, 0]  # I-PER I-PER O
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 1
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 2
        assert len(warnings) == 1
        assert warnings[0]["type"] == "illegal_transition"
        assert "I-PER" in warnings[0]["detail"]

    def test_type_change_i_treated_as_b(self):
        """B-PER I-LOC (type mismatch) → PER entity, then I-LOC treated as B-LOC."""
        tag_ids = [1, 4, 0]  # B-PER I-LOC O
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 2
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 1
        assert entities[1].entity_type == "LOC"
        assert entities[1].token_start == 1
        assert entities[1].token_end == 2
        assert len(warnings) == 1

    def test_entity_at_end(self):
        """Entity extending to end of sequence."""
        tag_ids = [1, 2]  # B-PER I-PER (no trailing O)
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 1
        assert entities[0].token_end == 2

    def test_b_starts_new_entity_closes_previous(self):
        """B-LOC after B-PER I-PER → closes PER, starts LOC."""
        tag_ids = [1, 2, 3, 0]  # B-PER I-PER B-LOC O
        entities, warnings = decode_tags(tag_ids, BIO_LABELS, TAG_SCHEME_BIO)
        assert len(entities) == 2
        assert entities[0].entity_type == "PER"
        assert entities[0].token_end == 2
        assert entities[1].entity_type == "LOC"
        assert entities[1].token_start == 2


# ── BIOES scheme tests ───────────────────────────────────────────────────────

class TestBIOESDecode:
    def test_simple_bioes(self):
        """B-PER I-PER E-PER → one PER entity."""
        tag_ids = [1, 2, 3, 0]  # B I E O
        entities, warnings = decode_tags(tag_ids, BIOES_LABELS, TAG_SCHEME_BIOES)
        assert len(entities) == 1
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 3

    def test_single_token_s(self):
        """S-PER → single-token entity."""
        tag_ids = [4, 0]  # S-PER O
        entities, warnings = decode_tags(tag_ids, BIOES_LABELS, TAG_SCHEME_BIOES)
        assert len(entities) == 1
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 1

    def test_s_after_entity(self):
        """B-PER E-PER S-LOC → two entities."""
        tag_ids = [1, 3, 8, 0]  # B-PER E-PER S-LOC O
        entities, warnings = decode_tags(tag_ids, BIOES_LABELS, TAG_SCHEME_BIOES)
        assert len(entities) == 2
        assert entities[0].entity_type == "PER"
        assert entities[0].token_end == 2
        assert entities[1].entity_type == "LOC"
        assert entities[1].token_start == 2
        assert entities[1].token_end == 3

    def test_isolated_e_treated_as_entity(self):
        """Isolated E-PER (no B-PER) → single-token entity + warning."""
        tag_ids = [3, 0]  # E-PER O
        entities, warnings = decode_tags(tag_ids, BIOES_LABELS, TAG_SCHEME_BIOES)
        assert len(entities) == 1
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 1
        assert len(warnings) == 1
        assert warnings[0]["type"] == "illegal_transition"

    def test_isolated_i_in_bioes(self):
        """Isolated I-PER in BIOES mode → treated as B-PER + warning."""
        tag_ids = [2, 3, 0]  # I-PER E-PER O
        entities, warnings = decode_tags(tag_ids, BIOES_LABELS, TAG_SCHEME_BIOES)
        assert len(entities) == 1
        assert entities[0].entity_type == "PER"
        assert entities[0].token_start == 0
        assert entities[0].token_end == 2
        assert len(warnings) == 1
