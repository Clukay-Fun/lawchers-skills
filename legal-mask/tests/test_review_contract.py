"""CLI review boundary tests using synthetic, locally generated material."""

import hashlib
import json

import pytest

from legal_desens.cli import main


@pytest.fixture
def review_files(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("电话：13800138000\n保留说明", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    source_map = tmp_path / "source-map.json"
    assert main([
        "prepare", str(source), "--profile", "labor", "--regex-only",
        "--manifest", str(manifest), "--map", str(source_map),
    ]) == 0
    candidate = next(
        c for c in json.loads(manifest.read_text())["candidates"]
        if c["entityType"] == "PHONE"
    )
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([{**candidate, "action": "redact"}]))
    out = tmp_path / "output.txt"
    map_path = tmp_path / "output.map.json"
    audit = tmp_path / "audit.json"
    args = [
        "redact", str(source), "--decisions", str(decisions),
        "--source-map", str(source_map), "--out", str(out),
        "--map", str(map_path), "--audit", str(audit),
    ]
    return source, source_map, decisions, out, map_path, audit, args


def test_prepare_review_export_roundtrip(review_files, tmp_path):
    source, _, _, out, map_path, audit, args = review_files
    assert main(args) == 0
    assert "138****8000" in out.read_text()
    assert "保留说明" in out.read_text()
    result = json.loads(audit.read_text())
    assert result["summary"]["redact_applied"] == 1
    assert result["residual_scan"]["passed"] is True
    restored = tmp_path / "restored.txt"
    assert main(["restore", str(out), "--map", str(map_path), "--out", str(restored)]) == 0
    assert restored.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("payload", [
    {"action": "redact"}, ["redact"], [{"action": "replace"}], [{}],
])
def test_invalid_decisions_fail_before_writing(review_files, payload, capsys):
    _, _, decisions, out, map_path, audit, args = review_files
    decisions.write_text(json.dumps(payload))
    assert main(args) == 1
    assert "Error loading decisions" in capsys.readouterr().err
    assert not any(p.exists() for p in (out, map_path, audit))


@pytest.mark.parametrize("change", ["source", "missing_hash", "wrong_hash", "not_object"])
def test_stale_or_invalid_source_map_preserves_existing_output(review_files, change, capsys):
    source, source_map, _, out, map_path, audit, args = review_files
    data = json.loads(source_map.read_text())
    if change == "source":
        # Same-length change: offsets remain plausible, but review is stale.
        source.write_text(source.read_text().replace("13800138000", "13900139000"))
    elif change == "missing_hash":
        data.pop("source_sha256")
    elif change == "wrong_hash":
        data["source_sha256"] = hashlib.sha256(b"other document").hexdigest()
    else:
        data = []
    source_map.write_text(json.dumps(data))
    out.write_bytes(b"previous successful export")
    assert main(args) == 1
    assert "Error:" in capsys.readouterr().err
    assert out.read_bytes() == b"previous successful export"
    assert not map_path.exists()
    assert not audit.exists()
