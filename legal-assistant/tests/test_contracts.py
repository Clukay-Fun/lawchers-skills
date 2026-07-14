"""Slice 4/5：B1 销项入账 + B0 合同登记。"""

import json

import pytest

from legal_assistant.contracts import (
    contract_commit,
    contract_draft,
    extract_pdf_text,
    list_pending,
    parse_invoice_text,
    resolve_pending,
    run_output_invoice_once,
)
from legal_assistant.journal import NullJournal
from legal_assistant.state import PENDING_REVIEW, Ledger

SAMPLE_INVOICE_TEXT = """
电子发票（普通发票）
发票号码：26952000001234567890
开票日期： 2026年07月10日
购 买 方 名称：深圳市安居集团有限公司
统一社会信用代码：91440300MA5XXXXX0X
销 售 方 名称：北京市隆安（深圳）律师事务所
价税合计（大写） 壹万捌仟伍佰伍拾圆整 （小写）¥18550.00
"""


# 真实电子发票文本层：标签区在前、值按序在后（与桌面真实样例同构）
REAL_LAYOUT_TEXT = """电子发票（普通发票）
发票号码：
开票日期：
销
售
方
信
息
统一社会信用代码/纳税人识别号：
名称：
购
买
方
信
息
统一社会信用代码/纳税人识别号：
名称：
26952000001234567890
2026年07月10日
深圳市安居集团有限公司
91440300MA5DA8G12X
北京市隆安（深圳）律师事务所
31440000MD0217791L
项目名称
*鉴证咨询服务*法律服务费
价税合计（大写）
合        计
（小写）
壹万捌仟伍佰伍拾圆整
¥18550.00
17509.43
¥
1040.57
¥
"""


FIRM = "北京市隆安（深圳）律师事务所"


def test_parse_inline_label_layout():
    p = parse_invoice_text(SAMPLE_INVOICE_TEXT, FIRM)
    assert p.invoice_no == "26952000001234567890"
    assert p.invoice_date == "2026/07/10"
    assert p.amount == 18550.0
    assert p.payer == "深圳市安居集团有限公司"
    assert p.missing() == []


def test_parse_real_separated_layout():
    p = parse_invoice_text(REAL_LAYOUT_TEXT, FIRM)
    assert p.invoice_no == "26952000001234567890"
    assert p.invoice_date == "2026/07/10"
    assert p.amount == 18550.0  # 最大 ¥ 值 = 价税合计
    assert p.payer == "深圳市安居集团有限公司"  # 排除本所后的对方
    assert p.missing() == []


def test_parse_real_pdf_via_fitz(tmp_path):
    """真实 PDF 路径：用 pymupdf 生成分离版式发票 PDF，走完整 extract→parse 链。"""
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "real_layout.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 40
    for line in REAL_LAYOUT_TEXT.splitlines():
        page.insert_text((40, y), line, fontname="china-s", fontsize=9)
        y += 14
    doc.save(str(pdf_path))
    doc.close()

    text = extract_pdf_text(pdf_path)
    assert "发票号码" in text  # 文本层真实存在
    p = parse_invoice_text(text, FIRM)
    assert p.invoice_no == "26952000001234567890"
    assert p.invoice_date == "2026/07/10"
    assert p.amount == 18550.0
    assert p.payer == "深圳市安居集团有限公司"
    assert p.missing() == []


def _seed_contract(fake_lark, contract_no="20260001", client="深圳市安居集团有限公司"):
    return fake_lark.record_create("contracts", {
        "律所合同号": contract_no, "客户名称": client, "已开票": 0,
    })


def _drop_invoice_pdf(cfg, monkeypatch, text=SAMPLE_INVOICE_TEXT, name="out1.pdf"):
    pdf = cfg.paths["output_invoice_inbox"] / name
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("legal_assistant.contracts.extract_pdf_text", lambda p: text)
    return pdf


