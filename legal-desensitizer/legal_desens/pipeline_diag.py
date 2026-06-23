"""Pipeline diagnostics: call counters and timing for scan pipeline."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StageTiming:
    """Timing for a single pipeline stage."""
    stage: str
    page: Optional[int]
    start: float
    end: float

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000


@dataclass
class PipelineDiagnostics:
    """Track call counts and timing for scan pipeline.

    Used to verify:
    - render_document_calls == 1
    - rendered_pages == N
    - original_ocr_calls == N
    - verification_ocr_calls == N
    - redact_calls == N
    - rapidocr_instances == 1
    - ner_engine_instances == 1 (0 if regex-only)
    - onnx_sessions == 1 (0 if regex-only)
    """
    # Call counts
    render_document_calls: int = 0
    rendered_pages: int = 0
    original_ocr_calls: int = 0
    verification_ocr_calls: int = 0
    redact_calls: int = 0

    # Instance counts
    rapidocr_instances: int = 0
    ner_engine_instances: int = 0
    onnx_sessions: int = 0

    # Timing
    timings: List[StageTiming] = field(default_factory=list)

    # Failure tracking
    failed_pages: List[int] = field(default_factory=list)
    failure_categories: Dict[int, str] = field(default_factory=dict)

    def start_stage(self, stage: str, page: Optional[int] = None) -> float:
        """Record stage start time. Returns start time."""
        return time.perf_counter()

    def end_stage(self, stage: str, start_time: float, page: Optional[int] = None) -> None:
        """Record stage end time."""
        self.timings.append(StageTiming(
            stage=stage,
            page=page,
            start=start_time,
            end=time.perf_counter(),
        ))

    def record_render(self, page_count: int) -> None:
        """Record a render_document call."""
        self.render_document_calls += 1
        self.rendered_pages += page_count

    def record_ocr(self, is_verification: bool = False) -> None:
        """Record an OCR call."""
        if is_verification:
            self.verification_ocr_calls += 1
        else:
            self.original_ocr_calls += 1

    def record_redact(self) -> None:
        """Record a redact call."""
        self.redact_calls += 1

    def record_rapidocr_instance(self) -> None:
        """Record RapidOCR instantiation."""
        self.rapidocr_instances += 1

    def record_ner_instance(self) -> None:
        """Record NEREngine instantiation."""
        self.ner_engine_instances += 1

    def record_onnx_session(self) -> None:
        """Record ONNX session creation."""
        self.onnx_sessions += 1

    def record_failure(self, page: int, category: str) -> None:
        """Record a page failure."""
        self.failed_pages.append(page)
        self.failure_categories[page] = category

    def to_dict(self) -> dict:
        """Export diagnostics as dict for audit."""
        return {
            "call_counts": {
                "render_document": self.render_document_calls,
                "rendered_pages": self.rendered_pages,
                "original_ocr": self.original_ocr_calls,
                "verification_ocr": self.verification_ocr_calls,
                "redact": self.redact_calls,
            },
            "instance_counts": {
                "rapidocr": self.rapidocr_instances,
                "ner_engine": self.ner_engine_instances,
                "onnx_sessions": self.onnx_sessions,
            },
            "failed_pages": self.failed_pages,
            "failure_categories": self.failure_categories,
            "stage_timings": [
                {
                    "stage": t.stage,
                    "page": t.page,
                    "duration_ms": round(t.duration_ms, 1),
                }
                for t in self.timings
            ],
        }

    def assert_hard_metrics(self, expected_pages: int, mode: str = "regex-only") -> List[str]:
        """Check hard metrics. Returns list of violations (empty = pass)."""
        violations = []

        if self.render_document_calls != 1:
            violations.append(f"render_document_calls={self.render_document_calls}, expected 1")
        if self.rendered_pages != expected_pages:
            violations.append(f"rendered_pages={self.rendered_pages}, expected {expected_pages}")
        if self.original_ocr_calls != expected_pages:
            violations.append(f"original_ocr_calls={self.original_ocr_calls}, expected {expected_pages}")
        if self.verification_ocr_calls != expected_pages:
            violations.append(f"verification_ocr_calls={self.verification_ocr_calls}, expected {expected_pages}")
        if self.redact_calls != expected_pages:
            violations.append(f"redact_calls={self.redact_calls}, expected {expected_pages}")
        if self.rapidocr_instances != 1:
            violations.append(f"rapidocr_instances={self.rapidocr_instances}, expected 1")

        if mode != "regex-only":
            if self.ner_engine_instances != 1:
                violations.append(f"ner_engine_instances={self.ner_engine_instances}, expected 1")
            if self.onnx_sessions != 1:
                violations.append(f"onnx_sessions={self.onnx_sessions}, expected 1")
        else:
            if self.ner_engine_instances != 0:
                violations.append(f"ner_engine_instances={self.ner_engine_instances}, expected 0 (regex-only)")
            if self.onnx_sessions != 0:
                violations.append(f"onnx_sessions={self.onnx_sessions}, expected 0 (regex-only)")

        return violations

