"""Bytes-safe file I/O for .txt and .md files.

Preserves BOM, CRLF, trailing newline exactly as in the original.
.md files use the same byte-safe logic as .txt (plain text with Markdown structure).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
BOM_UTF8 = b"\xef\xbb\xbf"


@dataclass
class TextFile:
    """Represents a .txt file with its encoding metadata."""
    text: str
    raw: bytes
    has_bom: bool
    newline: str  # "\r\n" or "\n"
    has_trailing_newline: bool

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


def read_text(path: str) -> TextFile:
    """Read a .txt file preserving all byte-level characteristics."""
    raw = open(path, "rb").read()

    has_bom = raw[:3] == BOM_UTF8
    content = raw[3:] if has_bom else raw

    # Detect newline style by checking raw bytes
    has_crlf = b"\r\n" in content
    newline = "\r\n" if has_crlf else "\n"

    # Decode
    text = content.decode("utf-8")

    # Check trailing newline
    has_trailing_newline = len(text) > 0 and text[-1] == "\n"

    return TextFile(
        text=text,
        raw=raw,
        has_bom=has_bom,
        newline=newline,
        has_trailing_newline=has_trailing_newline,
    )


def write_text(path: str, text: str, meta: TextFile) -> None:
    """Write text back with the same byte-level characteristics as meta."""
    # Encode to bytes
    raw = text.encode("utf-8")

    # Prepend BOM if original had it
    if meta.has_bom:
        raw = BOM_UTF8 + raw

    with open(path, "wb") as f:
        f.write(raw)


def sha256_file(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
