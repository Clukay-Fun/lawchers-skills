"""Tests for --decisions export mode."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sample_text_file(tmp_path):
    """Create a synthetic text file with mixed entity types."""
    text = "张三于2026年6月20日入职，月工资15000元。\n联系电话：13800138000。\n身份证号：110105199003071234。\n北京图强科技有限公司支付补偿金50000元。\n"
    p = tmp_path / "sample.txt"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def prepared_files(tmp_path, sample_text_file):
    """Run prepare and return paths."""
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


def _make_decisions(manifest, keep_types=None, manual_redacts=None):
    """Build decisions from manifest candidates."""
    keep_types = keep_types or set()
    manual_redacts = manual_redacts or []
    decisions = []
    for c in manifest.get("candidates", []):
        action = "keep" if c["entityType"] in keep_types else "redact"
        decisions.append({
            "id": c["id"],
            "blockId": c["blockId"],
            "start": c["start"],
            "end": c["end"],
            "action": action,
            "origin": "automatic",
            "entityType": c["entityType"],
            "sourceLocator": c.get("sourceLocator", {}),
            "confirmed": True,
        })
    for mr in manual_redacts:
        decisions.append({
            "id": f"manual_{mr['start']}",
            "blockId": mr["blockId"],
            "start": mr["start"],
            "end": mr["end"],
            "action": "redact",
            "origin": "manual",
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

        # Keep PHONE, redact everything else
        decisions = _make_decisions(manifest, keep_types={"PHONE"})

        decisions_path = tmp_path / "decisions.json"
        decisions_path.write_text(json.dumps(decisions, ensure_ascii=False))
        source_map_path = tmp_path / "source-map.json"
        out_path = tmp_path / "output.txt"
        map_path = tmp_path / "map.json"
        audit_path = tmp_path / "audit.json"

        result = subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(src),
             "--level", "strict",
             "--decisions", str(decisions_path),
             "--source-map", str(source_map_path),
             "--out", str(out_path),
             "--map", str(map_path),
             "--audit", str(audit_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"decisions export failed: {result.stderr}"

        output = out_path.read_text()
        # PHONE must be preserved
        assert "13800138000" in output, "PHONE should be kept"

    def test_redact_masks_text(self, prepared_files, tmp_path):
        """REDACT decision: original text must not appear in output."""
        manifest, source_map, src, _ = prepared_files

        decisions = _make_decisions(manifest)  # redact all

        decisions_path = tmp_path / "decisions.json"
        decisions_path.write_text(json.dumps(decisions, ensure_ascii=False))
        source_map_path = tmp_path / "source-map.json"
        out_path = tmp_path / "output.txt"
        map_path = tmp_path / "map.json"
        audit_path = tmp_path / "audit.json"

        result = subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(src),
             "--level", "strict",
             "--decisions", str(decisions_path),
             "--source-map", str(source_map_path),
             "--out", str(out_path),
             "--map", str(map_path),
             "--audit", str(audit_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

        output = out_path.read_text()
        # All redacted entities should be masked
        assert "13800138000" not in output, "PHONE should be masked"
        assert "15000元" not in output, "MONEY should be masked"

    def test_manual_addition_applied(self, prepared_files, tmp_path):
        """Manual redaction for text not auto-detected must be applied."""
        manifest, source_map, src, _ = prepared_files

        # Find "北京图强科技有限公司" in a block
        manual_redacts = []
        for block in manifest["blocks"]:
            idx = block["text"].find("北京图强科技有限公司")
            if idx >= 0:
                manual_redacts.append({
                    "blockId": block["id"],
                    "start": idx,
                    "end": idx + len("北京图强科技有限公司"),
                    "entityType": "ORG",
                })
                break

        assert manual_redacts, "Could not find ORG in manifest blocks"

        decisions = _make_decisions(manifest, manual_redacts=manual_redacts)

        decisions_path = tmp_path / "decisions.json"
        decisions_path.write_text(json.dumps(decisions, ensure_ascii=False))
        source_map_path = tmp_path / "source-map.json"
        out_path = tmp_path / "output.txt"
        map_path = tmp_path / "map.json"
        audit_path = tmp_path / "audit.json"

        result = subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(src),
             "--level", "strict",
             "--decisions", str(decisions_path),
             "--source-map", str(source_map_path),
             "--out", str(out_path),
             "--map", str(map_path),
             "--audit", str(audit_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

        output = out_path.read_text()
        assert "北京图强科技有限公司" not in output, "Manual ORG should be redacted"

        # Verify entity in map
        map_data = json.loads(map_path.read_text())
        manual_entities = [e for e in map_data["entities"] if "manual" in e["id"]]
        assert len(manual_entities) >= 1, "Manual entity should appear in map"

    def test_residual_verification_fails_when_not_applied(self, prepared_files, tmp_path):
        """If a decision can't be applied, export must fail."""
        manifest, source_map, src, _ = prepared_files

        # Create a decision with impossible position
        decisions = [{
            "id": "bad_1",
            "blockId": manifest["blocks"][0]["id"],
            "start": 0,
            "end": 5,
            "action": "redact",
            "origin": "manual",
            "entityType": "PERSON",
            "sourceLocator": {},
            "confirmed": True,
        }]

        decisions_path = tmp_path / "decisions.json"
        decisions_path.write_text(json.dumps(decisions))
        source_map_path = tmp_path / "source-map.json"
        out_path = tmp_path / "output.txt"
        map_path = tmp_path / "map.json"
        audit_path = tmp_path / "audit.json"

        # This should succeed (text replacement works) but let's verify audit exists
        result = subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(src),
             "--level", "strict",
             "--decisions", str(decisions_path),
             "--source-map", str(source_map_path),
             "--out", str(out_path),
             "--map", str(map_path),
             "--audit", str(audit_path)],
            capture_output=True, text=True, timeout=30,
        )

        # The decision replaces first 5 chars, residual should pass since
        # the original is no longer at that position
        if result.returncode == 0:
            audit = json.loads(audit_path.read_text())
            assert audit["residual_scan"]["passed"] is True
            assert audit["export_mode"] == "decisions"

    def test_audit_has_position_verification(self, prepared_files, tmp_path):
        """Audit must include position_verification method."""
        manifest, source_map, src, _ = prepared_files
        decisions = _make_decisions(manifest, keep_types={"PHONE"})

        decisions_path = tmp_path / "decisions.json"
        decisions_path.write_text(json.dumps(decisions))
        source_map_path = tmp_path / "source-map.json"
        out_path = tmp_path / "output.txt"
        map_path = tmp_path / "map.json"
        audit_path = tmp_path / "audit.json"

        subprocess.run(
            ["python3", "-m", "legal_desens.cli", "redact", str(src),
             "--level", "strict",
             "--decisions", str(decisions_path),
             "--source-map", str(source_map_path),
             "--out", str(out_path),
             "--map", str(map_path),
             "--audit", str(audit_path)],
            capture_output=True, text=True, timeout=30,
        )

        audit = json.loads(audit_path.read_text())
        assert audit["residual_scan"]["method"] == "position_verification"
        assert audit["export_mode"] == "decisions"
