"""OCR Spike Evaluation: RapidOCR vs PaddleOCR (PP-OCRv6).

Runs both engines on the same 3-page synthetic scan PDF.
Produces: rapidocr.json, ppocrv6.json, overlay images, timing data.
"""

import json
import os
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(SPIKE_DIR, "samples")
OUTPUT_DIR = os.path.join(SPIKE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

PDF_PATH = os.path.join(SAMPLES_DIR, "synthetic_labor_case_3pages.pdf")

# ---------- helpers ----------

def _get_font(size=14):
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_pdf_pages(pdf_path, dpi=200):
    """Render PDF pages to PNG images."""
    doc = fitz.open(pdf_path)
    paths = []
    for i, page in enumerate(doc):
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        out = os.path.join(OUTPUT_DIR, f"page_{i+1}.png")
        pix.save(out)
        paths.append(out)
    doc.close()
    return paths


def draw_overlay(image_path, ocr_lines, output_path, engine_name, box_color=(255, 0, 0)):
    """Draw OCR bounding boxes on a copy of the image."""
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _get_font(12)

    for i, line_data in enumerate(ocr_lines):
        box = line_data["box"]
        text = line_data["text"]
        conf = line_data["confidence"]

        # Draw polygon
        pts = [(int(p[0]), int(p[1])) for p in box]
        draw.polygon(pts, outline=box_color, fill=None)
        draw.line(pts + [pts[0]], fill=box_color, width=2)

        # Label with text preview and confidence
        label = f"[{i}] {text[:20]}... {conf:.2f}"
        x, y = int(box[0][0]), max(0, int(box[0][1]) - 16)
        draw.text((x, y), label, fill=box_color, font=font)

    img.save(output_path)
    return output_path


# ---------- engine runners ----------

def run_rapidocr_on_pages(page_images):
    """Run RapidOCR on each page, return per-page results."""
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    results = []
    for page_idx, img_path in enumerate(page_images):
        t0 = time.perf_counter()
        raw_result, elapsed = engine(img_path)
        t1 = time.perf_counter()
        page_time = t1 - t0

        lines = []
        if raw_result:
            for item in raw_result:
                box, text, conf = item[0], item[1], item[2]
                lines.append({
                    "text": text,
                    "box": box,
                    "confidence": round(conf, 4),
                })

        results.append({
            "page": page_idx + 1,
            "image": os.path.basename(img_path),
            "lines": lines,
            "total_lines": len(lines),
            "full_text": "\n".join(l["text"] for l in lines),
            "time_seconds": round(page_time, 4),
        })
    return results


def run_paddleocr_on_pages(page_images, use_ppocrv6=True):
    """Run PaddleOCR on each page, return per-page results."""
    from paddleocr import PaddleOCR

    # PP-OCRv6 is default in PaddleOCR 3.7.0
    # use_angle_cls=True for rotated text, lang='ch' for Chinese
    engine = PaddleOCR(
        use_textline_orientation=True,
        lang="ch",
        use_gpu=False,
    )

    results = []
    for page_idx, img_path in enumerate(page_images):
        t0 = time.perf_counter()
        raw_result = engine.ocr(img_path, cls=True)
        t1 = time.perf_counter()
        page_time = t1 - t0

        lines = []
        if raw_result and raw_result[0]:
            for item in raw_result[0]:
                box = item[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = item[1][0]
                conf = item[1][1]
                lines.append({
                    "text": text,
                    "box": box,
                    "confidence": round(conf, 4),
                })

        results.append({
            "page": page_idx + 1,
            "image": os.path.basename(img_path),
            "lines": lines,
            "total_lines": len(lines),
            "full_text": "\n".join(l["text"] for l in lines),
            "time_seconds": round(page_time, 4),
        })
    return results


def run_stability(engine_type, page_images, runs=3):
    """Run engine N times on same pages, return consistency metrics."""
    all_runs = []
    for run_idx in range(runs):
        if engine_type == "rapidocr":
            result = run_rapidocr_on_pages(page_images)
        else:
            result = run_paddleocr_on_pages(page_images)
        all_runs.append(result)

    # Compare runs: text consistency, line count consistency
    metrics = {"runs": runs, "per_page": []}
    for page_idx in range(len(page_images)):
        texts = [all_runs[r][page_idx]["full_text"] for r in range(runs)]
        line_counts = [all_runs[r][page_idx]["total_lines"] for r in range(runs)]
        times = [all_runs[r][page_idx]["time_seconds"] for r in range(runs)]

        all_text_same = all(t == texts[0] for t in texts)
        all_count_same = all(c == line_counts[0] for c in line_counts)

        metrics["per_page"].append({
            "page": page_idx + 1,
            "text_identical": all_text_same,
            "line_count_identical": all_count_same,
            "line_counts": line_counts,
            "times": [round(t, 4) for t in times],
            "avg_time": round(sum(times) / len(times), 4),
        })
    return metrics


# ---------- sensitive entity recall ----------

# Ground truth entities for the synthetic sample
GROUND_TRUTH = {
    "phone": ["13812345678", "13987654321", "15600123456", "010-82345678"],
    "id_card": ["110108199203151234", "110105198807206789"],
    "person_name": ["张伟华", "李晓明", "王丽芳", "赵志刚"],
    "company": ["北京明远科技有限公司"],
    "amount": ["28000", "22000", "6000", "42000", "75600", "84000", "3000", "15600", "5600"],
    "social_credit_code": ["91110108MA01ABCDEF"],
}


def check_entity_recall(ocr_text, ground_truth):
    """Check which ground truth entities appear in OCR text."""
    recall = {}
    for entity_type, values in ground_truth.items():
        found = []
        missed = []
        for v in values:
            if v in ocr_text:
                found.append(v)
            else:
                missed.append(v)
        recall[entity_type] = {
            "total": len(values),
            "found": len(found),
            "missed": len(missed),
            "recall_rate": round(len(found) / len(values) * 100, 1) if values else 100.0,
            "missed_values": missed,
        }
    return recall


# ---------- main ----------

def main():
    print("=" * 60)
    print("OCR Spike: RapidOCR vs PaddleOCR (PP-OCRv6)")
    print("=" * 60)

    # Machine info
    import platform
    machine_info = {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    }
    print(f"Machine: {machine_info['machine']} / {machine_info['platform']}")

    # Render PDF pages
    print("\n[1/7] Rendering PDF pages to PNG...")
    page_images = render_pdf_pages(PDF_PATH, dpi=200)
    print(f"  Rendered {len(page_images)} pages")

    # RapidOCR
    print("\n[2/7] Running RapidOCR...")
    from rapidocr_onnxruntime import RapidOCR as _ROC
    rapidocr_version = getattr(_ROC, '__version__', 'unknown')
    t0 = time.perf_counter()
    rapidocr_results = run_rapidocr_on_pages(page_images)
    rapidocr_total = time.perf_counter() - t0
    print(f"  RapidOCR total: {rapidocr_total:.2f}s")
    for r in rapidocr_results:
        print(f"    Page {r['page']}: {r['total_lines']} lines, {r['time_seconds']:.2f}s")

    # PaddleOCR (PP-OCRv6)
    print("\n[3/7] Running PaddleOCR (PP-OCRv6)...")
    import paddleocr
    ppocr_version = paddleocr.__version__
    t0 = time.perf_counter()
    ppocr_results = run_paddleocr_on_pages(page_images, use_ppocrv6=True)
    ppocr_total = time.perf_counter() - t0
    print(f"  PaddleOCR total: {ppocr_total:.2f}s")
    for r in ppocr_results:
        print(f"    Page {r['page']}: {r['total_lines']} lines, {r['time_seconds']:.2f}s")

    # Entity recall
    print("\n[4/7] Checking entity recall...")
    rapidocr_all_text = "\n".join(r["full_text"] for r in rapidocr_results)
    ppocr_all_text = "\n".join(r["full_text"] for r in ppocr_results)
    rapidocr_recall = check_entity_recall(rapidocr_all_text, GROUND_TRUTH)
    ppocr_recall = check_entity_recall(ppocr_all_text, GROUND_TRUTH)
    print("  RapidOCR recall:")
    for k, v in rapidocr_recall.items():
        print(f"    {k}: {v['found']}/{v['total']} ({v['recall_rate']}%)")
    print("  PaddleOCR recall:")
    for k, v in ppocr_recall.items():
        print(f"    {k}: {v['found']}/{v['total']} ({v['recall_rate']}%)")

    # Stability (3 runs)
    print("\n[5/7] Stability test (3 runs each)...")
    rapidocr_stability = run_stability("rapidocr", page_images, runs=3)
    ppocr_stability = run_stability("paddleocr", page_images, runs=3)
    print("  RapidOCR stability:")
    for p in rapidocr_stability["per_page"]:
        print(f"    Page {p['page']}: text_identical={p['text_identical']}, "
              f"line_count_identical={p['line_count_identical']}, "
              f"avg_time={p['avg_time']:.2f}s")
    print("  PaddleOCR stability:")
    for p in ppocr_stability["per_page"]:
        print(f"    Page {p['page']}: text_identical={p['text_identical']}, "
              f"line_count_identical={p['line_count_identical']}, "
              f"avg_time={p['avg_time']:.2f}s")

    # Overlay images
    print("\n[6/7] Generating overlay images...")
    overlay_paths = {"rapidocr": [], "paddleocr": []}
    for page_idx, img_path in enumerate(page_images):
        # RapidOCR overlay
        ro_out = os.path.join(OUTPUT_DIR, f"overlay_rapidocr_page{page_idx+1}.png")
        draw_overlay(img_path, rapidocr_results[page_idx]["lines"], ro_out, "RapidOCR",
                     box_color=(255, 0, 0))
        overlay_paths["rapidocr"].append(ro_out)

        # PaddleOCR overlay
        po_out = os.path.join(OUTPUT_DIR, f"overlay_ppocrv6_page{page_idx+1}.png")
        draw_overlay(img_path, ppocr_results[page_idx]["lines"], po_out, "PP-OCRv6",
                     box_color=(0, 128, 255))
        overlay_paths["paddleocr"].append(po_out)

        # Combined overlay (both engines on same image)
        combined_out = os.path.join(OUTPUT_DIR, f"overlay_combined_page{page_idx+1}.png")
        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = _get_font(10)

        # RapidOCR in red
        for i, line_data in enumerate(rapidocr_results[page_idx]["lines"]):
            box = line_data["box"]
            pts = [(int(p[0]), int(p[1])) for p in box]
            draw.polygon(pts, outline=(255, 0, 0))
            draw.line(pts + [pts[0]], fill=(255, 0, 0), width=2)

        # PaddleOCR in blue
        for i, line_data in enumerate(ppocr_results[page_idx]["lines"]):
            box = line_data["box"]
            pts = [(int(p[0]), int(p[1])) for p in box]
            draw.polygon(pts, outline=(0, 128, 255))
            draw.line(pts + [pts[0]], fill=(0, 128, 255), width=2)

        # Legend
        draw.text((10, 10), "Red=RapidOCR  Blue=PaddleOCR(PP-OCRv6)", fill=(0, 0, 0), font=font)
        img.save(combined_out)

    print(f"  Generated {len(overlay_paths['rapidocr']) + len(overlay_paths['paddleocr']) + len(page_images)} overlay images")

    # Save JSON outputs
    print("\n[7/7] Saving JSON outputs...")

    # Get model sizes (approximate)
    rapidocr_data = {
        "engine": "rapidocr-onnxruntime",
        "version": rapidocr_version,
        "machine": machine_info,
        "gpu": False,
        "pages": rapidocr_results,
        "total_time": round(rapidocr_total, 4),
        "entity_recall": rapidocr_recall,
        "stability": rapidocr_stability,
    }

    ppocr_data = {
        "engine": "paddleocr",
        "version": ppocr_version,
        "pp_engine": "PP-OCRv6",
        "paddlepaddle_version": "3.3.1",
        "machine": machine_info,
        "gpu": False,
        "pages": ppocr_results,
        "total_time": round(ppocr_total, 4),
        "entity_recall": ppocr_recall,
        "stability": ppocr_stability,
    }

    rapidocr_json = os.path.join(OUTPUT_DIR, "rapidocr.json")
    ppocr_json = os.path.join(OUTPUT_DIR, "ppocrv6.json")

    with open(rapidocr_json, "w", encoding="utf-8") as f:
        json.dump(rapidocr_data, f, ensure_ascii=False, indent=2)
    with open(ppocr_json, "w", encoding="utf-8") as f:
        json.dump(ppocr_data, f, ensure_ascii=False, indent=2)

    print(f"  {rapidocr_json}")
    print(f"  {ppocr_json}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"RapidOCR v{rapidocr_version}: {rapidocr_total:.2f}s total, "
          f"{sum(r['total_lines'] for r in rapidocr_results)} lines total")
    print(f"PaddleOCR v{ppocr_version} (PP-OCRv6): {ppocr_total:.2f}s total, "
          f"{sum(r['total_lines'] for r in ppocr_results)} lines total")
    print(f"\nOverlay images: {OUTPUT_DIR}/overlay_*.png")
    print(f"JSON outputs: {OUTPUT_DIR}/rapidocr.json, {OUTPUT_DIR}/ppocrv6.json")


if __name__ == "__main__":
    main()
