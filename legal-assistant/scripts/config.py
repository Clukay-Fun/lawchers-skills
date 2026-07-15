"""config.yaml 加载与校验。

原则：路径/表标识/字段映射全部来自配置，代码零硬编码。
飞书凭据不经过本项目：lark-cli 自行管理（`lark-cli config init` / `auth login`）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, List, Optional

import yaml


class ConfigError(Exception):
    """配置缺失或非法。message 面向用户，须可操作。"""


@dataclasses.dataclass
class LarkConfig:
    bin: str
    base_token: str
    identity: str
    tables: Dict[str, str]
    push_user_id: str


@dataclasses.dataclass
class ScanConfig:
    categories: Dict[str, List[str]]
    trash_keywords: List[str]
    review_dir_name: str
    trash_dir_name: str
    ocr_command: str


@dataclasses.dataclass
class Config:
    paths: Dict[str, Path]
    lark: LarkConfig
    fields: Dict[str, Dict[str, str]]
    zip_stable_seconds: int
    scan: ScanConfig
    weekly_xlsx_dir: Optional[Path]
    source_file: Path
    # 本所全称：解析销项发票时用于排除己方、识别对方（付款方）
    firm_name: str = ""


# 必填路径键 → 用途说明（doctor 报告用）
PATH_KEYS = {
    "invoice_inbox": "发票 zip 收件箱",
    "invoice_output": "发票分类产物目录",
    "invoice_archive": "发票已处理 zip 归档",
    "output_invoice_inbox": "销项发票收件箱",
    "output_invoice_archive": "销项发票已处理归档",
    "scan_inbox": "扫描件待整理目录",
    "scan_output": "扫描件分类目标根目录",
    "state_dir": "状态台账目录",
    "journal_dir": "journal 目录",
}

TABLE_KEYS = ("reimburse", "contracts", "output_invoices")

# 每张表必须映射的内部字段名
REQUIRED_FIELDS = {
    "reimburse": ("invoice_no", "invoice_type", "amount", "payee", "invoice_date"),
    # contract_link 指向合同台账的双向关联字段；写它即建立合同↔发票关系，
    # 合同侧的「关联发票」由飞书自动反填，无需手写
    "output_invoices": ("invoice_no", "member", "contract_no", "payer", "invoice_date",
                        "amount", "contract_link"),
    "contracts": ("contract_no", "client", "invoiced"),
}


def _require(mapping: dict, key: str, where: str):
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"config 缺少 `{where}.{key}`（参考 config.example.yaml）")
    return mapping[key]


def load_config(path) -> Config:
    src = Path(path)
    if not src.exists():
        raise ConfigError(
            f"找不到配置文件 {src}。复制 config.example.yaml 为 config.yaml 并按本机路径修改。"
        )
    with open(src, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    paths_raw = raw.get("paths") or {}
    paths: Dict[str, Path] = {}
    for key in PATH_KEYS:
        paths[key] = Path(str(_require(paths_raw, key, "paths")))

    lark_raw = raw.get("lark") or {}
    tables_raw = lark_raw.get("tables") or {}
    tables = {k: str(_require(tables_raw, k, "lark.tables")) for k in TABLE_KEYS}
    push_raw = lark_raw.get("push") or {}
    lark = LarkConfig(
        bin=str(lark_raw.get("bin") or "lark-cli"),
        base_token=str(_require(lark_raw, "base_token", "lark")),
        identity=str(lark_raw.get("identity") or "user"),
        tables=tables,
        push_user_id=str(push_raw.get("user_id") or ""),
    )
    if lark.identity not in ("user", "bot"):
        raise ConfigError("`lark.identity` 只能是 user 或 bot")

    fields_raw = raw.get("fields") or {}
    fields: Dict[str, Dict[str, str]] = {}
    for table, required in REQUIRED_FIELDS.items():
        table_fields = fields_raw.get(table) or {}
        for name in required:
            _require(table_fields, name, f"fields.{table}")
        fields[table] = {k: str(v) for k, v in table_fields.items()}

    invoice_raw = raw.get("invoice") or {}
    zip_stable_seconds = int(invoice_raw.get("zip_stable_seconds", 60))

    scan_raw = raw.get("scan") or {}
    categories = scan_raw.get("categories") or {}
    if not categories:
        raise ConfigError("config 缺少 `scan.categories`（分类关键词映射）")
    scan = ScanConfig(
        categories={str(k): [str(w) for w in v] for k, v in categories.items()},
        trash_keywords=[str(w) for w in (scan_raw.get("trash_keywords") or [])],
        review_dir_name=str(scan_raw.get("review_dir_name") or "待人工复核"),
        trash_dir_name=str(scan_raw.get("trash_dir_name") or "临时垃圾箱"),
        ocr_command=str(scan_raw.get("ocr_command") or ""),
    )

    weekly_raw = raw.get("weekly") or {}
    weekly_dir = weekly_raw.get("xlsx_output_dir")
    weekly_xlsx_dir = Path(str(weekly_dir)) if weekly_dir else None

    return Config(
        firm_name=str(raw.get("firm_name") or ""),
        paths=paths,
        lark=lark,
        fields=fields,
        zip_stable_seconds=zip_stable_seconds,
        scan=scan,
        weekly_xlsx_dir=weekly_xlsx_dir,
        source_file=src,
    )
