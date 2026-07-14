"""Slice 2：扫描件归档。"""

from legal_assistant.journal import NullJournal
from legal_assistant.scans import classify_file, run_scan_once


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_classify_by_filename(cfg):
    inbox = cfg.paths["scan_inbox"]
    assert classify_file(_touch(inbox / "委托代理合同-张三.pdf"), cfg.scan) == "合同文件"
    assert classify_file(_touch(inbox / "律师函20260101.pdf"), cfg.scan) == "诉讼函件"
    assert classify_file(_touch(inbox / "dzfp_12345.pdf"), cfg.scan) == "财务相关"


def test_trash_and_review(cfg):
    inbox = cfg.paths["scan_inbox"]
    assert classify_file(_touch(inbox / "合同test.pdf"), cfg.scan) == "临时垃圾箱"  # 垃圾优先
    # 纯数字名、无文本层 → 待人工复核
    assert classify_file(_touch(inbox / "202508211755765628586.pdf"), cfg.scan) == "待人工复核"


def test_run_scan_once_moves_files(cfg):
    inbox = cfg.paths["scan_inbox"]
    _touch(inbox / "聘用协议.pdf")
    _touch(inbox / "判决书2026.jpg")
    _touch(inbox / "999999.png")          # → 待人工复核
    _touch(inbox / "副本-合同.pdf")        # → 临时垃圾箱
    _touch(inbox / "notes.txt")           # 非文档后缀，不动
    r = run_scan_once(cfg, NullJournal())
    assert len(r.moved) == 2 and len(r.review) == 1 and len(r.trash) == 1
    assert (inbox / "合同文件" / "聘用协议.pdf").exists()
    assert (inbox / "诉讼函件" / "判决书2026.jpg").exists()
    assert (inbox / "待人工复核" / "999999.png").exists()
    assert (inbox / "临时垃圾箱" / "副本-合同.pdf").exists()
    assert (inbox / "notes.txt").exists()


def test_no_overwrite_suffix(cfg):
    inbox = cfg.paths["scan_inbox"]
    _touch(inbox / "合同文件" / "合同A.pdf", b"already-there")
    _touch(inbox / "合同A.pdf", b"new-one")
    run_scan_once(cfg, NullJournal())
    assert (inbox / "合同文件" / "合同A.pdf").read_bytes() == b"already-there"
    assert (inbox / "合同文件" / "合同A_1.pdf").read_bytes() == b"new-one"


def test_second_run_skips_sorted_dirs(cfg):
    inbox = cfg.paths["scan_inbox"]
    _touch(inbox / "聘用协议.pdf")
    run_scan_once(cfg, NullJournal())
    r2 = run_scan_once(cfg, NullJournal())  # 已归档的分类目录不再动
    assert not r2.moved and not r2.review and not r2.trash


def test_folder_as_package(cfg):
    inbox = cfg.paths["scan_inbox"]
    _touch(inbox / "张三合同扫描包" / "p1.jpg")
    r = run_scan_once(cfg, NullJournal())
    assert (inbox / "合同文件" / "张三合同扫描包" / "p1.jpg").exists()
    assert len(r.moved) == 1


def test_dry_run_moves_nothing(cfg):
    inbox = cfg.paths["scan_inbox"]
    _touch(inbox / "聘用协议.pdf")
    r = run_scan_once(cfg, NullJournal(), dry_run=True)
    assert len(r.moved) == 1
    assert (inbox / "聘用协议.pdf").exists()
    assert not (inbox / "合同文件").exists()
