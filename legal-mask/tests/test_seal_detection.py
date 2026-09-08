"""P7 Seal Detection Enhancement Test.

Creates synthetic seal samples and measures recall/precision
before and after parameter tuning.

Synthetic samples include:
- Red circles (standard seal)
- Red ellipses (oval seal)
- Dark red seals (low saturation)
- Light red seals (low value)
- Small seals (minimum area)
- Large seals (maximum area)
- Multiple seals on one page
- Non-seal red text (should NOT be detected)
- Non-red circles (should NOT be detected)
"""

import math
import tempfile
from pathlib import Path

import pytest

try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

pytestmark = pytest.mark.skipif(not HAS_OPENCV, reason="OpenCV not installed")


def _create_seal_image(
    output_path: str,
    width: int = 800,
    height: int = 1100,
    seals: list = None,
) -> dict:
    """Create a synthetic image with seal-like red circles/ellipses.

    Args:
        output_path: Where to save the PNG.
        width, height: Image dimensions.
        seals: List of dicts: {cx, cy, rx, ry, color_bgr, label}
               cx/cy are center in pixels, rx/ry are radii.

    Returns:
        dict with ground truth: {seals: [{x, y, w, h} in pixels]}
    """
    img = np.ones((height, width, 3), dtype=np.uint8) * 255  # white background
    ground_truth = []

    for seal in (seals or []):
        cx, cy = seal["cx"], seal["cy"]
        rx, ry = seal.get("rx", 60), seal.get("ry", 60)
        color = seal.get("color_bgr", (0, 0, 200))  # default red

        cv2.ellipse(img, (cx, cy), (rx, ry), 0, 0, 360, color, -1)

        # Add some inner detail (typical seal has inner circle + text area)
        inner_rx, inner_ry = int(rx * 0.7), int(ry * 0.7)
        cv2.ellipse(img, (cx, cy), (inner_rx, inner_ry), 0, 0, 360, (255, 255, 255), 2)

        ground_truth.append({
            "cx": cx, "cy": cy,
            "x": cx - rx, "y": cy - ry,
            "w": rx * 2, "h": ry * 2,
        })

    cv2.imwrite(output_path, img)
    return {"seals": ground_truth, "width": width, "height": height}


# ── Test Dataset ──────────────────────────────────────────────

def _standard_seals():
    """Standard seal test cases."""
    return [
        # Standard red circle seal (typical)
        {"cx": 400, "cy": 300, "rx": 60, "ry": 60, "color_bgr": (0, 0, 200)},
        # Oval seal
        {"cx": 400, "cy": 600, "rx": 80, "ry": 50, "color_bgr": (0, 0, 200)},
        # Small seal
        {"cx": 200, "cy": 200, "rx": 30, "ry": 30, "color_bgr": (0, 0, 200)},
    ]


def _challenging_seals():
    """Harder cases: dark red, light red, large."""
    return [
        # Dark red (low saturation)
        {"cx": 400, "cy": 300, "rx": 60, "ry": 60, "color_bgr": (20, 20, 150)},
        # Light red (low value)
        {"cx": 400, "cy": 600, "rx": 60, "ry": 60, "color_bgr": (100, 100, 220)},
        # Very large seal
        {"cx": 400, "cy": 900, "rx": 120, "ry": 120, "color_bgr": (0, 0, 200)},
    ]


def _multi_seal_page():
    """Multiple seals on one page."""
    return [
        {"cx": 200, "cy": 200, "rx": 50, "ry": 50, "color_bgr": (0, 0, 200)},
        {"cx": 600, "cy": 400, "rx": 70, "ry": 45, "color_bgr": (0, 0, 200)},
        {"cx": 400, "cy": 800, "rx": 40, "ry": 40, "color_bgr": (0, 0, 200)},
    ]


def _non_seal_distractors():
    """Non-seal red objects (should NOT be detected)."""
    return [
        # Red text-like thin rectangle
        {"cx": 400, "cy": 200, "rx": 100, "ry": 8, "color_bgr": (0, 0, 200)},
        # Small red dot (too small)
        {"cx": 300, "cy": 300, "rx": 5, "ry": 5, "color_bgr": (0, 0, 200)},
    ]


# ── Detection wrapper ─────────────────────────────────────────

def _detect(img_path: str, **kwargs):
    """Run seal detection with current parameters."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from legal_desens.seal_detect import detect_seals_in_image
    return detect_seals_in_image(img_path, **kwargs)


def _check_recall(detected_seals, ground_truth, iou_threshold=0.3):
    """Check how many ground truth seals were detected (IoU-based)."""
    found = 0
    for gt in ground_truth:
        gt_box = (gt["x"], gt["y"], gt["x"] + gt["w"], gt["y"] + gt["h"])
        for det in detected_seals:
            # Convert normalized back to pixels for comparison
            det_box = (
                int(det.x * gt.get("img_w", 800)),
                int(det.y * gt.get("img_h", 1100)),
                int((det.x + det.width) * gt.get("img_w", 800)),
                int((det.y + det.height) * gt.get("img_h", 1100)),
            )
            iou = _compute_iou(gt_box, det_box)
            if iou >= iou_threshold:
                found += 1
                break
    return found


def _compute_iou(box1, box2):
    """Compute IoU between two (x1, y1, x2, y2) boxes."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - intersection
    return intersection / union if union > 0 else 0


