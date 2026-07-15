"""legal-assistant CLI：Task Scheduler 与 agent 的统一入口。

一次调用有明确开始和结束；失败项隔离，退出码非零表示存在失败。
`--dry-run`：不写飞书、不移动文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, PATH_KEYS, load_config
from .journal import Journal
from .lark import LarkClient, LarkError


def _load(args) -> Config:
    return load_config(args.config)


def _client(cfg: Config, dry_run: bool) -> LarkClient:
    return LarkClient(cfg.lark, dry_run=dry_run)


def _journal(cfg: Config) -> Journal:
    return Journal(cfg.paths["journal_dir"])


# ---------- 子命令 ----------

def cmd_doctor(args) -> int:
    """诊断：配置、路径、lark-cli、可选依赖。每条问题给出可操作修复。"""
    problems = []
    try:
        cfg = _load(args)
    except ConfigError as exc:
        print(f"✗ 配置：{exc}")
        return 2
    print(f"✓ 配置：{cfg.source_file}")

    for key, desc in PATH_KEYS.items():
        path = cfg.paths[key]
        if path.exists():
            print(f"✓ {desc}：{path}")
        else:
            # state/journal/归档目录可自动创建；收件箱与扫描目录必须真实存在
            if key in ("state_dir", "journal_dir", "invoice_archive",
                       "output_invoice_archive", "invoice_output"):
                print(f"• {desc}：{path}（不存在，首次运行时自动创建）")
            else:
                problems.append(f"{desc} 不存在：{path} —— 创建该目录或修改 config paths.{key}")

    lark = _client(cfg, dry_run=True)
    err = lark.check_binary()
    if err:
        problems.append(err)
    else:
        print(f"✓ lark-cli：{cfg.lark.bin}")

    if not cfg.lark.push_user_id:
        print("• lark.push.user_id 未配置：weekly-summary 无法推送（其余功能不受影响）")

    try:
        import fitz  # noqa: F401
        print("✓ pymupdf：可用（PDF 文本层提取）")
    except ImportError:
        print("• pymupdf 未安装：扫描件只能按文件名分类，销项发票入账全部转人工。安装：pip install legal-assistant[pdf]")

    if cfg.scan.ocr_command:
        print(f"✓ OCR hook：{cfg.scan.ocr_command}")
    else:
        print("• OCR hook 未配置（scan.ocr_command）：无文本层的扫描件将沉淀到待人工复核")

    if problems:
        print("\n需要处理：")
        for p in problems:
            print(f"✗ {p}")
        return 1
    print("\ndoctor 通过。")
    return 0


def cmd_invoice_once(args) -> int:
    from .invoices import run_invoice_once

    cfg = _load(args)
    results = run_invoice_once(cfg, _client(cfg, args.dry_run), _journal(cfg), dry_run=args.dry_run)
    if not results:
        print("收件箱无待处理 zip。")
        return 0
    failed = 0
    for r in results:
        if r.ok:
            print(
                f"✓ {r.zip_path.name}: {len(r.rows)} 行，新增 {len(r.created)}，"
                f"重复 {len(r.duplicates)}，缺 PDF {len(r.missing_pdf)}，孤儿 PDF {len(r.orphan_pdfs)}"
            )
        else:
            failed += 1
            print(f"✗ {r.zip_path.name}: {r.error}")
    return 1 if failed else 0


def cmd_scan_once(args) -> int:
    from .scans import run_scan_once

    cfg = _load(args)
    r = run_scan_once(cfg, _journal(cfg), dry_run=args.dry_run)
    print(f"归档 {len(r.moved)}，复核 {len(r.review)}，垃圾 {len(r.trash)}，占用跳过 {len(r.locked)}")
    for line in r.moved:
        print(f"  {line}")
    return 0


def cmd_weekly_summary(args) -> int:
    from .summary import run_weekly_summary

    cfg = _load(args)
    markdown = run_weekly_summary(cfg, _client(cfg, args.dry_run), _journal(cfg), dry_run=args.dry_run)
    if args.dry_run:
        print(markdown)
    else:
        print("汇总已推送。")
    return 0


def cmd_output_invoice_once(args) -> int:
    from .contracts import run_output_invoice_once

    cfg = _load(args)
    report = run_output_invoice_once(cfg, _client(cfg, args.dry_run), _journal(cfg), dry_run=args.dry_run)
    for line in report["created"]:
        print(f"✓ {line}")
    for line in report["pending"]:
        print(f"… {line}")
    for line in report["failed"]:
        print(f"✗ {line}")
    if not any(report.values()):
        print("开票收件箱无待处理 PDF。")
    return 1 if report["failed"] else 0


def cmd_pending(args) -> int:
    from .contracts import list_pending

    cfg = _load(args)
    entries = list_pending(cfg)
    print(json.dumps(entries, ensure_ascii=False, indent=2))
    return 0


def cmd_resolve(args) -> int:
    from .contracts import resolve_pending

    cfg = _load(args)
    invoice_no = resolve_pending(
        cfg, _client(cfg, False), _journal(cfg),
        key=args.key, contract_no=args.contract_no, member=args.member or "",
        invoice_no=args.invoice_no or "", amount=args.amount,
        payer=args.payer or "", invoice_date=args.date or "",
    )
    print(f"✓ {args.key}: 发票 {invoice_no} 已入账（合同 {args.contract_no}）")
    return 0


def cmd_contract_draft(args) -> int:
    from .contracts import contract_draft

    cfg = _load(args)
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"✗ 找不到 {pdf}")
        return 1
    out = contract_draft(cfg, pdf, _journal(cfg))
    print(f"草稿已生成：{out}")
    print(out.read_text(encoding="utf-8"))
    return 0


def cmd_contract_commit(args) -> int:
    from .contracts import contract_commit

    cfg = _load(args)
    record_id = contract_commit(
        cfg, _client(cfg, args.dry_run), _journal(cfg),
        Path(args.draft), attachment_field=args.attachment_field,
    )
    print(f"✓ 合同已登记（record: {record_id or 'dry-run'}）")
    return 0


def cmd_journal(args) -> int:
    cfg = _load(args)
    content = _journal(cfg).read_recent(days=args.days)
    print(content or "（journal 为空）")
    return 0


# ---------- 入口 ----------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="legal-assistant",
        description="律所日常事务自动化（发票/扫描件/周报，飞书经 lark-cli）",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text, dry_run=True):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default="config.yaml", help="配置文件路径（默认 ./config.yaml）")
        if dry_run:
            p.add_argument("--dry-run", action="store_true", help="不写飞书、不移动文件")
        p.set_defaults(func=func)
        return p

    add("doctor", cmd_doctor, "诊断配置/路径/lark-cli/依赖", dry_run=False)
    add("invoice-once", cmd_invoice_once, "处理发票收件箱中的 zip（贴票入台账）")
    add("scan-once", cmd_scan_once, "扫描件归档一轮")
    add("weekly-summary", cmd_weekly_summary, "定时汇总：聚合两表推送（调度时间在 register-tasks.ps1 自定义，默认周五 16:00）")
    add("output-invoice-once", cmd_output_invoice_once, "处理开票收件箱中的销项发票（开票入账）")
    add("pending", cmd_pending, "列出挂起待人工复核的开票项", dry_run=False)

    p = add("resolve", cmd_resolve, "人工复核：显式补全后完成挂起开票项写入", dry_run=False)
    p.add_argument("key", help="挂起项键（PDF 文件名，见 pending 输出）")
    p.add_argument("--contract-no", required=True, help="确认的律所合同号")
    p.add_argument("--member", help="团队成员")
    p.add_argument("--invoice-no", help="补正发票号")
    p.add_argument("--amount", type=float, help="补正金额")
    p.add_argument("--payer", help="补正付款方")
    p.add_argument("--date", help="补正开票日期 YYYY/MM/DD")

    p = add("contract-draft", cmd_contract_draft, "从合同 PDF 生成字段草稿（合同登记第一步）", dry_run=False)
    p.add_argument("pdf", help="合同 PDF 路径")

    p = add("contract-commit", cmd_contract_commit, "确认后的草稿写入合同台账（合同登记）")
    p.add_argument("--draft", required=True, help="草稿 JSON 路径")
    p.add_argument("--attachment-field", default=None,
                   help="附件字段名（默认取 config fields.contracts.attachment，再兜底「附件」）")

    p = add("journal", cmd_journal, "查看近几天 journal（agent 唤起时先读）", dry_run=False)
    p.add_argument("--days", type=int, default=3)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return 2
    except LarkError as exc:
        print(f"✗ lark-cli：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
