"""Model installer: acquire and validate NER model into user-level directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────────────────

USER_MODEL_DIR = Path.home() / ".legal-desens" / "models" / "roberta-crf-ner"
DEFAULT_APP_DIR = Path("/Applications/Desensitization/ydner_onnx")

REQUIRED_FILES = ["model.onnx", "config.json", "vocab.txt"]
# labels.json is required OR config.json must contain id2label/label2id


class InstallError(Exception):
    """Raised when model installation fails."""


# ── SHA-256 helpers ──────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── Label source detection ───────────────────────────────────────────────────


def detect_label_source(model_dir: Path) -> Tuple[str, str]:
    """Detect label source and return (source_name, reason).

    Checks labels.json first, then config.json.
    Raises InstallError if neither provides a valid label mapping.
    """
    labels_path = model_dir / "labels.json"
    if labels_path.is_file():
        try:
            with open(labels_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, (list, dict)) and len(raw) > 0:
                return "labels.json", "labels.json exists and is non-empty"
        except (json.JSONDecodeError, OSError):
            pass

    config_path = model_dir / "config.json"
    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "id2label" in config and len(config["id2label"]) > 0:
                return "config.json", "config.json contains id2label"
            if "label2id" in config and len(config["label2id"]) > 0:
                return "config.json", "config.json contains label2id"
        except (json.JSONDecodeError, OSError):
            pass

    raise InstallError(
        f"No label mapping found in '{model_dir}'. "
        "Expected labels.json or config.json with id2label/label2id."
    )


# ── Validation ───────────────────────────────────────────────────────────────


def validate_model_dir(model_dir: Path) -> None:
    """Validate that a model directory has all required files and label mapping.

    Raises InstallError on failure.
    """
    if not model_dir.is_dir():
        raise InstallError(f"Model directory not found: {model_dir}")

    missing = [f for f in REQUIRED_FILES if not (model_dir / f).is_file()]
    if missing:
        raise InstallError(
            f"Model directory '{model_dir}' is missing required files: {missing}. "
            f"Required: {REQUIRED_FILES} + label mapping (labels.json or config.json)."
        )

    # Label source detection will raise if not found
    detect_label_source(model_dir)


# ── Manifest ─────────────────────────────────────────────────────────────────


def build_manifest(
    source: str,
    src_path: str,
    model_dir: Path,
    label_source: str,
) -> dict:
    """Build manifest.json content for an installed model."""
    files: Dict[str, str] = {}
    total_size = 0
    for item in sorted(model_dir.iterdir()):
        if item.is_file() and item.name != "manifest.json":
            files[item.name] = sha256_file(item)
            total_size += item.stat().st_size

    return {
        "name": "RobertaCrfNerModel",
        "format": "onnx",
        "source": source,
        "src_path": src_path,
        "size_bytes": total_size,
        "files": files,
        "label_source": label_source,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "path": str(model_dir),
    }


def write_manifest(model_dir: Path, manifest: dict) -> None:
    """Write manifest.json to model directory."""
    manifest_path = model_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def read_manifest(model_dir: Path) -> Optional[dict]:
    """Read manifest.json if it exists, else None."""
    manifest_path = model_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Idempotency check ───────────────────────────────────────────────────────


def is_already_installed(model_dir: Path, src_path: str) -> bool:
    """Check if model is already installed with matching SHA from same source.

    Returns True if all file SHAs in manifest match current files.
    """
    manifest = read_manifest(model_dir)
    if manifest is None:
        return False

    if manifest.get("src_path") != src_path:
        return False

    stored_files = manifest.get("files", {})
    for fname, stored_sha in stored_files.items():
        fpath = model_dir / fname
        if not fpath.is_file():
            return False
        if sha256_file(fpath) != stored_sha:
            return False

    return True


# ── Install from app (--from-app) ────────────────────────────────────────────


def install_from_app(
    src: Path = DEFAULT_APP_DIR,
    force: bool = False,
    target: Path = USER_MODEL_DIR,
) -> dict:
    """Install model from local App directory.

    Args:
        src: Source model directory (default: /Applications/Desensitization/ydner_onnx)
        force: If True, overwrite existing installation
        target: Target installation directory

    Returns:
        manifest dict

    Raises:
        InstallError on any failure
    """
    if not src.is_dir():
        raise InstallError(
            f"Source model directory not found: {src}. "
            "Use --src to specify a different source path."
        )

    # Validate source has all required files
    missing_src = [f for f in REQUIRED_FILES if not (src / f).is_file()]
    if missing_src:
        raise InstallError(
            f"Source directory '{src}' is missing required files: {missing_src}."
        )

    # Detect label source in source directory
    label_source, _ = detect_label_source(src)

    # Idempotency check
    if not force and target.is_dir() and is_already_installed(target, str(src)):
        manifest = read_manifest(target)
        print(f"Model already installed at {target} (SHA-256 match). Use --force to reinstall.")
        return manifest

    # Clean target if exists (partial install or --force)
    if target.exists():
        shutil.rmtree(target)

    # Copy files
    target.mkdir(parents=True, exist_ok=True)
    try:
        for item in src.iterdir():
            if item.is_file():
                shutil.copy2(item, target / item.name)

        # Build and write manifest
        manifest = build_manifest(
            source="from-app",
            src_path=str(src),
            model_dir=target,
            label_source=label_source,
        )
        write_manifest(target, manifest)
        return manifest

    except Exception:
        # Clean up on failure
        if target.exists():
            shutil.rmtree(target)
        raise


# ── Install from URL (--url) ─────────────────────────────────────────────────


def _safe_extract_zip(zf: "zipfile.ZipFile", dest: Path) -> None:
    """Extract ZIP members safely, rejecting path traversal."""
    for member in zf.infolist():
        # Resolve the target path and verify it stays within dest
        member_path = (dest / member.filename).resolve()
        if not member_path.is_relative_to(dest.resolve()):
            raise InstallError(
                f"Unsafe ZIP entry: '{member.filename}' would extract outside target directory."
            )
        zf.extract(member, dest)


def install_from_url(
    url: str,
    sha256: str,
    force: bool = False,
    target: Path = USER_MODEL_DIR,
) -> dict:
    """Install model by downloading from URL and verifying SHA-256.

    Downloads to a temp file, verifies SHA-256, extracts to a staging
    directory, validates, then atomically replaces target only on success.
    Previous valid installation is preserved if validation fails.

    Raises InstallError on SHA mismatch or any failure.
    """
    # Idempotency check (SHA-based, not source-path-based for URL installs)
    if not force and target.is_dir():
        manifest = read_manifest(target)
        if manifest and manifest.get("source") == "url":
            stored_sha = manifest.get("download_sha256")
            if stored_sha == sha256:
                print(f"Model already installed at {target} (download SHA-256 match). Use --force to reinstall.")
                return manifest

    # Download
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".download")
    os.close(tmp_fd)
    staging: Optional[Path] = None
    try:
        print(f"Downloading model from {url}...")
        urllib.request.urlretrieve(url, tmp_path)

        # Verify SHA-256
        actual_sha = sha256_file(Path(tmp_path))
        if actual_sha != sha256:
            raise InstallError(
                f"SHA-256 mismatch: expected {sha256[:16]}..., got {actual_sha[:16]}... . "
                "Download aborted, no files installed."
            )

        # Extract to staging directory (sibling of target) for safe validation
        staging = target.parent / (target.name + ".staging")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        import tarfile
        import zipfile

        if tarfile.is_tarfile(tmp_path):
            with tarfile.open(tmp_path) as tf:
                tf.extractall(staging, filter="data")
        elif zipfile.is_zipfile(tmp_path):
            with zipfile.ZipFile(tmp_path) as zf:
                _safe_extract_zip(zf, staging)
        else:
            raise InstallError(
                "Downloaded file is not a recognized archive (tar.gz or zip)."
            )

        # Validate extracted contents in staging
        validate_model_dir(staging)
        label_source, _ = detect_label_source(staging)

        # Build manifest in staging, then fix path to final target before writing
        manifest = build_manifest(
            source="url",
            src_path=url,
            model_dir=staging,
            label_source=label_source,
        )
        manifest["download_sha256"] = sha256
        manifest["path"] = str(target)
        write_manifest(staging, manifest)

        # Atomic replace: remove old target, rename staging → target
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        staging = None  # staging consumed, don't clean in finally

        return manifest

    except InstallError:
        raise
    except Exception as e:
        raise InstallError(f"Download/install failed: {e}") from e
    finally:
        # Clean staging on failure (staging is None if consumed by rename)
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        # Always clean temp download file
        p = Path(tmp_path)
        if p.exists():
            p.unlink()


# ── Main entry point for CLI ─────────────────────────────────────────────────


def install_model(
    from_app: bool = False,
    src: Optional[str] = None,
    url: Optional[str] = None,
    sha256: Optional[str] = None,
    force: bool = False,
    target: Optional[str] = None,
) -> dict:
    """Main entry point for model installation.

    Returns manifest dict on success.
    Raises InstallError on failure.
    """
    target_dir = Path(target) if target else USER_MODEL_DIR

    if url:
        if not sha256:
            raise InstallError("--url requires --sha256 for integrity verification.")
        return install_from_url(url, sha256, force=force, target=target_dir)
    else:
        # Default: --from-app
        src_dir = Path(src) if src else DEFAULT_APP_DIR
        return install_from_app(src_dir, force=force, target=target_dir)
