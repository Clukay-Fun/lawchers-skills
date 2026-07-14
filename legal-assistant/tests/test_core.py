"""Slice 0：config / state / journal。"""

import pytest

from legal_assistant.config import ConfigError, load_config
from legal_assistant.journal import Journal
from legal_assistant.state import Ledger, SUCCEEDED, PENDING_REVIEW


def test_config_loads(cfg):
    assert cfg.lark.base_token == "bascnTEST"
    assert cfg.fields["reimburse"]["invoice_no"] == "发票号码"
    assert cfg.zip_stable_seconds == 1
    assert "合同文件" in cfg.scan.categories


def test_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="找不到配置文件"):
        load_config(tmp_path / "nope.yaml")


def test_config_missing_key(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("paths:\n  invoice_inbox: /x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="paths"):
        load_config(bad)


def test_ledger_roundtrip(tmp_path):
    ledger = Ledger(tmp_path, "invoices")
    ledger.mark("k1", SUCCEEDED, note="a")
    ledger.mark("k2", PENDING_REVIEW, reason="歧义")
    # 重新加载仍在
    reloaded = Ledger(tmp_path, "invoices")
    assert reloaded.is_done("k1")
    assert reloaded.status("k2") == PENDING_REVIEW
    assert reloaded.entries(PENDING_REVIEW).keys() == {"k2"}


def test_ledger_rejects_bad_status(tmp_path):
    ledger = Ledger(tmp_path, "x")
    with pytest.raises(ValueError):
        ledger.mark("k", "bogus")


def test_journal_append_and_read(tmp_path):
    j = Journal(tmp_path / "journal")
    j.append("invoice-once", "测试消息")
    j.append("scan-once", "第二条")
    content = j.read_recent(days=1)
    assert "invoice-once" in content and "第二条" in content