def test_b1_unique_match_writes_and_writes_back(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark)
    pdf = _drop_invoice_pdf(cfg, monkeypatch)
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    assert len(report["created"]) == 1 and not report["pending"]
    rec = fake_lark.tables["output_invoices"][0]["fields"]
    assert rec["发票号"] == "26952000001234567890"
    assert rec["合同号"] == "20260001"
    # 双向关联字段指向合同记录（合同侧「关联发票」由飞书自动反填）
    contract_rec_id = fake_lark.tables["contracts"][0]["record_id"]
    assert rec["合同台账"] == [{"id": contract_rec_id}]
    # 回写合同台账「已开票」累加
    contract = fake_lark.tables["contracts"][0]["fields"]
    assert contract["已开票"] == 18550.0
    # PDF 归档
    assert not pdf.exists()
    assert (cfg.paths["output_invoice_archive"] / "out1.pdf").exists()


def test_b1_no_match_pends(cfg, fake_lark, monkeypatch):
    _drop_invoice_pdf(cfg, monkeypatch)  # 没有任何合同
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    assert len(report["pending"]) == 1
    assert not fake_lark.tables["output_invoices"]
    assert list_pending(cfg)  # 挂起可查


def test_b1_multi_match_pends(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark, "20260001")
    _seed_contract(fake_lark, "20260002")  # 同客户两个合同
    _drop_invoice_pdf(cfg, monkeypatch)
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    assert len(report["pending"]) == 1
    entry = list(list_pending(cfg).values())[0]
    assert set(entry["candidates"]) == {"20260001", "20260002"}
    assert not fake_lark.tables["output_invoices"]


def test_b1_unreadable_text_pends(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark)
    _drop_invoice_pdf(cfg, monkeypatch, text="")  # 无文本层
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    assert len(report["pending"]) == 1
    assert "字段缺失" in report["pending"][0]


def test_b1_remote_duplicate_pends(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark)
    fake_lark.record_create("output_invoices", {"发票号": "26952000001234567890"})
    _drop_invoice_pdf(cfg, monkeypatch)
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    assert len(report["pending"]) == 1
    assert "重复" in report["pending"][0]
    assert len(fake_lark.tables["output_invoices"]) == 1  # 没多写


def test_resolve_pending_flow(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark, "20260001")
    _seed_contract(fake_lark, "20260002")
    _drop_invoice_pdf(cfg, monkeypatch)
    run_output_invoice_once(cfg, fake_lark, NullJournal())
    # 人工确认合同号
    invoice_no = resolve_pending(
        cfg, fake_lark, NullJournal(),
        key="out1.pdf", contract_no="20260002", member="刘达",
    )
    assert invoice_no == "26952000001234567890"
    rec = fake_lark.tables["output_invoices"][0]["fields"]
    assert rec["合同号"] == "20260002" and rec["团队成员"] == "刘达"
    # 关联字段指向用户选定的那个合同记录
    chosen_id = [r["record_id"] for r in fake_lark.tables["contracts"]
                 if r["fields"]["律所合同号"] == "20260002"][0]
    assert rec["合同台账"] == [{"id": chosen_id}]
    # 与自动路径一致：resolve 也回写合同台账「已开票」累加
    resolved_contract = [
        r["fields"] for r in fake_lark.tables["contracts"]
        if r["fields"]["律所合同号"] == "20260002"
    ][0]
    assert resolved_contract["已开票"] == 18550.0
    # 未选中的合同不受影响
    other = [
        r["fields"] for r in fake_lark.tables["contracts"]
        if r["fields"]["律所合同号"] == "20260001"
    ][0]
    assert other["已开票"] == 0
    ledger = Ledger(cfg.paths["state_dir"], "output_invoices")
    assert ledger.is_done("out1.pdf")
    # 再跑一轮不重复处理
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    assert not report["created"] and not report["pending"]


def test_resolve_unknown_contract_no_writes_nothing(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark, "20260001")
    _seed_contract(fake_lark, "20260002")
    _drop_invoice_pdf(cfg, monkeypatch)
    run_output_invoice_once(cfg, fake_lark, NullJournal())
    # 给了一个台账里不存在的合同号：直接报错，主表不写
    with pytest.raises(ValueError, match="匹配到 0 条"):
        resolve_pending(cfg, fake_lark, NullJournal(), key="out1.pdf", contract_no="99999999")
    assert not fake_lark.tables["output_invoices"]


