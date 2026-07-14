"""Slice 3：定时汇总推送。"""

from legal_assistant.journal import NullJournal
from legal_assistant.summary import collect, render_markdown, run_weekly_summary


def _seed(fake_lark):
    for no, member, amount in [("N1", "刘达", 100.0), ("N2", "刘达", 50.5), ("N3", "杨铖", 200.0)]:
        fake_lark.record_create("reimburse", {
            "发票号码": no, "发票类型": "餐饮", "金额": amount,
            "收款方": "某公司", "开票日期": "2026/07/01", "团队成员": member,
        })
    fake_lark.record_create("output_invoices", {
        "发票号": "OUT1", "团队成员": "刘达", "合同号": "20260001",
        "付款方": "深圳市安居集团有限公司", "开票日期": "2026/01/14", "发票金额": 18550.0,
    })


def test_collect_aggregates(cfg, fake_lark):
    _seed(fake_lark)
    data = collect(cfg, fake_lark)
    assert data.reimburse_by_member["刘达"] == [2, 150.5]
    assert data.reimburse_by_member["杨铖"] == [1, 200.0]
    assert data.reimburse_total == 350.5
    assert data.invoices_total == 18550.0
    assert len(data.invoices_by_member["刘达"]) == 1


def test_render_contains_totals(cfg, fake_lark):
    _seed(fake_lark)
    md = render_markdown(collect(cfg, fake_lark), as_of="2026-07-17")
    assert "费用发票提交统计" in md and "开票汇总表" in md
    assert "¥350.50" in md and "¥18,550.00" in md
    assert "截至 2026-07-17" in md


def test_empty_tables(cfg, fake_lark):
    md = render_markdown(collect(cfg, fake_lark))
    assert "¥0.00" in md  # 空表不崩，总计为 0


def test_dry_run_writes_snapshot_no_send(cfg, fake_lark):
    _seed(fake_lark)
    run_weekly_summary(cfg, fake_lark, NullJournal(), dry_run=True)
    assert not fake_lark.messages
    snapshots = list(cfg.paths["state_dir"].glob("weekly-summary-*.dryrun.md"))
    assert len(snapshots) == 1


def test_send_pushes_markdown_and_xlsx(cfg, fake_lark):
    _seed(fake_lark)
    run_weekly_summary(cfg, fake_lark, NullJournal(), dry_run=False)
    assert len(fake_lark.messages) == 1
    msg = fake_lark.messages[0]
    assert msg["user_id"] == "ou_test"
    assert "开票汇总表" in msg["markdown"]
    assert msg["key"].startswith("weekly-")
    assert cfg.weekly_xlsx_dir is not None
    assert list(cfg.weekly_xlsx_dir.glob("汇总_*.xlsx"))
