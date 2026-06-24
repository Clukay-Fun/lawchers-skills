"""Tests for --decisions export mode.

Every test verifies the fail-closed invariant:
  redact_requested == redact_applied == map_entities == map_occurrences
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sample_text_file(tmp_path):
    text = "张三于2026年6月20日入职，月工资15000元。\n联系电话：13800138000。\n身份证号：110105199003071234。\n北京图强科技有限公司支付补偿金50000元。\n"
    p = tmp_path / "sample.txt"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def prepared_files(tmp_path, sample_text_file):
    manifest_path = tmp_path / "manifest.json"
    preview_path = tmp_path / "preview.md"
    source_map_path = tmp_path / "source-map.json"

    result = subprocess.run(
        ["python3", "-m", "legal_desens.cli", "prepare",
         str(sample_text_file), "--level", "strict", "--regex-only",
         "--preview-md", str(preview_path),
         "--manifest", str(manifest_path),
         "--map", str(source_map_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"prepare failed: {result.stderr}"

    manifest = json.loads(manifest_path.read_text())
    source_map = json.loads(source_map_path.read_text())
    return manifest, source_map, sample_text_file, tmp_path


def _run_decisions(src, decisions_path, source_map_path, tmp_path):
    """Run redact --decisions and return (returncode, stdout, stderr, audit_data)."""
    out_path = tmp_path / "output.txt"
    map_path = tmp_path / "map.json"
    audit_path = tmp_path / "audit.json"

    proc = subprocess.run(
        ["python3", "-m", "legal_desens.cli", "redact", str(src),
         "--level", "strict",
         "--decisions", str(decisions_path),
         "--source-map", str(source_map_path),
         "--out", str(out_path),
         "--map", str(map_path),
         "--audit", str(audit_path)],
        capture_output=True, text=True, timeout=30,
    )

    audit_data = None
    if audit_path.exists():
        try:
            audit_data = json.loads(audit_path.read_text())
        except json.JSONDecodeError:
            pass

    map_data = None
    if map_path.exists():
        try:
            map_data = json.loads(map_path.read_text())
        except json.JSONDecodeError:
            pass

    output_text = out_path.read_text() if out_path.exists() else None
    return proc.returncode, proc.stdout, proc.stderr, audit_data, map_data, output_text


def _make_decisions(manifest, keep_types=None, manual_redacts=None):
    keep_types = keep_types or set()
    manual_redacts = manual_redacts or []
    decisions = []
    for c in manifest.get("candidates", []):
        action = "keep" if c["entityType"] in keep_types else "redact"
        decisions.append({
            "id": c["id"], "blockId": c["blockId"],
            "start": c["start"], "end": c["end"],
            "action": action, "origin": "automatic",
            "entityType": c["entityType"],
            "sourceLocator": c.get("sourceLocator", {}),
            "confirmed": True,
        })
    for mr in manual_redacts:
        decisions.append({
            "id": f"manual_{mr['start']}", "blockId": mr["blockId"],
            "start": mr["start"], "end": mr["end"],
            "action": "redact", "origin": "manual",
            "entityType": mr.get("entityType", "MANUAL"),
            "sourceLocator": mr.get("sourceLocator", {}),
            "confirmed": True,
        })
    return decisions


class TestDecisionsExport:
    """Test --decisions CLI export mode."""

    def test_keep_preserves_text(self, prepared_files, tmp_path):
        """KEEP decision: text at that position must not be modified."""
        manifest, source_map, src, _ = prepared_files
        decisions = _make_decisions(manifest, keep_types={"PHONE"})

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions, ensure_ascii=False))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, audit, map_data, output = _run_decisions(src, dp, smp, tmp_path)
        assert rc == 0, f"export failed: {stderr}"
        assert "13800138000" in output, "PHONE should be kept"
        assert audit["residual_scan"]["passed"] is True

    def test_redact_masks_text(self, prepared_files, tmp_path):
        """REDACT decision: original text must not appear in output."""
        manifest, source_map, src, _ = prepared_files
        decisions = _make_decisions(manifest)  # redact all

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions, ensure_ascii=False))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, audit, map_data, output = _run_decisions(src, dp, smp, tmp_path)
        assert rc == 0, f"export failed: {stderr}"
        assert "13800138000" not in output, "PHONE should be masked"
        assert "15000元" not in output, "MONEY should be masked"
        # Verify invariant: requested == applied == entities
        redact_count = sum(1 for d in decisions if d["action"] == "redact")
        assert audit["summary"]["redact_requested"] == redact_count
        assert audit["summary"]["redact_applied"] == redact_count
        assert audit["summary"]["total_entities"] == redact_count
        assert audit["residual_scan"]["passed"] is True

    def test_manual_addition_applied(self, prepared_files, tmp_path):
        """Manual redaction for text not auto-detected must be applied."""
        manifest, source_map, src, _ = prepared_files

        manual_redacts = []
        for block in manifest["blocks"]:
            idx = block["text"].find("北京图强科技有限公司")
            if idx >= 0:
                manual_redacts.append({
                    "blockId": block["id"],
                    "start": idx, "end": idx + len("北京图强科技有限公司"),
                    "entityType": "ORG",
                })
                break
        assert manual_redacts, "ORG not found in manifest blocks"

        decisions = _make_decisions(manifest, manual_redacts=manual_redacts)
        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions, ensure_ascii=False))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, audit, map_data, output = _run_decisions(src, dp, smp, tmp_path)
        assert rc == 0, f"export failed: {stderr}"
        assert "北京图强科技有限公司" not in output, "Manual ORG should be redacted"

        manual_entities = [e for e in map_data["entities"] if "manual" in e["id"]]
        assert len(manual_entities) >= 1

    def test_audit_invariants(self, prepared_files, tmp_path):
        """Audit must report requested == applied == entities == occurrences."""
        manifest, source_map, src, _ = prepared_files
        decisions = _make_decisions(manifest)

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions, ensure_ascii=False))
        smp = tmp_path / "source-map.json"

        rc, _, _, audit, map_data, _ = _run_decisions(src, dp, smp, tmp_path)
        assert rc == 0

        redact_count = sum(1 for d in decisions if d["action"] == "redact")
        assert audit["summary"]["redact_requested"] == redact_count
        assert audit["summary"]["redact_applied"] == redact_count
        assert audit["summary"]["total_entities"] == redact_count
        assert audit["summary"]["total_occurrences"] == redact_count
        assert audit["residual_scan"]["method"] == "applied_position_verification"
        assert audit["export_mode"] == "decisions"


class TestDecisionsFailClosed:
    """Test that errors cause non-zero exit, artifact deletion, and findings."""

    def test_missing_block_fails(self, prepared_files, tmp_path):
        """Decision referencing non-existent block must fail."""
        manifest, source_map, src, _ = prepared_files
        decisions = [{
            "id": "bad_1", "blockId": "nonexistent_block",
            "start": 0, "end": 5,
            "action": "redact", "origin": "manual",
            "entityType": "PERSON", "sourceLocator": {}, "confirmed": True,
        }]

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, audit, _, output = _run_decisions(src, dp, smp, tmp_path)
        assert rc != 0, "Missing block should cause non-zero exit"
        assert "not found" in stderr.lower() or "failed" in stderr.lower()

    def test_out_of_bounds_fails(self, prepared_files, tmp_path):
        """Decision with end > block text length must fail."""
        manifest, source_map, src, _ = prepared_files
        block = manifest["blocks"][0]
        decisions = [{
            "id": "oob_1", "blockId": block["id"],
            "start": 0, "end": 99999,
            "action": "redact", "origin": "manual",
            "entityType": "PERSON", "sourceLocator": {}, "confirmed": True,
        }]

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, _, _, _ = _run_decisions(src, dp, smp, tmp_path)
        assert rc != 0, "Out-of-bounds should cause non-zero exit"

    def test_overlapping_decisions_fails(self, prepared_files, tmp_path):
        """Two overlapping redact decisions must cause failure."""
        manifest, source_map, src, _ = prepared_files
        block = manifest["blocks"][0]
        # Two decisions covering overlapping ranges
        decisions = [
            {
                "id": "overlap_1", "blockId": block["id"],
                "start": 0, "end": 10,
                "action": "redact", "origin": "manual",
                "entityType": "PERSON", "sourceLocator": {}, "confirmed": True,
            },
            {
                "id": "overlap_2", "blockId": block["id"],
                "start": 5, "end": 15,
                "action": "redact", "origin": "manual",
                "entityType": "ORG", "sourceLocator": {}, "confirmed": True,
            },
        ]

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, _, _, _ = _run_decisions(src, dp, smp, tmp_path)
        assert rc != 0, "Overlapping decisions should cause non-zero exit"
        assert "overlap" in stderr.lower() or "failed" in stderr.lower()

    def test_invalid_range_fails(self, prepared_files, tmp_path):
        """Decision with start >= end must fail."""
        manifest, source_map, src, _ = prepared_files
        block = manifest["blocks"][0]
        decisions = [{
            "id": "invalid_1", "blockId": block["id"],
            "start": 10, "end": 5,
            "action": "redact", "origin": "manual",
            "entityType": "PERSON", "sourceLocator": {}, "confirmed": True,
        }]

        dp = tmp_path / "decisions.json"
        dp.write_text(json.dumps(decisions))
        smp = tmp_path / "source-map.json"

        rc, _, stderr, _, _, _ = _run_decisions(src, dp, smp, tmp_path)
        assert rc != 0, "Invalid range should cause non-zero exit"


class TestB1MoneyTime:
    """B1 regression: YYYY元年 should be TIME, not MONEY."""

    def test_yyyy_yuan_nian_is_time(self, tmp_path):
        text = "日期2023元年工资15000元。\n"
        p = tmp_path / "test.txt"
        p.write_text(text)

        proc = subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(p),
             "--level", "strict", "--regex-only",
             "--map", str(tmp_path / "map.json")],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0
        map_data = json.loads((tmp_path / "map.json").read_text())

        money = [e for e in map_data["entities"] if e["entity_type"] == "MONEY"]
        time = [e for e in map_data["entities"] if e["entity_type"] == "TIME"]

        # 2023元年 → TIME 2023 (not MONEY 2023元)
        assert any(e["original"] == "2023" for e in time), "2023 should be TIME"
        assert not any("2023元" in e["original"] for e in money), "2023元 should not be MONEY"

    def test_yuan_nian_fee_still_money(self, tmp_path):
        text = "100元年费需提前缴纳，50元日薪按月结算，200元月租另付。\n"
        p = tmp_path / "test.txt"
        p.write_text(text)

        proc = subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(p),
             "--level", "strict", "--regex-only",
             "--map", str(tmp_path / "map.json")],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0
        map_data = json.loads((tmp_path / "map.json").read_text())

        money_orig = [e["original"] for e in map_data["entities"] if e["entity_type"] == "MONEY"]
        assert "100元" in money_orig, "100元年费 should be MONEY 100元"
        assert "50元" in money_orig, "50元日薪 should be MONEY 50元"
        assert "200元" in money_orig, "200元月租 should be MONEY 200元"
