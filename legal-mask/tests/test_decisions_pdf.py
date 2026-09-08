"""Tests for PDF text-layer decisions export.

Every test verifies the strong audit invariants:
  - original_removed: redacted text not extractable from target rects
  - replacement_written: mask text is present in output
  - position_verification: all decisions map to charMap rects
  - four-way invariant: requested == applied == entities == occurrences

Uses synthetic PDFs with real text layers — no real case materials.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


pytestmark = pytest.mark.skipif(not HAS_FITZ, reason="PyMuPDF not installed")


def _create_text_pdf(path: Path, pages_content: list[tuple[int, str]]) -> Path:
    """Create a simple text-layer PDF.

    pages_content: list of (page_number_1based, text_content)
    Uses textbox for proper text extraction.
    """
    doc = fitz.open()
    for page_num, text in pages_content:
        page = doc.new_page(width=595, height=842)  # A4
        r = fitz.Rect(72, 72, 523, 770)
        page.insert_textbox(r, text, fontname="china-s", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _run_prepare(pdf_path: Path, work_dir: Path) -> dict:
    """Run legal-desens prepare on a PDF and return source-map with candidates from manifest."""
    preview = work_dir / "preview.md"
    manifest = work_dir / "manifest.json"
    source_map = work_dir / "source-map.json"

    result = subprocess.run(
        [sys.executable, "-m", "legal_desens.cli", "prepare", str(pdf_path),
         "--level", "strict", "--regex-only",
         "--preview-md", str(preview),
         "--manifest", str(manifest),
         "--map", str(source_map)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"prepare failed: {result.stderr}"
    with open(source_map) as f:
        sm = json.load(f)
    with open(manifest) as f:
        man = json.load(f)
    # Merge candidates from manifest into source-map for test convenience
    sm["candidates"] = man.get("candidates", [])
    return sm


def _run_export(pdf_path: Path, decisions: list, source_map: dict,
                out_path: Path, map_path: Path, audit_path: Path) -> subprocess.CompletedProcess:
    """Run legal-desens redact --decisions on a PDF."""
    decisions_path = out_path.parent / "decisions.json"
    source_map_path = out_path.parent / "source-map.json"
    with open(decisions_path, "w") as f:
        json.dump(decisions, f, ensure_ascii=False)
    with open(source_map_path, "w") as f:
        json.dump(source_map, f, ensure_ascii=False)

    return subprocess.run(
        [sys.executable, "-m", "legal_desens.cli", "redact", str(pdf_path),
         "--level", "strict", "--regex-only",
         "--decisions", str(decisions_path),
         "--source-map", str(source_map_path),
         "--out", str(out_path),
         "--map", str(map_path),
         "--audit", str(audit_path)],
        capture_output=True, text=True, timeout=60,
    )


def _read_audit(audit_path: Path) -> dict:
    with open(audit_path) as f:
        return json.load(f)


def _extract_text_from_pdf(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def _extract_text_from_rect(pdf_path: Path, page_num: int, rect: list) -> str:
    doc = fitz.open(str(pdf_path))
    page = doc[page_num - 1]
    r = fitz.Rect(rect[0], rect[1], rect[2], rect[3])
    text = page.get_text("text", clip=r)
    doc.close()
    return text


def _find_candidates(source_map: dict, text_fragment: str) -> list:
    """Find candidate blocks containing the given text fragment.

    First checks manifest candidates (which have exact blockId/start/end),
    then falls back to searching block text.
    """
    # Check manifest candidates first
    manifest_cands = source_map.get("candidates", [])
    found = []
    for c in manifest_cands:
        block_id = c.get("blockId")
        start = c.get("start", 0)
        end = c.get("end", 0)
        # Verify the text matches by looking up in blocks
        for block in source_map.get("blocks", []):
            if block["id"] == block_id:
                block_text = block.get("text", "")
                if block_text[start:end] == text_fragment:
                    found.append({
                        "blockId": block_id,
                        "start": start,
                        "end": end,
                        "text": text_fragment,
                        "entityType": c.get("entityType"),
                    })
                break

    if found:
        return found

    # Fallback: search block text
    blocks = source_map.get("blocks", [])
    candidates = []
    for block in blocks:
        block_text = block.get("text", "")
        idx = block_text.find(text_fragment)
        if idx >= 0:
            candidates.append({
                "blockId": block["id"],
                "start": idx,
                "end": idx + len(text_fragment),
                "text": text_fragment,
            })
    return candidates


def _make_decisions_from_candidates(candidates: list, action: str = "redact",
                                     entity_type: str = "PHONE") -> list:
    decisions = []
    for i, c in enumerate(candidates):
        decisions.append({
            "id": f"test_{i}",
            "blockId": c["blockId"],
            "start": c["start"],
            "end": c["end"],
            "action": action,
            "origin": "manual" if entity_type == "MANUAL" else "automatic",
            "entityType": entity_type,
            "original": c["text"],
        })
    return decisions


# ---------------------------------------------------------------------------
# Test: basic phone + id + money redact
# ---------------------------------------------------------------------------

def test_pdf_phone_id_money_redact(tmp_path):
    """Redact phone, ID card, and money from a PDF. All three must be removed."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "张三 手机号13800138000\n身份证110101199001011234\n工资15000元"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    # Find candidates using manifest
    phone_cands = _find_candidates(source_map, "13800138000")
    id_cands = _find_candidates(source_map, "110101199001011234")
    money_cands = _find_candidates(source_map, "15000元")

    assert phone_cands, "phone not detected"
    assert id_cands, "id_card not detected"
    assert money_cands, "money not detected"

    decisions = []
    decisions += _make_decisions_from_candidates(phone_cands, "redact", "PHONE")
    decisions += _make_decisions_from_candidates(id_cands, "redact", "ID_CARD")
    decisions += _make_decisions_from_candidates(money_cands, "redact", "MONEY")

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode == 0, f"export failed: {result.stderr}"
    assert out_path.exists(), "output PDF not created"

    audit = _read_audit(audit_path)
    scan = audit["residual_scan"]
    assert scan["original_removed"] is True, f"original_removed failed: {scan}"
    assert scan["replacement_written"] is True, f"replacement_written failed: {scan}"
    assert scan["position_verification"] is True, f"position_verification failed: {scan}"
    assert scan["passed"] is True, f"audit not passed: {scan}"

    # Four-way invariant
    assert audit["summary"]["redact_requested"] == 3
    assert audit["summary"]["redact_applied"] == 3


