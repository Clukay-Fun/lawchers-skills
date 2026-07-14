"""journal：agent 的操作记忆。按天一个 markdown 文件，只追加。

每条记录一行：`- HH:MM:SS [命令] 动作 → 结果（待办/错误摘要）`
不写入完整身份证号、联系方式等敏感信息；不同步飞书。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional


class Journal:
    def __init__(self, journal_dir: Path):
        self.dir = Path(journal_dir)

    def _today_file(self) -> Path:
        return self.dir / f"{date.today().isoformat()}.md"

    def append(self, command: str, message: str):
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._today_file()
        is_new = not path.exists()
        ts = datetime.now().strftime("%H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# journal {date.today().isoformat()}\n\n")
            f.write(f"- {ts} [{command}] {message}\n")

    def read_recent(self, days: int = 3) -> str:
        """近 N 天 journal 内容，agent 唤起时读取建立上下文。"""
        parts: List[str] = []
        for offset in range(days - 1, -1, -1):
            day = date.today() - timedelta(days=offset)
            path = self.dir / f"{day.isoformat()}.md"
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").rstrip())
        return "\n\n".join(parts)


class NullJournal(Journal):
    """dry-run 或测试用：不落盘。"""

    def __init__(self):  # noqa: super-init-not-called
        self.entries: List[str] = []

    def append(self, command: str, message: str):
        self.entries.append(f"[{command}] {message}")

    def read_recent(self, days: int = 3) -> str:
        return "\n".join(self.entries)
