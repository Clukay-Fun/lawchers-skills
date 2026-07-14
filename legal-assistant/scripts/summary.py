"""定时汇总推送：读两张飞书表 → 按团队成员全量累计快照 → 机器人卡片私聊推送。

推送时点由 Task Scheduler 决定（默认每周五 16:00，日子/时间在 register-tasks.ps1 自定义）。
口径（保持用户现有手工格式，不做周期增量）：
1. 费用发票提交统计（发票报销台账）：每人 数量=行数 / 金额=Σ金额 + 总计
2. 开票汇总表（合同开票统计表）：每人逐张列票 + 总计
dry-run：只生成本地快照文件，不推送。
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config
from .journal import Journal
from .lark import LarkClient, field_number, field_text


@dataclasses.dataclass
class SummaryData:
    # 费用发票提交统计: member -> (count, total)
    reimburse_by_member: Dict[str, List[float]]
    reimburse_total: float
    # 开票汇总: member -> [row dict]
    invoices_by_member: Dict[str, List[dict]]
    invoices_total: float


def collect(cfg: Config, lark: LarkClient) -> SummaryData:
    fmap_r = cfg.fields["reimburse"]
    reimburse_by_member: Dict[str, List[float]] = {}
    reimburse_total = 0.0
    for rec in lark.record_list("reimburse"):
        fields = rec["fields"]
        member = field_text(fields.get("团队成员")) or "（未填成员）"
        amount = field_number(fields.get(fmap_r["amount"]))
        bucket = reimburse_by_member.setdefault(member, [0, 0.0])
        bucket[0] += 1
        bucket[1] += amount
        reimburse_total += amount

    fmap_o = cfg.fields["output_invoices"]
    invoices_by_member: Dict[str, List[dict]] = {}
    invoices_total = 0.0
    for rec in lark.record_list("output_invoices"):
        fields = rec["fields"]
        member = field_text(fields.get(fmap_o["member"])) or "（未填成员）"
        amount = field_number(fields.get(fmap_o["amount"]))
        invoices_by_member.setdefault(member, []).append({
            "invoice_no": field_text(fields.get(fmap_o["invoice_no"])),
            "contract_no": field_text(fields.get(fmap_o["contract_no"])),
            "payer": field_text(fields.get(fmap_o["payer"])),
            "invoice_date": field_text(fields.get(fmap_o["invoice_date"])),
            "amount": amount,
        })
        invoices_total += amount

    return SummaryData(
        reimburse_by_member=reimburse_by_member,
        reimburse_total=reimburse_total,
        invoices_by_member=invoices_by_member,
        invoices_total=invoices_total,
    )


def render_markdown(data: SummaryData, as_of: Optional[str] = None) -> str:
    as_of = as_of or date.today().isoformat()
    lines: List[str] = [f"# 发票与开票汇总（截至 {as_of}，全量累计）", ""]

    lines.append("## 费用发票提交统计")
    lines.append("")
    lines.append("| 团队成员 | 已提交发票数量 | 已提交发票金额 |")
    lines.append("| --- | --- | --- |")
    total_count = 0
    for member in sorted(data.reimburse_by_member):
        count, amount = data.reimburse_by_member[member]
        total_count += int(count)
        lines.append(f"| {member} | {int(count)} | ¥{amount:,.2f} |")
    lines.append(f"| **总计** | **{total_count}** | **¥{data.reimburse_total:,.2f}** |")
    lines.append("")

    lines.append("## 开票汇总表")
    lines.append("")
    lines.append("| 团队成员 | 发票号码 | 合同号 | 付款方 | 开票日期 | 金额 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for member in sorted(data.invoices_by_member):
        for i, row in enumerate(data.invoices_by_member[member]):
            name = member if i == 0 else ""
            lines.append(
                f"| {name} | {row['invoice_no']} | {row['contract_no']} | "
                f"{row['payer']} | {row['invoice_date']} | ¥{row['amount']:,.2f} |"
            )
    lines.append(f"| **总计** | | | | | **¥{data.invoices_total:,.2f}** |")
    lines.append("")
    lines.append(
        f"截至 {as_of}：费用发票累计 ¥{data.reimburse_total:,.2f}，"
        f"合同开票累计 ¥{data.invoices_total:,.2f}。"
    )
    return "\n".join(lines)


def export_xlsx(data: SummaryData, out_dir: Path, as_of: str) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "费用发票提交统计"
    ws1.append(["团队成员", "已提交发票数量", "已提交发票金额"])
    total_count = 0
    for member in sorted(data.reimburse_by_member):
        count, amount = data.reimburse_by_member[member]
        total_count += int(count)
        ws1.append([member, int(count), round(amount, 2)])
    ws1.append(["总计", total_count, round(data.reimburse_total, 2)])

    ws2 = wb.create_sheet("开票汇总表")
    ws2.append(["团队成员", "发票号码", "合同号", "付款方", "开票日期", "金额"])
    for member in sorted(data.invoices_by_member):
        for i, row in enumerate(data.invoices_by_member[member]):
            ws2.append([
                member if i == 0 else "",
                row["invoice_no"], row["contract_no"], row["payer"],
                row["invoice_date"], round(row["amount"], 2),
            ])
    ws2.append(["总计", "", "", "", "", round(data.invoices_total, 2)])

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"汇总_{as_of}.xlsx"
    wb.save(str(path))
    return path


def run_weekly_summary(cfg: Config, lark: LarkClient, journal: Journal, dry_run: bool = False) -> str:
    as_of = date.today().isoformat()
    data = collect(cfg, lark)
    markdown = render_markdown(data, as_of)

    xlsx_path = None
    if cfg.weekly_xlsx_dir and not dry_run:
        xlsx_path = export_xlsx(data, cfg.weekly_xlsx_dir, as_of)

    if dry_run:
        snapshot = cfg.paths["state_dir"] / f"weekly-summary-{as_of}.dryrun.md"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(markdown, encoding="utf-8")
        journal.append("weekly-summary", f"dry-run 快照 → {snapshot}")
        return markdown

    if not cfg.lark.push_user_id:
        raise ValueError("config `lark.push.user_id` 未配置，无法推送汇总")
    lark.send_markdown(cfg.lark.push_user_id, markdown, idempotency_key=f"weekly-{as_of}")
    journal.append(
        "weekly-summary",
        f"已推送（费用累计 ¥{data.reimburse_total:,.2f} / 开票累计 ¥{data.invoices_total:,.2f}）"
        + (f"，xlsx → {xlsx_path}" if xlsx_path else ""),
    )
    return markdown