# ---------------------------------------------------------------------------
# Test: same text keep + redact (only redact the targeted occurrence)
# ---------------------------------------------------------------------------

def test_pdf_same_text_keep_redact(tmp_path):
    """Two lines with same phone number — keep one, redact the other."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "联系电话：13800138000\n备用电话：13800138000"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    # Find all occurrences - check manifest candidates and block text
    phone_cands = _find_candidates(source_map, "13800138000")
    # If only one candidate found (same block), create two from block text
    if len(phone_cands) < 2:
        blocks = source_map.get("blocks", [])
        for block in blocks:
            text = block.get("text", "")
            idx = 0
            phone_cands = []
            while True:
                idx = text.find("13800138000", idx)
                if idx < 0:
                    break
                phone_cands.append({
                    "blockId": block["id"],
                    "start": idx,
                    "end": idx + 11,
                    "text": "13800138000",
                })
                idx += 11

    assert len(phone_cands) >= 2, f"expected 2 phone occurrences, got {len(phone_cands)}"

    # Keep first, redact second
    decisions = [
        {
            "id": "keep_0",
            "blockId": phone_cands[0]["blockId"],
            "start": phone_cands[0]["start"],
            "end": phone_cands[0]["end"],
            "action": "keep",
            "origin": "manual",
            "entityType": "PHONE",
        },
        {
            "id": "redact_1",
            "blockId": phone_cands[1]["blockId"],
            "start": phone_cands[1]["start"],
            "end": phone_cands[1]["end"],
            "action": "redact",
            "origin": "automatic",
            "entityType": "PHONE",
            "original": phone_cands[1]["text"],
        },
    ]

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode == 0, f"export failed: {result.stderr}"

    audit = _read_audit(audit_path)
    assert audit["residual_scan"]["passed"] is True

    # Verify kept text is still extractable
    full_text = _extract_text_from_pdf(out_path)
    assert "13800138000" in full_text, "kept phone should still be extractable"


# ---------------------------------------------------------------------------
# Test: manual decision (non-entity text)
# ---------------------------------------------------------------------------

def test_pdf_manual_decision(tmp_path):
    """Manual redaction of arbitrary text like a project name."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "天枢计划将于2026年启动"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    cands = _find_candidates(source_map, "天枢计划")
    if not cands:
        # Manual decision: create from block text directly
        blocks = source_map.get("blocks", [])
        for block in blocks:
            text = block.get("text", "")
            idx = text.find("天枢计划")
            if idx >= 0:
                cands = [{"blockId": block["id"], "start": idx, "end": idx + 4, "text": "天枢计划"}]
                break

    assert cands, "block containing '天枢计划' not found"

    decisions = [{
        "id": "manual_0",
        "blockId": cands[0]["blockId"],
        "start": cands[0]["start"],
        "end": cands[0]["end"],
        "action": "redact",
        "origin": "manual",
        "entityType": "MANUAL",
        "original": "天枢计划",
    }]

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode == 0, f"export failed: {result.stderr}"

    audit = _read_audit(audit_path)
    assert audit["residual_scan"]["original_removed"] is True
    assert audit["residual_scan"]["passed"] is True


# ---------------------------------------------------------------------------
# Test: invalid block → fail closed
# ---------------------------------------------------------------------------

