"""共享文件操作：写锁检测、防覆盖移动。invoices 与 scans 共用。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def is_file_locked(path: Path) -> bool:
    """文件是否被其他进程占用（WPS/Word/PDF 阅读器打开）。

    Windows 上被占用的文件无法以追加写打开或改名；
    macOS/Linux 一般不会锁，此函数几乎总是 False（测试环境即如此）。
    """
    path = Path(path)
    try:
        # 尝试以追加模式打开（不改内容）
        with open(path, "a"):
            pass
        # Windows 下重命名到自身也会被占用挡住
        os.rename(path, path)
        return False
    except (OSError, PermissionError):
        return True


def unique_target(target: Path) -> Path:
    """目标已存在时追加 _1/_2… 后缀，绝不覆盖。"""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 1
    while True:
        candidate = target.with_name(f"{stem}_{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def safe_move(src: Path, dest_dir: Path, dry_run: bool = False) -> Path:
    """把 src 移到 dest_dir 下，重名自动加后缀。返回最终目标路径。"""
    src = Path(src)
    dest_dir = Path(dest_dir)
    target = unique_target(dest_dir / src.name)
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
    return target


def safe_copy(src: Path, target: Path, dry_run: bool = False) -> Path:
    """把 src 复制为 target（可改名），重名自动加后缀。返回最终目标路径。"""
    src = Path(src)
    target = unique_target(Path(target))
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(target))
    return target
