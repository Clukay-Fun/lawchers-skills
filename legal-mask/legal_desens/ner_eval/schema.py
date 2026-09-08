"""Annotation JSON schema for NER evaluation (012 stage).

Schema: char-level start/end + BIO tags.
Coordinate system: Python str codepoint indices (consistent with 002).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Entity types handled by NER (regex handles PHONE/ID_CARD/EMAIL) ───────────

NER_ENTITY_TYPES = {"PERSON", "ORG", "LOCATION", "MONEY"}

# Char-level BIO tags: one tag per character in text.
# BIO scheme:  B-X = begin, I-X = inside, O = outside
# BIOES scheme: B-X = begin, I-X = inside, E-X = end, S-X = single, O = outside


@dataclass
class Entity:
    """A single entity span in the annotation."""
    id: str
    entity_type: str
    start: int  # char-level, inclusive, Python str index
    end: int    # char-level, exclusive, Python str index
    text: str   # must equal source_text[start:end]

    def span_length(self) -> int:
        return self.end - self.start


@dataclass
class Annotation:
    """A single annotated text sample."""
    text: str
    entities: List[Entity]
    bio_tags: List[str]  # one tag per character in text
    id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "entities": [
                {
                    "id": e.id,
                    "entity_type": e.entity_type,
                    "start": e.start,
                    "end": e.end,
                    "text": e.text,
                }
                for e in self.entities
            ],
            "bio_tags": self.bio_tags,
            **({"id": self.id} if self.id else {}),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Annotation":
        entities = [
            Entity(
                id=e["id"],
                entity_type=e["entity_type"],
                start=e["start"],
                end=e["end"],
                text=e["text"],
            )
            for e in data["entities"]
        ]
        return cls(
            text=data["text"],
            entities=entities,
            bio_tags=data["bio_tags"],
            id=data.get("id"),
        )


# ── Validation ────────────────────────────────────────────────────────────────


class AnnotationValidationError(Exception):
    """Raised when an annotation fails validation."""
    pass


def validate_annotation(ann: Annotation) -> List[str]:
    """Validate an annotation against all schema rules.

    Returns list of warning strings (empty = valid).
    Raises AnnotationValidationError on hard violations.
    """
    warnings: List[str] = []

    # Rule 1: text[start:end] == entity.text for every entity
    for ent in ann.entities:
        actual = ann.text[ent.start:ent.end]
        if actual != ent.text:
            raise AnnotationValidationError(
                f"Entity '{ent.id}': text[{ent.start}:{ent.end}] = "
                f"{repr(actual)} != entity.text {repr(ent.text)}"
            )

    # Rule 2: start < end
    for ent in ann.entities:
        if ent.start >= ent.end:
            raise AnnotationValidationError(
                f"Entity '{ent.id}': start ({ent.start}) >= end ({ent.end})"
            )

    # Rule 3: entity_type must be a NER type (not regex-handled PII)
    for ent in ann.entities:
        if ent.entity_type not in NER_ENTITY_TYPES:
            raise AnnotationValidationError(
                f"Entity '{ent.id}': entity_type '{ent.entity_type}' is not a "
                f"NER type. NER types: {sorted(NER_ENTITY_TYPES)}. "
                f"PHONE/ID_CARD/EMAIL are handled by regex."
            )

    # Rule 4: bio_tags length must equal text length
    if len(ann.bio_tags) != len(ann.text):
        raise AnnotationValidationError(
            f"bio_tags length ({len(ann.bio_tags)}) != text length ({len(ann.text)})"
        )

    # Rule 5: BIO tags must be consistent with entity spans
    expected_bio = _generate_bio_tags(ann.text, ann.entities, scheme="BIO")
    for i, (actual_tag, expected_tag) in enumerate(zip(ann.bio_tags, expected_bio)):
        if actual_tag != expected_tag:
            warnings.append(
                f"BIO mismatch at char {i}: got '{actual_tag}', "
                f"expected '{expected_tag}' (derived from entities)"
            )

    # Rule 6: entities should not overlap
    sorted_ents = sorted(ann.entities, key=lambda e: e.start)
    for i in range(len(sorted_ents) - 1):
        curr = sorted_ents[i]
        nxt = sorted_ents[i + 1]
        if curr.end > nxt.start:
            warnings.append(
                f"Entities '{curr.id}' and '{nxt.id}' overlap: "
                f"[{curr.start},{curr.end}) and [{nxt.start},{nxt.end})"
            )

    return warnings


def _generate_bio_tags(
    text: str,
    entities: List[Entity],
    scheme: str = "BIO",
) -> List[str]:
    """Generate expected BIO/BIOES tags from entity spans."""
    tags = ["O"] * len(text)

    sorted_ents = sorted(entities, key=lambda e: e.start)
    for ent in sorted_ents:
        for i in range(ent.start, ent.end):
            if i == ent.start:
                if scheme == "BIOES" and ent.span_length() == 1:
                    tags[i] = f"S-{ent.entity_type}"
                else:
                    tags[i] = f"B-{ent.entity_type}"
            elif scheme == "BIOES" and i == ent.end - 1:
                tags[i] = f"E-{ent.entity_type}"
            else:
                tags[i] = f"I-{ent.entity_type}"

    return tags


def validate_annotation_file(path: str | Path) -> Tuple[List[Annotation], List[str]]:
    """Load and validate a JSON file containing annotations.

    Returns (annotations, warnings).
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "annotations" in data:
        items = data["annotations"]
    else:
        raise AnnotationValidationError(
            f"Expected a list of annotations or {{'annotations': [...]}}. "
            f"Got: {type(data)}"
        )

    annotations: List[Annotation] = []
    all_warnings: List[str] = []

    for i, item in enumerate(items):
        try:
            ann = Annotation.from_dict(item)
            warns = validate_annotation(ann)
            for w in warns:
                all_warnings.append(f"[sample {i}] {w}")
            annotations.append(ann)
        except AnnotationValidationError as e:
            all_warnings.append(f"[sample {i}] ERROR: {e}")

    return annotations, all_warnings
