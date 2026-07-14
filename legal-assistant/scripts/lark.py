"""lark-cli 适配层：唯一的飞书出口。

原则：
- 只调 lark-cli shortcut（+record-list / +record-upsert / +messages-send /
  +record-upload-attachment），不自造 HTTP 封装，不管理凭据。
- dry_run=True 时：读操作照常执行（无副作用），写操作只记录不执行。
- 所有写操作前字段已由调用方按 config.fields 映射校验。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .config import LarkConfig


class LarkError(Exception):
    """lark-cli 调用失败。带原始 stderr，供 doctor/journal 记录。"""


def field_text(value) -> str:
    """把飞书字段值归一成字符串：文本字段可能是 str 或 [{"text":…}] 段列表。"""
    if value is None:
        return ""
    if isinstance(value, list):
        return "".join(
            seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in value
        )
    if isinstance(value, dict):
        return str(value.get("text", value))
    return str(value)


def field_number(value) -> float:
    """把飞书字段值归一成数字；无法解析返回 0.0。"""
    try:
        return float(field_text(value).replace(",", "").replace("¥", "").replace("￥", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _extract(obj, key):
    """在 lark-cli 返回的 JSON 里递归找第一个 key。返回格式随版本可能有包裹层。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _extract(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract(v, key)
            if found is not None:
                return found
    return None


class LarkClient:
    def __init__(self, cfg: LarkConfig, dry_run: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run
        # dry-run 下被跳过的写操作，命令行形式，供报告
        self.skipped_writes: List[str] = []

    # ---------- 底层 ----------

    def _run(self, args: List[str], write: bool = False) -> dict:
        cmd = [self.cfg.bin] + args + ["--as", self.cfg.identity, "--format", "json"]
        if write and self.dry_run:
            self.skipped_writes.append(" ".join(cmd))
            return {"dry_run": True}
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise LarkError(
                f"lark-cli 失败（exit {proc.returncode}）: {' '.join(args[:3])}\n{proc.stderr.strip()[:2000]}"
            )
        out = proc.stdout.strip()
        if not out:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            # 某些命令输出非 JSON 提示行；保底返回原文
            return {"raw": out}

    def _table_id(self, table_key: str) -> str:
        return self.cfg.tables[table_key]

    # ---------- 读 ----------

    def record_list(
        self,
        table_key: str,
        field_names: Optional[List[str]] = None,
        filter_json: Optional[dict] = None,
    ) -> List[dict]:
        """全量拉取记录（自动翻页）。返回 [{"record_id":…, "fields": {…}}]。"""
        records: List[dict] = []
        offset = 0
        limit = 200
        while True:
            args = [
                "base", "+record-list",
                "--base-token", self.cfg.base_token,
                "--table-id", self._table_id(table_key),
                "--limit", str(limit),
                "--offset", str(offset),
            ]
            for name in field_names or []:
                args += ["--field-id", name]
            if filter_json:
                args += ["--filter-json", json.dumps(filter_json, ensure_ascii=False)]
            data = self._run(args)
            items = _extract(data, "items") or []
            for item in items:
                records.append({
                    "record_id": item.get("record_id") or item.get("id") or "",
                    "fields": item.get("fields", item),
                })
            has_more = _extract(data, "has_more")
            if not has_more or not items:
                break
            offset += limit
        return records

    def find_by_field(self, table_key: str, field_name: str, value) -> List[dict]:
        return self.record_list(
            table_key,
            filter_json={"logic": "and", "conditions": [[field_name, "==", value]]},
        )

    # ---------- 写 ----------

    def record_create(self, table_key: str, fields: Dict) -> Optional[str]:
        """创建一条记录，返回 record_id（dry-run 返回 None）。
        注意：+record-upsert 不带 --record-id 就是纯创建，不按业务键去重——
        去重由调用方先 find_by_field 完成。"""
        data = self._run([
            "base", "+record-upsert",
            "--base-token", self.cfg.base_token,
            "--table-id", self._table_id(table_key),
            "--json", json.dumps(fields, ensure_ascii=False),
        ], write=True)
        if data.get("dry_run"):
            return None
        return _extract(data, "record_id")

    def record_update(self, table_key: str, record_id: str, fields: Dict):
        self._run([
            "base", "+record-upsert",
            "--base-token", self.cfg.base_token,
            "--table-id", self._table_id(table_key),
            "--record-id", record_id,
            "--json", json.dumps(fields, ensure_ascii=False),
        ], write=True)

    def upload_attachment(self, table_key: str, record_id: str, field_name: str, file_path: Path):
        self._run([
            "base", "+record-upload-attachment",
            "--base-token", self.cfg.base_token,
            "--table-id", self._table_id(table_key),
            "--record-id", record_id,
            "--field", field_name,
            "--file", str(file_path),
        ], write=True)

    def send_markdown(self, user_id: str, markdown: str, idempotency_key: Optional[str] = None):
        args = [
            "im", "+messages-send",
            "--user-id", user_id,
            "--markdown", markdown,
        ]
        if idempotency_key:
            args += ["--idempotency-key", idempotency_key]
        self._run(args, write=True)

    # ---------- 诊断 ----------

    def check_binary(self) -> Optional[str]:
        """lark-cli 是否可用。返回 None 表示 OK，否则返回诊断信息。"""
        try:
            proc = subprocess.run(
                [self.cfg.bin, "--help"], capture_output=True, text=True, timeout=15
            )
        except FileNotFoundError:
            return f"找不到 lark-cli（配置的 bin={self.cfg.bin}）。安装：npm i -g @larksuiteoapi/lark-cli 或修正 config lark.bin 路径。"
        except subprocess.TimeoutExpired:
            return "lark-cli --help 超时。"
        if proc.returncode != 0:
            return f"lark-cli --help 退出码 {proc.returncode}：{proc.stderr.strip()[:300]}"
        return None
