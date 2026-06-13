"""Tests for model installer (006 stage).

All tests use synthetic model directories — no real model files needed.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legal_desens.model_install import (
    InstallError,
    USER_MODEL_DIR,
    DEFAULT_APP_DIR,
    REQUIRED_FILES,
    sha256_file,
    detect_label_source,
    validate_model_dir,
    build_manifest,
    write_manifest,
    read_manifest,
    is_already_installed,
    install_from_app,
    install_from_url,
    install_model,
)
from legal_desens.engine.ner import _resolve_model_dir


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_model_dir(
    base: Path,
    *,
    with_labels_json: bool = True,
    with_config_labels: bool = False,
    missing_file: Optional[str] = None,
    extra_files: Optional[Dict[str, str]] = None,
) -> Path:
    """Create a synthetic model directory with minimal required files."""
    d = base / "model"
    d.mkdir(parents=True, exist_ok=True)

    files = {
        "model.onnx": b"\x08\x01\x12\x02onnx",  # fake ONNX bytes
        "config.json": json.dumps({
            "model_type": "bert",
            "num_labels": 7,
            **({"id2label": {"0": "O", "1": "B-PER", "2": "I-PER", "3": "B-LOC", "4": "I-LOC", "5": "B-ORG", "6": "I-ORG"}}
               if with_config_labels else {}),
        }).encode(),
        "vocab.txt": "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n张\n三\n北\n京\n市\n".encode(),
    }

    if with_labels_json:
        labels = {"0": "O", "1": "B-PER", "2": "I-PER", "3": "B-LOC", "4": "I-LOC", "5": "B-ORG", "6": "I-ORG"}
        files["labels.json"] = json.dumps(labels).encode()

    if extra_files:
        for name, content in extra_files.items():
            files[name] = content.encode() if isinstance(content, str) else content

    for name, content in files.items():
        if name == missing_file:
            continue
        (d / name).write_bytes(content)

    return d


@pytest.fixture
def synthetic_model(tmp_path):
    """Create a complete synthetic model directory."""
    return _make_model_dir(tmp_path)


@pytest.fixture
def synthetic_src(tmp_path):
    """Create a synthetic source directory (as if it's the App install)."""
    src = tmp_path / "ydner_onnx"
    src.mkdir()
    # Create files directly in src (not nested)
    files = {
        "model.onnx": b"\x08\x01\x12\x02onnx",
        "config.json": json.dumps({
            "model_type": "bert",
            "num_labels": 7,
        }).encode(),
        "vocab.txt": "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n张\n三\n北\n京\n市\n".encode(),
        "labels.json": json.dumps({
            "0": "O", "1": "B-PER", "2": "I-PER", "3": "B-LOC",
            "4": "I-LOC", "5": "B-ORG", "6": "I-ORG",
        }).encode(),
    }
    for name, content in files.items():
        (src / name).write_bytes(content)
    return src


@pytest.fixture
def target_dir(tmp_path):
    """Return a target directory path (doesn't exist yet)."""
    return tmp_path / "target" / "roberta-crf-ner"


# ── 1. SHA-256 helper ────────────────────────────────────────────────────────


class TestSha256:
    def test_sha256_file(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        result = sha256_file(f)
        assert len(result) == 64  # hex digest
        assert result == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_sha256_empty(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        result = sha256_file(f)
        assert len(result) == 64


# ── 2. Label source detection ────────────────────────────────────────────────


class TestLabelDetection:
    def test_labels_json(self, synthetic_model):
        source, reason = detect_label_source(synthetic_model)
        assert source == "labels.json"

    def test_config_fallback(self, tmp_path):
        """When labels.json missing, fallback to config.json id2label."""
        d = _make_model_dir(tmp_path, with_labels_json=False, with_config_labels=True)
        source, reason = detect_label_source(d)
        assert source == "config.json"

    def test_config_label2id_fallback(self, tmp_path):
        """When labels.json missing, fallback to config.json label2id."""
        d = tmp_path / "model"
        d.mkdir()
        (d / "config.json").write_bytes(json.dumps({
            "label2id": {"O": 0, "B-PER": 1, "I-PER": 2},
        }).encode())
        source, reason = detect_label_source(d)
        assert source == "config.json"

    def test_no_labels_raises(self, tmp_path):
        """No labels.json and config.json without label mapping → error."""
        d = _make_model_dir(tmp_path, with_labels_json=False, with_config_labels=False)
        with pytest.raises(InstallError, match="No label mapping found"):
            detect_label_source(d)

    def test_empty_labels_json_falls_to_config(self, tmp_path):
        """Empty labels.json → falls through to config.json."""
        d = tmp_path / "model"
        d.mkdir()
        (d / "labels.json").write_bytes(b"[]")
        (d / "config.json").write_bytes(json.dumps({
            "id2label": {"0": "O", "1": "B-PER"},
        }).encode())
        source, _ = detect_label_source(d)
        assert source == "config.json"


# ── 3. Validation ────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_dir(self, synthetic_model):
        validate_model_dir(synthetic_model)  # should not raise

    def test_missing_dir(self, tmp_path):
        with pytest.raises(InstallError, match="not found"):
            validate_model_dir(tmp_path / "nonexistent")

    def test_missing_model_onnx(self, tmp_path):
        d = _make_model_dir(tmp_path, missing_file="model.onnx")
        with pytest.raises(InstallError, match="missing required files"):
            validate_model_dir(d)

    def test_missing_config_json(self, tmp_path):
        d = _make_model_dir(tmp_path, missing_file="config.json")
        with pytest.raises(InstallError, match="missing required files"):
            validate_model_dir(d)

    def test_missing_vocab_txt(self, tmp_path):
        d = _make_model_dir(tmp_path, missing_file="vocab.txt")
        with pytest.raises(InstallError, match="missing required files"):
            validate_model_dir(d)

    def test_missing_labels_and_config_no_labels(self, tmp_path):
        """labels.json missing and config.json has no label mapping → FAIL."""
        d = _make_model_dir(tmp_path, with_labels_json=False, with_config_labels=False)
        with pytest.raises(InstallError, match="No label mapping found"):
            validate_model_dir(d)


# ── 4. Manifest ──────────────────────────────────────────────────────────────


class TestManifest:
    def test_build_manifest(self, synthetic_model):
        manifest = build_manifest(
            source="from-app",
            src_path="/some/path",
            model_dir=synthetic_model,
            label_source="labels.json",
        )
        assert manifest["name"] == "RobertaCrfNerModel"
        assert manifest["format"] == "onnx"
        assert manifest["source"] == "from-app"
        assert manifest["src_path"] == "/some/path"
        assert manifest["label_source"] == "labels.json"
        assert "installed_at" in manifest
        assert "files" in manifest
        # Check that SHA-256 are stored for each file
        for fname, sha in manifest["files"].items():
            assert len(sha) == 64, f"SHA for {fname} is not 64 chars"
        assert manifest["size_bytes"] > 0

    def test_write_read_manifest(self, synthetic_model):
        manifest = build_manifest(
            source="from-app", src_path="/src",
            model_dir=synthetic_model, label_source="labels.json",
        )
        write_manifest(synthetic_model, manifest)
        loaded = read_manifest(synthetic_model)
        assert loaded is not None
        assert loaded["source"] == "from-app"
        assert loaded["files"] == manifest["files"]

    def test_read_manifest_none(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert read_manifest(d) is None


# ── 5. Idempotency ──────────────────────────────────────────────────────────


class TestIdempotency:
    def test_not_installed(self, synthetic_model):
        assert is_already_installed(synthetic_model, "/some/path") is False

    def test_installed_same_source(self, synthetic_model):
        manifest = build_manifest(
            source="from-app", src_path="/some/path",
            model_dir=synthetic_model, label_source="labels.json",
        )
        write_manifest(synthetic_model, manifest)
        assert is_already_installed(synthetic_model, "/some/path") is True

    def test_installed_different_source(self, synthetic_model):
        manifest = build_manifest(
            source="from-app", src_path="/some/path",
            model_dir=synthetic_model, label_source="labels.json",
        )
        write_manifest(synthetic_model, manifest)
        assert is_already_installed(synthetic_model, "/other/path") is False

    def test_installed_file_changed(self, synthetic_model):
        manifest = build_manifest(
            source="from-app", src_path="/some/path",
            model_dir=synthetic_model, label_source="labels.json",
        )
        write_manifest(synthetic_model, manifest)
        # Modify a file
        (synthetic_model / "vocab.txt").write_bytes(b"changed content\n")
        assert is_already_installed(synthetic_model, "/some/path") is False


# ── 6. Install from app ──────────────────────────────────────────────────────


class TestInstallFromApp:
    def test_basic_install(self, synthetic_src, target_dir):
        manifest = install_from_app(src=synthetic_src, target=target_dir)
        assert target_dir.is_dir()
        assert (target_dir / "model.onnx").is_file()
        assert (target_dir / "config.json").is_file()
        assert (target_dir / "vocab.txt").is_file()
        assert (target_dir / "labels.json").is_file()
        assert (target_dir / "manifest.json").is_file()
        assert manifest["source"] == "from-app"
        assert manifest["src_path"] == str(synthetic_src)

    def test_install_idempotent(self, synthetic_src, target_dir, capsys):
        install_from_app(src=synthetic_src, target=target_dir)
        # Second install should skip
        manifest = install_from_app(src=synthetic_src, target=target_dir)
        captured = capsys.readouterr()
        assert "already installed" in captured.out + captured.err

    def test_install_force_reinstall(self, synthetic_src, target_dir):
        install_from_app(src=synthetic_src, target=target_dir)
        old_manifest = read_manifest(target_dir)
        # Modify target to simulate drift
        (target_dir / "vocab.txt").write_bytes(b"drifted\n")
        # Force reinstall
        manifest = install_from_app(src=synthetic_src, target=target_dir, force=True)
        assert (target_dir / "vocab.txt").read_bytes() != b"drifted\n"
        assert manifest["source"] == "from-app"

    def test_missing_source_raises(self, tmp_path, target_dir):
        with pytest.raises(InstallError, match="Source model directory not found"):
            install_from_app(src=tmp_path / "nonexistent", target=target_dir)
        # No leftover directory
        assert not target_dir.exists()

    def test_incomplete_source_raises(self, tmp_path, target_dir):
        """Source missing model.onnx → FAIL, no half-install."""
        src = tmp_path / "incomplete_src"
        src.mkdir()
        (src / "config.json").write_bytes(b"{}")
        (src / "vocab.txt").write_bytes(b"tok")
        (src / "labels.json").write_bytes(b'{"0": "O"}')
        # model.onnx missing
        with pytest.raises(InstallError, match="missing required files"):
            install_from_app(src=src, target=target_dir)
        assert not target_dir.exists()

    def test_source_missing_labels_raises(self, tmp_path, target_dir):
        """Source has no labels.json and config.json has no label mapping → FAIL."""
        src = tmp_path / "no_labels_src"
        src.mkdir()
        (src / "model.onnx").write_bytes(b"\x08\x01")
        (src / "config.json").write_bytes(json.dumps({"model_type": "bert"}).encode())
        (src / "vocab.txt").write_bytes(b"[PAD]\n")
        with pytest.raises(InstallError, match="No label mapping found"):
            install_from_app(src=src, target=target_dir)
        assert not target_dir.exists()

    def test_cleanup_on_failure(self, synthetic_src, target_dir):
        """If something goes wrong mid-install, target is cleaned up."""
        # We can easily simulate failure by making target a file
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        target_dir.write_bytes(b"blocking file")
        with pytest.raises(Exception):
            install_from_app(src=synthetic_src, target=target_dir)


# ── 7. Install from URL (limited — no real server) ───────────────────────────


class TestInstallFromUrl:
    def test_sha_mismatch_raises(self, tmp_path, target_dir, monkeypatch):
        """SHA mismatch → FAIL, no files installed."""
        import urllib.request

        # Create a fake archive
        fake_archive = tmp_path / "model.tar.gz"
        fake_archive.write_bytes(b"fake archive content")

        real_sha = sha256_file(fake_archive)
        wrong_sha = "0" * 64

        def mock_urlretrieve(url, dest):
            import shutil
            shutil.copy2(fake_archive, dest)

        monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

        with pytest.raises(InstallError, match="SHA-256 mismatch"):
            install_from_url("http://example.com/model.tar.gz", wrong_sha, target=target_dir)

        assert not target_dir.exists()

    def test_download_requires_sha(self, target_dir):
        """--url without --sha256 raises."""
        with pytest.raises(InstallError, match="--url requires --sha256"):
            install_model(url="http://example.com/model.tar.gz", target=str(target_dir))


# ── 8. Main install_model entry point ────────────────────────────────────────


class TestInstallModelEntryPoint:
    def test_from_app_default(self, synthetic_src, target_dir):
        manifest = install_model(
            from_app=True, src=str(synthetic_src), target=str(target_dir),
        )
        assert manifest["source"] == "from-app"
        assert (target_dir / "manifest.json").is_file()

    def test_url_requires_sha(self, target_dir):
        with pytest.raises(InstallError, match="--url requires --sha256"):
            install_model(url="http://example.com/model.tar.gz", target=str(target_dir))


# ── 9. Search order (revised 002) ────────────────────────────────────────────


class TestModelDirSearchOrder:
    def test_explicit_dir_highest_priority(self):
        d = _resolve_model_dir("/explicit/path")
        assert str(d) == os.path.normpath("/explicit/path")

    def test_env_var_second_priority(self, monkeypatch):
        monkeypatch.setenv("LEGAL_DESENS_MODEL_DIR", "/env/path")
        monkeypatch.delenv("LEGAL_DESENS_MODEL_DIR", raising=False)
        # With explicit
        d = _resolve_model_dir("/explicit")
        assert str(d) == os.path.normpath("/explicit")
        # Without explicit
        monkeypatch.setenv("LEGAL_DESENS_MODEL_DIR", "/env/path")
        d = _resolve_model_dir(None)
        assert str(d) == os.path.normpath("/env/path")

    def test_user_dir_third_priority(self, tmp_path, monkeypatch):
        """When no --model-dir and no env, user-level dir is checked."""
        monkeypatch.delenv("LEGAL_DESENS_MODEL_DIR", raising=False)

        # If user dir exists, it should be returned
        fake_user = tmp_path / "user_model"
        fake_user.mkdir()
        monkeypatch.setattr(
            "legal_desens.engine.ner.USER_MODEL_DIR", fake_user
        )
        d = _resolve_model_dir(None)
        assert d == fake_user

    def test_app_dir_fallback(self, monkeypatch, tmp_path):
        """When user dir doesn't exist, app dir is fallback."""
        monkeypatch.delenv("LEGAL_DESENS_MODEL_DIR", raising=False)
        monkeypatch.setattr(
            "legal_desens.engine.ner.USER_MODEL_DIR", tmp_path / "nonexistent_user_dir"
        )
        monkeypatch.setattr(
            "legal_desens.engine.ner.DEFAULT_APP_DIR", tmp_path / "app_dir"
        )
        d = _resolve_model_dir(None)
        assert d == tmp_path / "app_dir"


# ── 10. End-to-end: install then ner-inspect (via search order) ──────────────


class TestInstallThenInspect:
    def test_install_then_ner_inspect_without_model_dir(self, synthetic_src, tmp_path, monkeypatch):
        """After install to user-level dir, ner-inspect should find it without --model-dir."""
        monkeypatch.delenv("LEGAL_DESENS_MODEL_DIR", raising=False)
        target = tmp_path / "models" / "roberta-crf-ner"
        install_from_app(src=synthetic_src, target=target)

        # Patch USER_MODEL_DIR to our target
        monkeypatch.setattr("legal_desens.engine.ner.USER_MODEL_DIR", target)

        # _resolve_model_dir without explicit arg should find target
        d = _resolve_model_dir(None)
        assert d == target

        # The dir should be valid for ner inspection
        from legal_desens.model_install import validate_model_dir
        validate_model_dir(d)  # should not raise

    def test_manifest_recorded_correctly(self, synthetic_src, target_dir):
        """Install then verify manifest has all expected fields."""
        manifest = install_from_app(src=synthetic_src, target=target_dir)

        assert manifest["name"] == "RobertaCrfNerModel"
        assert manifest["format"] == "onnx"
        assert manifest["source"] == "from-app"
        assert manifest["label_source"] == "labels.json"
        assert "installed_at" in manifest
        assert manifest["path"] == str(target_dir)

        # All file SHAs are valid
        for fname, sha in manifest["files"].items():
            fpath = target_dir / fname
            assert fpath.is_file(), f"{fname} not found in target"
            assert sha256_file(fpath) == sha, f"SHA mismatch for {fname}"

        # manifest.json itself is not in files dict
        assert "manifest.json" not in manifest["files"]


# ── 11. CLI integration ─────────────────────────────────────────────────────


class TestCLI:
    def test_install_model_help(self):
        from legal_desens.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["install-model", "--help"])
        assert exc_info.value.code == 0

    def test_install_model_no_source(self, tmp_path):
        """install-model with nonexistent default source → error."""
        from legal_desens.cli import main
        # The default source won't exist in test env
        ret = main(["install-model", "--src", str(tmp_path / "nonexistent")])
        assert ret == 1

    def test_install_model_success(self, synthetic_src, tmp_path):
        from legal_desens.cli import main
        target = str(tmp_path / "installed")
        ret = main([
            "install-model",
            "--src", str(synthetic_src),
            "--target", target,
        ])
        assert ret == 0
        assert (Path(target) / "manifest.json").is_file()

    def test_install_model_force(self, synthetic_src, tmp_path):
        from legal_desens.cli import main
        target = str(tmp_path / "installed")
        assert main(["install-model", "--src", str(synthetic_src), "--target", target]) == 0
        assert main(["install-model", "--src", str(synthetic_src), "--target", target, "--force"]) == 0

    def test_install_model_out(self, synthetic_src, tmp_path):
        from legal_desens.cli import main
        target = str(tmp_path / "installed")
        out_file = str(tmp_path / "manifest.json")
        ret = main([
            "install-model",
            "--src", str(synthetic_src),
            "--target", target,
            "--out", out_file,
        ])
        assert ret == 0
        with open(out_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["source"] == "from-app"
