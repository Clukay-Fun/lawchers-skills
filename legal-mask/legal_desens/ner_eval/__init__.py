"""NER annotation schema, evaluation harness, and synthetic fixtures (012 stage).

All data is synthetic. No real legal text. No model training.
"""

from .schema import Annotation, Entity, validate_annotation, validate_annotation_file
from .harness import (
    EvalReport,
    EvalResult,
    GateResult,
    compare_annotations,
    recall_gate,
    int8_gate,
)
from .fixtures import SYNTHETIC_ANNOTATIONS

__all__ = [
    "Annotation",
    "Entity",
    "validate_annotation",
    "validate_annotation_file",
    "EvalReport",
    "EvalResult",
    "GateResult",
    "compare_annotations",
    "recall_gate",
    "int8_gate",
    "SYNTHETIC_ANNOTATIONS",
]
