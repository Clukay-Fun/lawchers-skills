"""扫描件归档：文件名语义优先 → 首页文本 → 外部 OCR → 待人工复核兜底。

安全动作（照搬用户已验证的方案）：
- 移动前写锁检测，占用文件静默跳过（skipped_locked），下一轮继续；
- 目标重名追加 _1/_2，绝不覆盖；
- 无法判定 → 待人工复核；test/copy/副本等 → 临时垃圾箱；
- 全程无弹窗，仅结构化日志 + journal。
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from typing import List, Optional

from .config import Config, ScanConfig
from .fsops import is_file_locked, safe_move
from .journal import Journal
from .state import SKIPPED_LOCKED, SUCCEEDED, Ledger

# 归档目标目录本身 & 隐藏文件不参与整理
DOC_SUFFIXES = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


@dataclasses.dataclass
class ScanResult:
    moved: List[str] = dataclasses.field(default_factory=list)
    review: List[str] = dataclasses.field(default_factory=list)
    trash: List[str] = dataclasses.field(default_factory=list)
    locked: List[str] = dataclasses.field(default_factory=list)


def classify_text(text: str, scan: ScanConfig) -> Optional[str]:
    """按分类关键词匹配文本（文件名或正文），命中返回分类名。"""
    if not text:
        return None
    lowered = text.lower()
    for category, keywords in scan.categories.items():
        for kw in keywords:
            if kw.lower() in lowered:
                return category
    return None


def is_trash(name: str, scan: ScanConfig) -> bool:
    lowered = name.lower()
    return any(kw.lower() in lowered for kw in scan.trash_keywords)


def _first_page_text(path: Path) -> str:
    """PDF 首页文本层（需 [pdf] extra；缺失时返回空串走 OCR/复核）。"""
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    try:
        with fitz.open(str(path)) as doc:
            if doc.page_count == 0:
                return ""
            return doc[0].get_text() or ""
    except Exception:
        return ""


def _ocr_text(path: Path, scan: ScanConfig) -> str:
    """外部 OCR 命令 hook：`scan.ocr_command` 中 {file} 替换为文件路径，
    命令向 stdout 输出识别文本。Windows 上接 PaddleOCR-VL。留空则跳过。"""
    if not scan.ocr_command:
        return ""
    cmd = scan.ocr_command.replace("{file}", str(path))
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


def classify_file(path: Path, scan: ScanConfig) -> str:
    """三重过滤：垃圾名 → 文件名语义 → 首页文本/OCR → 待人工复核。"""
    if is_trash(path.name, scan):
        return scan.trash_dir_name
    by_name = classify_text(path.stem, scan)
    if by_name:
        return by_name
    text = _first_page_text(path)
    if not text.strip():
        text = _ocr_text(path, scan)
    by_content = classify_text(text, scan)
    if by_content:
        return by_content
    return scan.review_dir_name


def run_scan_once(cfg: Config, journal: Journal, dry_run: bool = False) -> ScanResult:
    result = ScanResult()
    inbox = cfg.paths["scan_inbox"]
    out_root = cfg.paths["scan_output"]
    scan = cfg.scan
    ledger = Ledger(cfg.paths["state_dir"], "scans")
    # 目标分类目录名集合：已在这些目录里的文件不再动
    target_dirs = set(scan.categories) | {scan.review_dir_name, scan.trash_dir_name}

    if not inbox.exists():
        journal.append("scan-once", f"扫描目录不存在：{inbox}")
        return result

    for path in sorted(inbox.iterdir()):
        if path.name.startswith(".") or path.name.startswith("~"):
            continue
        if path.is_dir():
            if path.name in target_dirs:
                continue
            # 子文件夹视为一个整体扫描件包，按名分类移动
            category = classify_text(path.name, scan) or (
                scan.trash_dir_name if is_trash(path.name, scan) else scan.review_dir_name
            )
        elif path.suffix.lower() in DOC_SUFFIXES:
            if is_file_locked(path):
                ledger.mark(path.name, SKIPPED_LOCKED)
                result.locked.append(path.name)
                continue
            category = classify_file(path, scan)
        else:
            continue

        target = safe_move(path, out_root / category, dry_run=dry_run)
        if not dry_run:
            ledger.mark(path.name, SUCCEEDED, category=category, target=str(target))
        if category == scan.review_dir_name:
            result.review.append(path.name)
        elif category == scan.trash_dir_name:
            result.trash.append(path.name)
        else:
            result.moved.append(f"{path.name} → {category}")

    journal.append(
        "scan-once",
        f"归档 {len(result.moved)}，复核 {len(result.review)}，垃圾 {len(result.trash)}，"
        f"占用跳过 {len(result.locked)}" + ("（dry-run）" if dry_run else ""),
    )
    return result
