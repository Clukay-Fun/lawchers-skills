"""进项发票贴票。

zip（QQ 邮箱发票导出）→ 解压 → 解析发票统计 xlsx → 按「收款方+金额+日期」
匹配 PDF → 按发票类型归档到 发票整理/YYYY-MM-DD/<类型>/ → 写发票报销台账
（发票号去重）→ zip 移入已处理。

幂等：
- zip 级：台账 domain=invoices，key=zip 文件名。
- 行级：key=发票号；写飞书前先全量拉取远端发票号集合去重。
"""

from __future__ import annotations

import dataclasses
import re
import tempfile
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

from .config import Config
from .fsops import safe_copy, safe_move
from .journal import Journal
from .lark import LarkClient
from .state import FAILED, PROCESSING, SUCCEEDED, Ledger

# QQ 导出 xlsx 的表头（按名取列，不依赖顺序）
COL_TYPE = "发票类型"
COL_DATE = "开票日期"
COL_NO = "发票号码"
COL_PAYEE = "收款方"
COL_AMOUNT = "金额"

PDF_NAME_RE = re.compile(r"^(\d{6})_([\d.]+)_(.+)\.pdf$", re.IGNORECASE)


@dataclasses.dataclass
class InvoiceRow:
    invoice_no: str
    invoice_type: str
    invoice_date: str  # YYYY/MM/DD
    payee: str
    amount: float
    pdf: Optional[Path] = None


@dataclasses.dataclass
class ZipResult:
    zip_path: Path
    rows: List[InvoiceRow] = dataclasses.field(default_factory=list)
    created: List[str] = dataclasses.field(default_factory=list)      # 新写入飞书的发票号
    duplicates: List[str] = dataclasses.field(default_factory=list)   # 远端已存在
    missing_pdf: List[str] = dataclasses.field(default_factory=list)  # 有行无 PDF
    orphan_pdfs: List[str] = dataclasses.field(default_factory=list)  # 有 PDF 无行
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _norm_date(value) -> str:
    """开票日期统一为 YYYY/MM/DD（openpyxl 可能给 datetime 或字符串）。"""
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, date):
        return value.strftime("%Y/%m/%d")
    s = str(value or "").strip().replace("-", "/")
    return s


def _date_to_yymmdd(d: str) -> str:
    m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", d)
    if not m:
        return ""
    return f"{m.group(1)[2:]}{int(m.group(2)):02d}{int(m.group(3)):02d}"


def parse_stats_xlsx(path: Path) -> List[InvoiceRow]:
    """解析 QQ 邮箱导出的发票统计 xlsx。按表头名取列；跳过总计行与空行。"""
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if header is None:
        raise ValueError(f"{path.name}: 空表")
    col_index = {str(name).strip(): i for i, name in enumerate(header) if name is not None}
    for col in (COL_TYPE, COL_DATE, COL_NO, COL_PAYEE, COL_AMOUNT):
        if col not in col_index:
            raise ValueError(f"{path.name}: 缺少表头「{col}」，实际表头 {list(col_index)}")

    def cell(row: tuple, col: str):
        idx = col_index[col]
        return row[idx] if idx < len(row) else None

    result: List[InvoiceRow] = []
    for row in rows_iter:
        if row is None:
            continue
        invoice_no = str(cell(row, COL_NO) or "").strip()
        if not invoice_no:
            continue  # 总计行 / 空行
        try:
            amount = float(cell(row, COL_AMOUNT))
        except (TypeError, ValueError):
            raise ValueError(f"{path.name}: 发票 {invoice_no} 金额非法: {cell(row, COL_AMOUNT)!r}")
        result.append(InvoiceRow(
            invoice_no=invoice_no,
            invoice_type=str(cell(row, COL_TYPE) or "").strip() or "未分类",
            invoice_date=_norm_date(cell(row, COL_DATE)),
            payee=str(cell(row, COL_PAYEE) or "").strip(),
            amount=amount,
        ))
    wb.close()
    return result


def match_pdfs(rows: List[InvoiceRow], pdfs: List[Path]) -> List[Path]:
    """按「YYMMDD + 金额 + 收款方」把 PDF 挂到行上。返回没匹配上的 PDF。"""
    index: Dict[Tuple[str, str, str], List[InvoiceRow]] = {}
    for r in rows:
        key = (_date_to_yymmdd(r.invoice_date), f"{r.amount:.2f}", r.payee)
        index.setdefault(key, []).append(r)
    orphans: List[Path] = []
    for pdf in pdfs:
        m = PDF_NAME_RE.match(pdf.name)
        matched = None
        if m:
            try:
                amount = f"{float(m.group(2)):.2f}"
            except ValueError:
                amount = m.group(2)
            key = (m.group(1), amount, m.group(3))
            for candidate in index.get(key, []):
                if candidate.pdf is None:
                    matched = candidate
                    break
        if matched is not None:
            matched.pdf = pdf
        else:
            orphans.append(pdf)
    return orphans