def test_b1_writeback_failure_pends_and_resolve_retries(cfg, fake_lark, monkeypatch):
    _seed_contract(fake_lark, "20260001")
    pdf = _drop_invoice_pdf(cfg, monkeypatch)

    # 模拟回写失败（record_update 抛错）
    def boom(table_key, record_id, fields):
        raise RuntimeError("字段类型不匹配")

    original_update = fake_lark.record_update
    fake_lark.record_update = boom
    report = run_output_invoice_once(cfg, fake_lark, NullJournal())
    # 主表已写、回写失败 → 挂起而非成功；PDF 不归档
    assert not report["created"] and len(report["pending"]) == 1
    assert "回写合同台账失败" in report["pending"][0]
    assert len(fake_lark.tables["output_invoices"]) == 1
    assert pdf.exists()
    entry = list(list_pending(cfg).values())[0]
    assert entry["main_record_written"] is True and entry["main_record_id"]

    # 恢复后 resolve 重试：不重复建主表，补回写 + 归档
    fake_lark.record_update = original_update
    resolve_pending(cfg, fake_lark, NullJournal(), key="out1.pdf", contract_no="20260001")
    assert len(fake_lark.tables["output_invoices"]) == 1  # 没有第二条
    contract = fake_lark.tables["contracts"][0]["fields"]
    assert contract["已开票"] == 18550.0
    assert not pdf.exists()
    assert (cfg.paths["output_invoice_archive"] / "out1.pdf").exists()
    ledger = Ledger(cfg.paths["state_dir"], "output_invoices")
    assert ledger.is_done("out1.pdf")


def test_resolve_unknown_key_raises(cfg, fake_lark):
    with pytest.raises(ValueError, match="挂起项"):
        resolve_pending(cfg, fake_lark, NullJournal(), key="nope.pdf", contract_no="X")


def test_b0_draft_then_commit(cfg, fake_lark, monkeypatch, tmp_path):
    contract_pdf = tmp_path / "委托代理合同.pdf"
    contract_pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        "legal_assistant.contracts.extract_pdf_text",
        lambda p: "甲方统一社会信用代码 91440300MA5EXAMPLE 律师费 ¥50,000.00 2026年06月01日签订",
    )
    draft_path = contract_draft(cfg, contract_pdf, NullJournal())
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["信用代码"] == "91440300MA5EXAMPLE"
    assert draft["合同金额"] == 50000.0
    assert draft["签约日期"] == "2026/06/01"
    assert draft["律所合同号"] == ""  # 低置信度留空
    # 确认前不落业务数据
    assert not fake_lark.tables["contracts"]

    # commit 前必须补全合同号/客户名
    with pytest.raises(ValueError, match="律所合同号"):
        contract_commit(cfg, fake_lark, NullJournal(), draft_path)

    draft["律所合同号"] = "20260099"
    draft["客户名称"] = "某某科技有限公司"
    draft["承办人"] = "刘达"  # 用户补充字段：键名即飞书真实字段名，原样透传
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    record_id = contract_commit(cfg, fake_lark, NullJournal(), draft_path)
    fields = fake_lark.tables["contracts"][0]["fields"]
    assert fields["律所合同号"] == "20260099"
    # 已知草稿键必须经 config 映射转换（conftest 映射到不同名字段以验证）
    assert fields["合同金额(元)"] == 50000.0
    assert fields["信用代码/身份证"] == "91440300MA5EXAMPLE"
    assert fields["签约日期"] == "2026/06/01"
    assert "合同金额" not in fields  # 草稿键名不得直写
    assert fields["承办人"] == "刘达"
    # 附件字段名取自 config 映射；已上传且可追溯到原 PDF
    assert fake_lark.attachments[0][1] == record_id
    assert fake_lark.attachments[0][2] == "合同附件"
    assert fake_lark.attachments[0][3] == str(contract_pdf.resolve())

    # 重复登记被拒
    with pytest.raises(ValueError, match="已存在"):
        contract_commit(cfg, fake_lark, NullJournal(), draft_path)