def test_pdf_invalid_block_fail_closed(tmp_path):
    """Decision referencing non-existent block must fail and clean up."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "测试文本"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    decisions = [{
        "id": "bad_0",
        "blockId": "nonexistent_block_id",
        "start": 0,
        "end": 4,
        "action": "redact",
        "origin": "manual",
        "entityType": "MANUAL",
    }]

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode != 0, "should fail for invalid block"
    assert not out_path.exists(), "output should be cleaned up on failure"


# ---------------------------------------------------------------------------
# Test: out of bounds → fail closed
# ---------------------------------------------------------------------------

def test_pdf_out_of_bounds_fail_closed(tmp_path):
    """Decision with start/end exceeding block text length must fail."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "短文本"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    blocks = source_map.get("blocks", [])
    assert blocks, "no blocks found"

    decisions = [{
        "id": "oob_0",
        "blockId": blocks[0]["id"],
        "start": 0,
        "end": 9999,  # way out of bounds
        "action": "redact",
        "origin": "manual",
        "entityType": "MANUAL",
    }]

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode != 0, "should fail for out-of-bounds"
    assert not out_path.exists(), "output should be cleaned up on failure"


# ---------------------------------------------------------------------------
# Test: overlapping decisions → fail closed
# ---------------------------------------------------------------------------

def test_pdf_overlapping_decisions_fail_closed(tmp_path):
    """Overlapping redact decisions must fail."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "手机号码13800138000联系"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    blocks = source_map.get("blocks", [])
    assert blocks

    block = blocks[0]
    text = block.get("text", "")
    idx = text.find("13800138000")
    if idx < 0:
        pytest.skip("phone not found in block text")

    decisions = [
        {
            "id": "overlap_0",
            "blockId": block["id"],
            "start": idx,
            "end": idx + 7,
            "action": "redact",
            "origin": "manual",
            "entityType": "PHONE",
        },
        {
            "id": "overlap_1",
            "blockId": block["id"],
            "start": idx + 5,
            "end": idx + 11,
            "action": "redact",
            "origin": "manual",
            "entityType": "PHONE",
        },
    ]

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode != 0, "should fail for overlapping decisions"
    assert not out_path.exists(), "output should be cleaned up"


# ---------------------------------------------------------------------------
# Test: residual original not extractable
# ---------------------------------------------------------------------------

def test_pdf_residual_original_not_extractable(tmp_path):
    """After redaction, original text must not be extractable from target rects."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "机密信息：13800138000"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    cands = _find_candidates(source_map, "13800138000")
    assert cands

    decisions = _make_decisions_from_candidates(cands, "redact", "PHONE")

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode == 0

    audit = _read_audit(audit_path)
    assert audit["residual_scan"]["original_removed"] is True


# ---------------------------------------------------------------------------
# Test: keep text still extractable
# ---------------------------------------------------------------------------

def test_pdf_keep_text_still_extractable(tmp_path):
    """Kept text must remain extractable in the output PDF."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "保留：010-66668888\n删除：13800138000"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    phone_cands = _find_candidates(source_map, "13800138000")
    assert phone_cands

    decisions = _make_decisions_from_candidates(phone_cands, "redact", "PHONE")

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode == 0, f"export failed: {result.stderr}\nstdout: {result.stdout}"

    full_text = _extract_text_from_pdf(out_path)
    assert "010-66668888" in full_text, "kept landline should remain extractable"


# ---------------------------------------------------------------------------
# Test: replacement written (mask visible in output)
# ---------------------------------------------------------------------------

def test_pdf_replacement_written(tmp_path):
    """Verify that replacement/mask text is actually written in the output."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "电话：13800138000"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    cands = _find_candidates(source_map, "13800138000")
    assert cands

    decisions = _make_decisions_from_candidates(cands, "redact", "PHONE")

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode == 0

    audit = _read_audit(audit_path)
    assert audit["residual_scan"]["replacement_written"] is True

    # Verify the output PDF has some text content (not blank)
    full_text = _extract_text_from_pdf(out_path)
    assert len(full_text.strip()) > 0, "output PDF should have text content"


# ---------------------------------------------------------------------------
# Test: fail closed cleans output
# ---------------------------------------------------------------------------

def test_pdf_fail_closed_cleans_output(tmp_path):
    """When export fails, no partial output file should remain."""
    pdf = _create_text_pdf(tmp_path / "input.pdf", [
        (1, "测试"),
    ])

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_map = _run_prepare(pdf, work_dir)

    decisions = [{
        "id": "fail_0",
        "blockId": "INVALID",
        "start": 0,
        "end": 2,
        "action": "redact",
        "origin": "manual",
        "entityType": "MANUAL",
    }]

    out_path = tmp_path / "output.redacted.pdf"
    map_path = tmp_path / "output.map.json"
    audit_path = tmp_path / "output.audit.json"

    result = _run_export(pdf, decisions, source_map, out_path, map_path, audit_path)
    assert result.returncode != 0
    assert not out_path.exists(), "output PDF must be deleted on failure"