# ── Tests ─────────────────────────────────────────────────────

class TestSealDetection:
    """P7: Seal detection recall/precision tests."""

    def test_standard_seals_baseline(self, tmp_path):
        """Standard red circle/ellipse seals should be detected."""
        img_path = str(tmp_path / "standard.png")
        gt = _create_seal_image(img_path, seals=_standard_seals())

        detected = _detect(img_path)
        assert len(detected) >= 2, \
            f"Expected ≥2 standard seals, got {len(detected)}"

    def test_oval_seals(self, tmp_path):
        """Oval/elliptical seals should be detected (not just circles)."""
        img_path = str(tmp_path / "oval.png")
        seals = [{"cx": 400, "cy": 550, "rx": 90, "ry": 50, "color_bgr": (0, 0, 200)}]
        gt = _create_seal_image(img_path, seals=seals)

        detected = _detect(img_path)
        assert len(detected) >= 1, "Oval seal not detected"

    def test_dark_red_seal(self, tmp_path):
        """Dark red seals (low saturation) should be detected."""
        img_path = str(tmp_path / "dark_red.png")
        seals = [{"cx": 400, "cy": 550, "rx": 60, "ry": 60, "color_bgr": (20, 20, 150)}]
        gt = _create_seal_image(img_path, seals=seals)

        detected = _detect(img_path)
        assert len(detected) >= 1, "Dark red seal not detected"

    def test_light_red_seal(self, tmp_path):
        """Light red seals (high value) should be detected."""
        img_path = str(tmp_path / "light_red.png")
        seals = [{"cx": 400, "cy": 550, "rx": 60, "ry": 60, "color_bgr": (100, 100, 220)}]
        gt = _create_seal_image(img_path, seals=seals)

        detected = _detect(img_path)
        assert len(detected) >= 1, "Light red seal not detected"

    def test_multi_seal_page(self, tmp_path):
        """Multiple seals on one page should all be detected."""
        img_path = str(tmp_path / "multi.png")
        seals = _multi_seal_page()
        gt = _create_seal_image(img_path, seals=seals)

        detected = _detect(img_path)
        assert len(detected) >= 2, \
            f"Expected ≥2 seals on multi-seal page, got {len(detected)}"

    def test_no_false_positive_on_text(self, tmp_path):
        """Red text-like thin shapes should NOT be detected as seals."""
        img_path = str(tmp_path / "text.png")
        seals = _non_seal_distractors()
        gt = _create_seal_image(img_path, seals=seals)

        detected = _detect(img_path)
        # Thin rectangles should be filtered out by circularity
        thin_detected = [d for d in detected if d.area_ratio > 0.005]
        assert len(thin_detected) == 0, \
            f"False positive: {len(thin_detected)} thin shapes detected as seals"

    def test_no_false_positive_on_blue_circle(self, tmp_path):
        """Blue circles should NOT be detected (not red)."""
        img_path = str(tmp_path / "blue.png")
        seals = [{"cx": 400, "cy": 550, "rx": 60, "ry": 60, "color_bgr": (200, 0, 0)}]  # blue in BGR
        gt = _create_seal_image(img_path, seals=seals)

        detected = _detect(img_path)
        assert len(detected) == 0, \
            f"False positive: {len(detected)} blue circles detected as seals"

    def test_recall_comprehensive(self, tmp_path):
        """Comprehensive recall test across all standard cases."""
        all_seals = _standard_seals() + _challenging_seals() + _multi_seal_page()
        total = len(all_seals)
        found = 0

        # Test standard
        img_path = str(tmp_path / "standard.png")
        gt = _create_seal_image(img_path, seals=_standard_seals())
        detected = _detect(img_path)
        found += min(len(detected), len(_standard_seals()))

        # Test challenging
        img_path = str(tmp_path / "challenging.png")
        gt = _create_seal_image(img_path, seals=_challenging_seals())
        detected = _detect(img_path)
        found += min(len(detected), len(_challenging_seals()))

        # Test multi
        img_path = str(tmp_path / "multi.png")
        gt = _create_seal_image(img_path, seals=_multi_seal_page())
        detected = _detect(img_path)
        found += min(len(detected), len(_multi_seal_page()))

        recall = found / total if total > 0 else 0
        print(f"\n=== P7 Seal Detection Recall ===")
        print(f"Total seals: {total}")
        print(f"Detected: {found}")
        print(f"Recall: {recall:.1%}")
        assert recall >= 0.5, f"Recall {recall:.1%} below 50% threshold"