def repair_zip_name(info: zipfile.ZipInfo) -> str:
    """zip 条目无 UTF-8 flag 时（QQ/Windows 导出常见），zipfile 会按 cp437
    解码出乱码；还原字节后按 utf-8 / gbk 重新解码。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return info.filename


def _extract_zip(zip_path: Path, dest: Path):
    """extractall 的编码安全版：修复文件名、拒绝越界路径。"""
    with zipfile.ZipFile(str(zip_path)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = repair_zip_name(info).replace("\\", "/").lstrip("/")
            if ".." in name.split("/"):
                continue  # zip-slip 防御
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())


def find_ready_zips(inbox: Path, stable_seconds: int, ledger: Ledger) -> List[Path]:
    """收件箱里已就绪（mtime 足够老、未成功处理过）的 zip。"""
    if not inbox.exists():
        return []
    now = time.time()
    ready = []
    for p in sorted(inbox.glob("*.zip")):
        if now - p.stat().st_mtime < stable_seconds:
            continue  # 可能还在下载
        if ledger.is_done(p.name):
            continue
        ready.append(p)
    return ready


def _remote_invoice_nos(lark: LarkClient, cfg: Config) -> set:
    """一次性拉取远端所有发票号，用于去重。"""
    field = cfg.fields["reimburse"]["invoice_no"]
    records = lark.record_list("reimburse", field_names=[field])
    nos = set()
    for rec in records:
        value = rec["fields"].get(field)
        if isinstance(value, list):  # 文本字段可能是 segment 列表
            value = "".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in value
            )
        if value:
            nos.add(str(value).strip())
    return nos


def process_zip(
    zip_path: Path,
    cfg: Config,
    lark: LarkClient,
    ledger: Ledger,
    journal: Journal,
    dry_run: bool = False,
    remote_nos: Optional[set] = None,
) -> ZipResult:
    result = ZipResult(zip_path=zip_path)
    ledger.mark(zip_path.name, PROCESSING)
    try:
        with tempfile.TemporaryDirectory(prefix="legal-assistant-") as tmp:
            tmp_dir = Path(tmp)
            _extract_zip(zip_path, tmp_dir)

            xlsx_files = [p for p in tmp_dir.rglob("*.xlsx") if not p.name.startswith("~")]
            if not xlsx_files:
                raise ValueError("zip 内没有发票统计 xlsx（可能是半成品导出）")
            stats = sorted(xlsx_files, key=lambda p: ("发票统计" not in p.name, p.name))[0]
            result.rows = parse_stats_xlsx(stats)
            if not result.rows:
                raise ValueError(f"{stats.name} 解析出 0 行发票")

            pdfs = list(tmp_dir.rglob("*.pdf")) + list(tmp_dir.rglob("*.PDF"))
            orphans = match_pdfs(result.rows, pdfs)
            result.orphan_pdfs = [p.name for p in orphans]

            if remote_nos is None:
                remote_nos = _remote_invoice_nos(lark, cfg)

            out_root = cfg.paths["invoice_output"] / date.today().isoformat()
            fmap = cfg.fields["reimburse"]
            for row in result.rows:
                # 归档 PDF（打印用），与飞书写入独立：重复发票也照样归档打印
                if row.pdf is not None:
                    safe_copy(row.pdf, out_root / row.invoice_type / row.pdf.name, dry_run=dry_run)
                else:
                    result.missing_pdf.append(row.invoice_no)

                if row.invoice_no in remote_nos or ledger.is_done(row.invoice_no):
                    result.duplicates.append(row.invoice_no)
                    continue
                lark.record_create("reimburse", {
                    fmap["invoice_no"]: row.invoice_no,
                    fmap["invoice_type"]: row.invoice_type,
                    fmap["amount"]: row.amount,
                    fmap["payee"]: row.payee,
                    fmap["invoice_date"]: row.invoice_date,
                })
                remote_nos.add(row.invoice_no)
                result.created.append(row.invoice_no)
                if not dry_run:
                    ledger.mark(row.invoice_no, SUCCEEDED, kind="invoice_row", zip=zip_path.name)

            # 没匹配上的 PDF 沉淀到 待人工复核（不丢）
            for orphan in orphans:
                safe_copy(orphan, out_root / "待人工复核" / orphan.name, dry_run=dry_run)

        if not dry_run:
            safe_move(zip_path, cfg.paths["invoice_archive"], dry_run=False)
            ledger.mark(
                zip_path.name, SUCCEEDED,
                rows=len(result.rows), created=len(result.created),
                duplicates=len(result.duplicates),
            )
        journal.append(
            "invoice-once",
            f"{zip_path.name}: {len(result.rows)} 行，新增 {len(result.created)}，"
            f"重复 {len(result.duplicates)}，缺 PDF {len(result.missing_pdf)}，"
            f"孤儿 PDF {len(result.orphan_pdfs)}" + ("（dry-run）" if dry_run else ""),
        )
    except Exception as exc:  # zip 留原地，状态 failed
        result.error = str(exc)
        ledger.mark(zip_path.name, FAILED, error=str(exc)[:500])
        journal.append("invoice-once", f"{zip_path.name}: 失败 — {exc}")
    return result


def run_invoice_once(cfg: Config, lark: LarkClient, journal: Journal, dry_run: bool = False) -> List[ZipResult]:
    ledger = Ledger(cfg.paths["state_dir"], "invoices")
    zips = find_ready_zips(cfg.paths["invoice_inbox"], cfg.zip_stable_seconds, ledger)
    if not zips:
        return []
    try:
        remote_nos = _remote_invoice_nos(lark, cfg)
    except Exception as exc:
        if not dry_run:
            raise
        # dry-run 允许离线验证：远端不可达时跳过去重，只做解析/分类演练
        journal.append("invoice-once", f"dry-run：远端去重不可用（{exc}），按空集处理")
        remote_nos = set()
    results = []
    for zip_path in zips:
        results.append(
            process_zip(zip_path, cfg, lark, ledger, journal, dry_run=dry_run, remote_nos=remote_nos)
        )
    return results
