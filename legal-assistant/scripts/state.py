"""任务状态台账：业务键 → 状态，落盘 JSON，保证幂等与可追溯。

状态机：discovered → processing → succeeded / pending_review / failed / skipped_locked
台账按业务域分文件（invoices.json / output_invoices.json / scans.json），
存于 config.paths.state_dir。写入采用「临时文件 + 原子替换」。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

DISCOVERED = "discovered"
PROCESSING = "processing"
SUCCEEDED = "succeeded"
PENDING_REVIEW = "pending_review"
FAILED = "failed"
SKIPPED_LOCKED = "skipped_locked"

VALID_STATUSES = {DISCOVERED, PROCESSING, SUCCEEDED, PENDING_REVIEW, FAILED, SKIPPED_LOCKED}


class Ledger:
    """单个业务域的状态台账。key 是业务键（发票号 / 文件名 / zip 名）。"""

    def __init__(self, state_dir: Path, domain: str):
        self.path = Path(state_dir) / f"{domain}.json"
        self._data: Dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def get(self, key: str) -> Optional[dict]:
        return self._data.get(key)

    def status(self, key: str) -> Optional[str]:
        entry = self._data.get(key)
        return entry["status"] if entry else None

    def is_done(self, key: str) -> bool:
        return self.status(key) == SUCCEEDED

    def mark(self, key: str, status: str, **detail):
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown status: {status}")
        entry = self._data.get(key, {})
        entry.update(detail)
        entry["status"] = status
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._data[key] = entry
        self._flush()

    def entries(self, status: Optional[str] = None) -> Dict[str, dict]:
        if status is None:
            return dict(self._data)
        return {k: v for k, v in self._data.items() if v.get("status") == status}

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
