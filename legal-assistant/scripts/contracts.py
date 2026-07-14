"""B1 销项发票入账 + B0 合同登记。

B1（自动 + 人工兜底）：
  开票收件箱 PDF → 文本层提取发票字段 → 用付款方在合同台账唯一匹配合同号 →
  写合同开票统计表 → 尽力回写合同台账（已开票/关联发票）→ PDF 归档。
  任何不确定（字段缺失 / 无匹配 / 多匹配 / 远端重复）→ pending_review，禁止猜测写入。
  人工复核协议：`pending` 列出挂起项，`resolve --contract-no … [--member …]` 显式补全后写入。

B0（对话式半自动）：
  contract-draft <pdf> → 字段草稿 JSON（低置信度留空）→ agent/用户确认修改 →
  contract-commit --draft <json> → 写合同台账 + 上传附件。确认前不落任何业务数据。
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config
from .fsops import safe_move
from .journal import Journal
from .lark import LarkClient, field_number, field_text
from .state import FAILED, PENDING_REVIEW, SUCCEEDED, Ledger

# ---------- 发票 PDF 文本解析 ----------
# 真实电子发票文本层的标签与值是分离的（标签区在前，值按提取顺序在后），
# 所以除「标签:值」内联式外，还要按结构化锚点解析：
# 20 位发票号 / YYYY年MM月DD日 / 最大 ¥金额（价税合计必为最大）/ 信用代码行的前一行是公司名。

# 内联式正则一律不跨行（[ \t] 而非 \s）：标签值分离版式中标签行后面跟的是无关内容
RE_INVOICE_NO = re.compile(r"发票号码[:：][ \t]*(\d{8,20})")
RE_INVOICE_NO_BARE = re.compile(r"(?<!\d)(\d{20})(?!\d)")
RE_DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
RE_AMOUNT_LABELED = re.compile(r"[（(]\s*小写\s*[)）][ \t]*[¥￥]?[ \t]*([\d,]+(?:\.\d{1,2})?)")
RE_AMOUNT_CNY = re.compile(r"[¥￥]\s*([\d,]+\.\d{2})")
RE_DECIMAL = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})(?![\d%])")
RE_BUYER = re.compile(r"名\s*称[:：][ \t]*([^\s：:]{2,50})")
RE_USCC_LINE = re.compile(r"^[0-9A-HJ-NP-RT-UW-Y]{18}$")
RE_HAS_CJK = re.compile(r"[一-鿿]")


@dataclasses.dataclass
class ParsedInvoice:
    invoice_no: str = ""
    invoice_date: str = ""  # YYYY/MM/DD
    amount: Optional[float] = None
    payer: str = ""

    def missing(self) -> List[str]:
        gaps = []
        if not self.invoice_no:
            gaps.append("发票号")
        if not self.invoice_date:
            gaps.append("开票日期")
        if self.amount is None:
            gaps.append("金额")
        if not self.payer:
            gaps.append("付款方")
        return gaps


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        with fitz.open(str(path)) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def _counterparty(text: str, firm_name: str) -> str:
    """对方名称：信用代码行的前一行是公司名；排除本所名称后剩下的即对方。"""
    lines = [ln.strip() for ln in text.splitlines()]
    candidates: List[str] = []
    for i, line in enumerate(lines):
        if RE_USCC_LINE.match(line) and i > 0:
            name = lines[i - 1]
            # 公司/个人名必须含中文，且不是标签行
            if len(name) >= 3 and RE_HAS_CJK.search(name) and "：" not in name and ":" not in name:
                candidates.append(name)
    for name in candidates:
        if firm_name and (firm_name in name or name in firm_name):
            continue
        return name
    return ""


def parse_invoice_text(text: str, firm_name: str = "") -> ParsedInvoice:
    parsed = ParsedInvoice()
    # 发票号：内联标签优先，否则取独立的 20 位数字
    m = RE_INVOICE_NO.search(text)
    if m:
        parsed.invoice_no = m.group(1)
    else:
        m = RE_INVOICE_NO_BARE.search(text)
        if m:
            parsed.invoice_no = m.group(1)
    m = RE_DATE.search(text)
    if m:
        parsed.invoice_date = f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    # 金额：内联「（小写）」优先，否则取全文最大 ¥ 值（价税合计必为最大）
    m = RE_AMOUNT_LABELED.search(text)
    if m:
        try:
            parsed.amount = float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    if parsed.amount is None:
        # 恒等式校验：价税合计 = 税前 + 税额，且是全票最大的「等于另两数之和」的数。
        # 兜底：最大 ¥ 值。
        decimals = []
        for raw in RE_DECIMAL.findall(text):
            try:
                decimals.append(float(raw.replace(",", "")))
            except ValueError:
                pass
        pair_sums = set()
        for i, a in enumerate(decimals):
            for b in decimals[i + 1:]:
                pair_sums.add(round(a + b, 2))
        totals = [d for d in decimals if round(d, 2) in pair_sums]
        if totals:
            parsed.amount = max(totals)
        else:
            cny = []
            for raw in RE_AMOUNT_CNY.findall(text):
                try:
                    cny.append(float(raw.replace(",", "")))
                except ValueError:
                    pass
            if cny:
                parsed.amount = max(cny)
    # 对方名称：内联「名称：X」优先（须含中文、排除本所），否则按信用代码邻接行
    for m in RE_BUYER.finditer(text):
        name = m.group(1).strip()
        if not RE_HAS_CJK.search(name):
            continue
        if firm_name and (firm_name in name or name in firm_name):
            continue
        parsed.payer = name
        break
    if not parsed.payer:
        parsed.payer = _counterparty(text, firm_name)
    return parsed


# ---------- B1 ----------

def _lookup_contracts(lark: LarkClient, cfg: Config, client: str) -> List[dict]:
    """按客户名在合同台账中查合同。返回 [{"contract_no":…, "record_id":…}]。"""
    fmap = cfg.fields["contracts"]
    records = lark.find_by_field("contracts", fmap["client"], client)
    out = []
    for rec in records:
        out.append({
            "record_id": rec["record_id"],
            "contract_no": field_text(rec["fields"].get(fmap["contract_no"])),
            "invoiced": field_number(rec["fields"].get(fmap["invoiced"])),
        })
    return out


def _remote_output_invoice_exists(lark: LarkClient, cfg: Config, invoice_no: str) -> bool:
    fmap = cfg.fields["output_invoices"]
    return bool(lark.find_by_field("output_invoices", fmap["invoice_no"], invoice_no))


def _write_output_invoice(
    lark: LarkClient, cfg: Config, parsed: ParsedInvoice,
    contract_no: str, member: str, contract_record_id: str = "",
) -> Optional[str]:
    fmap = cfg.fields["output_invoices"]
    fields = {
        fmap["invoice_no"]: parsed.invoice_no,
        fmap["contract_no"]: contract_no,
        fmap["payer"]: parsed.payer,
        fmap["invoice_date"]: parsed.invoice_date,
        fmap["amount"]: parsed.amount,
    }
    if member:
        fields[fmap["member"]] = member
    # 双向关联字段：指向合同台账记录，合同侧「关联发票」自动反填
    if contract_record_id:
        fields[fmap["contract_link"]] = [{"id": contract_record_id}]
    return lark.record_create("output_invoices", fields)


def _writeback_contract(lark: LarkClient, cfg: Config, contract: dict, parsed: ParsedInvoice):
    """回写合同台账「已开票」金额累加。关联发票由双向 link 自动维护，不在此写。
    失败向上抛出，由调用方转挂起。"""
    fmap = cfg.fields["contracts"]
    lark.record_update("contracts", contract["record_id"], {
        fmap["invoiced"]: contract["invoiced"] + (parsed.amount or 0),
    })


def _find_contract_by_no(lark: LarkClient, cfg: Config, contract_no: str) -> dict:
    """按合同号唯一定位合同台账记录（回写用）。非唯一即抛错。"""
    fmap = cfg.fields["contracts"]
    records = lark.find_by_field("contracts", fmap["contract_no"], contract_no)
    if len(records) != 1:
        raise ValueError(
            f"合同号 {contract_no} 在合同台账中匹配到 {len(records)} 条记录"
            "（0 条请先用 contract-draft/commit 登记合同）"
        )
    rec = records[0]
    return {
        "record_id": rec["record_id"],
        "contract_no": contract_no,
        "invoiced": field_number(rec["fields"].get(fmap["invoiced"])),
    }


def run_output_invoice_once(
    cfg: Config, lark: LarkClient, journal: Journal, dry_run: bool = False,
) -> Dict[str, List[str]]:
    inbox = cfg.paths["output_invoice_inbox"]
    ledger = Ledger(cfg.paths["state_dir"], "output_invoices")
    report: Dict[str, List[str]] = {"created": [], "pending": [], "failed": []}
    if not inbox.exists():
        return report

    for pdf in sorted(inbox.glob("*.pdf")) + sorted(inbox.glob("*.PDF")):
        key = pdf.name
        if ledger.status(key) in (SUCCEEDED, PENDING_REVIEW):
            continue  # 挂起项等 resolve，成功项不重做

        text = extract_pdf_text(pdf)
        parsed = parse_invoice_text(text, cfg.firm_name)
        gaps = parsed.missing()

        def _pend(reason: str, **extra):
            ledger.mark(
                key, PENDING_REVIEW, reason=reason,
                parsed=dataclasses.asdict(parsed), **extra,
            )
            report["pending"].append(f"{key}: {reason}")
            journal.append("output-invoice-once", f"{key} 挂起：{reason}")

        if gaps:
            _pend(f"字段缺失：{'/'.join(gaps)}（文本层不可读或版式不识别）")
            continue
        if _remote_output_invoice_exists(lark, cfg, parsed.invoice_no):
            _pend(f"发票 {parsed.invoice_no} 远端已存在，疑似重复")
            continue

        contracts = _lookup_contracts(lark, cfg, parsed.payer)
        if len(contracts) != 1:
            nos = [c["contract_no"] for c in contracts]
            _pend(
                f"付款方「{parsed.payer}」匹配到 {len(contracts)} 个合同",
                candidates=nos,
            )
            continue

        contract = contracts[0]
        try:
            record_id = _write_output_invoice(
                lark, cfg, parsed, contract["contract_no"], member="",
                contract_record_id=contract["record_id"],
            )
        except Exception as exc:
            ledger.mark(key, FAILED, error=str(exc)[:500])
            report["failed"].append(f"{key}: {exc}")
            journal.append("output-invoice-once", f"{key} 失败：{exc}")
            continue

        if not dry_run:
            try:
                _writeback_contract(lark, cfg, contract, parsed)
            except Exception as exc:
                # 主表已写、回写失败：挂起（记下 record_id 防重试重复建主表）、不归档 PDF
                _pend(
                    f"主表已写入但回写合同台账失败：{str(exc)[:300]}"
                    f"（用 resolve {key} --contract-no {contract['contract_no']} 重试回写）",
                    main_record_id=record_id or "",
                    main_record_written=True,
                    contract_no=contract["contract_no"],
                )
                continue
            safe_move(pdf, cfg.paths["output_invoice_archive"], dry_run=False)
            ledger.mark(
                key, SUCCEEDED, invoice_no=parsed.invoice_no,
                contract_no=contract["contract_no"],
            )
        report["created"].append(f"{key} → 合同 {contract['contract_no']}")
        journal.append(
            "output-invoice-once",
            f"{key}: 发票 {parsed.invoice_no} 入账（合同 {contract['contract_no']}，"
            f"¥{parsed.amount:,.2f}）" + ("（dry-run）" if dry_run else ""),
        )
    return report


def list_pending(cfg: Config) -> Dict[str, dict]:
    ledger = Ledger(cfg.paths["state_dir"], "output_invoices")
    return ledger.entries(PENDING_REVIEW)


def resolve_pending(
    cfg: Config, lark: LarkClient, journal: Journal,
    key: str, contract_no: str, member: str = "",
    invoice_no: str = "", amount: Optional[float] = None,
    payer: str = "", invoice_date: str = "",
) -> str:
    """人工复核协议：显式给出合同号（及必要的补正字段）后完成写入。

    与自动路径完全一致：写主表 + 回写合同台账 + 归档 PDF。
    若挂起原因是「主表已写、回写失败」（entry 带 main_record_written），
    重试时跳过主表写入，只补回写，避免重复建记录。"""
    ledger = Ledger(cfg.paths["state_dir"], "output_invoices")
    entry = ledger.get(key)
    if not entry or entry.get("status") != PENDING_REVIEW:
        raise ValueError(f"没有名为 {key} 的挂起项（用 `legal-assistant pending` 查看）")
    saved = entry.get("parsed") or {}
    parsed = ParsedInvoice(
        invoice_no=invoice_no or saved.get("invoice_no", ""),
        invoice_date=invoice_date or saved.get("invoice_date", ""),
        amount=amount if amount is not None else saved.get("amount"),
        payer=payer or saved.get("payer", ""),
    )
    gaps = parsed.missing()
    if gaps:
        raise ValueError(f"仍缺字段：{'/'.join(gaps)}，请通过 --invoice-no/--amount/--payer/--date 补全")

    # 回写目标必须先唯一定位（合同不存在/多条 → 直接报错，不写任何数据）
    contract = _find_contract_by_no(lark, cfg, contract_no)

    main_written = bool(entry.get("main_record_written"))
    if not main_written:
        if _remote_output_invoice_exists(lark, cfg, parsed.invoice_no):
            raise ValueError(f"发票 {parsed.invoice_no} 远端已存在，拒绝重复写入")
        record_id = _write_output_invoice(
            lark, cfg, parsed, contract_no, member,
            contract_record_id=contract["record_id"],
        )
    else:
        record_id = entry.get("main_record_id") or ""

    try:
        _writeback_contract(lark, cfg, contract, parsed)
    except Exception as exc:
        ledger.mark(
            key, PENDING_REVIEW,
            reason=f"主表已写入但回写合同台账失败：{str(exc)[:300]}",
            parsed=dataclasses.asdict(parsed),
            main_record_id=record_id or "", main_record_written=True,
            contract_no=contract_no,
        )
        journal.append("resolve", f"{key}: 回写合同台账失败，保持挂起 — {exc}")
        raise ValueError(f"回写合同台账失败（主表记录已保留，重试 resolve 即可）：{exc}")

    pdf = cfg.paths["output_invoice_inbox"] / key
    if pdf.exists():
        safe_move(pdf, cfg.paths["output_invoice_archive"], dry_run=False)
    ledger.mark(key, SUCCEEDED, invoice_no=parsed.invoice_no, contract_no=contract_no, resolved=True)
    journal.append(
        "resolve",
        f"{key}: 人工确认合同 {contract_no}，发票 {parsed.invoice_no} 入账（含台账回写）",
    )
    return parsed.invoice_no


# ---------- B0 ----------

RE_USCC = re.compile(r"[0-9A-HJ-NP-RT-UW-Y]{18}")  # 统一社会信用代码
RE_CONTRACT_AMOUNT = re.compile(r"(?:合同金额|律师费|代理费|服务费)[^\d¥￥]{0,20}[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)")
RE_SIGN_DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def contract_draft(cfg: Config, pdf: Path, journal: Journal) -> Path:
    """从合同 PDF 生成字段草稿 JSON。只预填可靠字段，其余留空待确认。"""
    text = extract_pdf_text(pdf)
    if not text.strip() and cfg.scan.ocr_command:
        from .scans import _ocr_text
        text = _ocr_text(pdf, cfg.scan)

    draft = {
        "_source_pdf": str(pdf.resolve()),
        "_created_at": datetime.now().isoformat(timespec="seconds"),
        "_note": "低置信度字段留空；确认/补全后用 contract-commit 写入",
        "律所合同号": "",
        "客户名称": "",
        "信用代码": "",
        "合同金额": None,
        "签约日期": "",
    }
    m = RE_USCC.search(text)
    if m:
        draft["信用代码"] = m.group(0)
    m = RE_CONTRACT_AMOUNT.search(text)
    if m:
        try:
            draft["合同金额"] = float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    m = RE_SIGN_DATE.search(text)
    if m:
        draft["签约日期"] = f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"

    drafts_dir = cfg.paths["state_dir"] / "contract_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    out = drafts_dir / f"{pdf.stem}.draft.json"
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    journal.append("contract-draft", f"{pdf.name} → 草稿 {out.name}（待确认）")
    return out


# B0 草稿键（用户/agent 可读的中文）→ config fields.contracts 的内部键。
# 写飞书前一律经 config 映射转换；表里字段改名只改 config。
DRAFT_KEY_MAP = {
    "律所合同号": "contract_no",
    "客户名称": "client",
    "信用代码": "credit_code",
    "合同金额": "amount",
    "签约日期": "sign_date",
}


def contract_commit(
    cfg: Config, lark: LarkClient, journal: Journal, draft_path: Path,
    attachment_field: Optional[str] = None,
) -> Optional[str]:
    """确认后的草稿写入合同台账 + 上传原 PDF 附件。"""
    draft = json.loads(Path(draft_path).read_text(encoding="utf-8"))
    fmap = cfg.fields["contracts"]
    contract_no = str(draft.get("律所合同号") or "").strip()
    client = str(draft.get("客户名称") or "").strip()
    if not contract_no or not client:
        raise ValueError("草稿缺少 律所合同号 / 客户名称——确认补全后再 commit")
    existing = lark.find_by_field("contracts", fmap["contract_no"], contract_no)
    if existing:
        raise ValueError(f"合同号 {contract_no} 已存在于合同台账，拒绝重复登记")

    fields = {}
    for key, value in draft.items():
        if key.startswith("_") or value in (None, ""):
            continue
        internal = DRAFT_KEY_MAP.get(key)
        if internal:
            if internal not in fmap:
                raise ValueError(
                    f"config fields.contracts 缺少 `{internal}` 映射（草稿字段「{key}」），"
                    "补全 config 后重试"
                )
            fields[fmap[internal]] = value
        else:
            # 用户补充的业务字段：键名必须是飞书表的真实字段名（SKILL.md 约定）
            fields[key] = value

    record_id = lark.record_create("contracts", fields)
    source_pdf = Path(draft.get("_source_pdf", ""))
    # 附件字段名：CLI 显式指定 > config 映射 > 默认「附件」
    if attachment_field is None:
        attachment_field = fmap.get("attachment", "附件")
    if record_id and source_pdf.exists() and attachment_field:
        try:
            lark.upload_attachment("contracts", record_id, attachment_field, source_pdf)
        except Exception as exc:
            journal.append("contract-commit", f"附件上传失败（{contract_no}）：{exc}")
    journal.append(
        "contract-commit",
        f"合同 {contract_no}（{client}）已登记" + (f"，record {record_id}" if record_id else "（dry-run）"),
    )
    return record_id
