"""DD-V1 清单自证防护（W8 / A2-1）测试。

缺陷背景：材料库里混着**机构下发的尽调清单**（清单 / 资料清单 / 尽职调查清单 /
授信资料清单 / 尽调清单 ...）。清单是**考题**，不是**证据** —— 清单文件一旦进入
材料库，就会出现「用考题证明自己交了考题」（清单自证）。案例A 实测自证率 12%，
目标 0%。

本文件守住的五件事：

1. 清单文件**不进材料库**（埋在子目录里的清单同样被拦下）；
2. 排除是**规则驱动**的，且规则集可在**运行时用 JSON 文件整体覆盖**；
3. 排除**可审计**：结果里只有计数与规则 id，**不含任何真实文件名**；
4. ``rule_hit_but_not_excluded_count`` **恒为 0**，且不是空转的数字；
5. **既有证据不被误杀**（本改动只减材料，不得让判定变乐观）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_manifest_service as mf


# ── 隔离 ────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个测试独立的 Manifest 库 + 独立 Data Plane + 独立规则集缓存。"""
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.delenv(mf.CHECKLIST_RULES_ENV, raising=False)
    mf._RULES_CACHE.clear()
    mf.close_all()
    yield
    mf.close_all()
    mf._RULES_CACHE.clear()


def _mk_library(tmp_path: Path) -> tuple[str, Path]:
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(
        "lib1", str(root), authorized_by="波总", display_name="lib1",
        db_path=tmp_path / "_dp" / "manifest.sqlite",
    )
    return "lib1", root


def _db(tmp_path: Path) -> Path:
    return tmp_path / "_dp" / "manifest.sqlite"


def _write_rules(tmp_path: Path, monkeypatch, data: dict) -> Path:
    """写一份 JSON 规则文件并用环境变量挂上去（运行时覆盖内置规则）。"""
    p = tmp_path / "checklist_rules.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(mf.CHECKLIST_RULES_ENV, str(p))
    return p


def _live_names(mf_, lib: str, db) -> set[str]:
    return {e["file_name"] for e in mf_.list_manifest(lib, db_path=db)}


# ── 1. 清单不进材料库 ──────────────────────────────────────────────────────
def test_checklist_file_never_enters_corpus(tmp_path):
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.txt").write_text("序号\t材料名称\t是否提供\n1\t营业执照\t是\n", encoding="utf-8")
    (root / "审计报告2024.pdf").write_text("审计正文", encoding="utf-8")
    (root / "营业执照.pdf").write_text("执照正文", encoding="utf-8")

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert _live_names(mf, lib, _db(tmp_path)) == {"审计报告2024.pdf", "营业执照.pdf"}, \
        "清单是考题不是证据，绝不能进材料库"
    assert res["added"] == 2
    assert res["excluded_checklist_count"] == 1
    assert res["rule_hit_but_not_excluded_count"] == 0
    assert sum(res["excluded_by_rule"].values()) == 1
    assert len(res["excluded_by_rule"]) == 1, "只应命中一条（优先级最靠前的）规则"


def test_checklist_buried_in_subfolder_is_caught(tmp_path):
    """清单不都在库根：埋在任意层子目录里的清单同样必须被拦下。"""
    lib, root = _mk_library(tmp_path)
    deep = root / "2024" / "附件" / "尽调资料清单"
    deep.mkdir(parents=True)
    (deep / "机构回执.pdf").write_text("回执正文", encoding="utf-8")
    (root / "2024" / "checklist").mkdir(parents=True)
    (root / "2024" / "checklist" / "notes.md").write_text("考题备注", encoding="utf-8")
    (root / "2024" / "审计报告.pdf").write_text("正文", encoding="utf-8")

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert _live_names(mf, lib, _db(tmp_path)) == {"审计报告.pdf"}
    assert res["excluded_checklist_count"] == 2, "子目录里的清单必须被排除"
    assert res["rule_hit_but_not_excluded_count"] == 0
    assert "CL-001-path-segment" in res["excluded_by_rule"], \
        "目录名命中应归到 path_segment 规则"


def test_listed_naming_variants_are_all_excluded(tmp_path):
    """材料库里真实出现过的几种叫法都要覆盖到。"""
    lib, root = _mk_library(tmp_path)
    names = ["清单.txt", "资料清单.txt", "尽职调查清单.txt", "授信资料清单.txt", "尽调清单.txt"]
    for n in names:
        (root / n).write_text("考题", encoding="utf-8")
    (root / "审计报告2023.pdf").write_text("正文", encoding="utf-8")

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == len(names)
    assert _live_names(mf, lib, _db(tmp_path)) == {"审计报告2023.pdf"}


# ── 2. 证据不被误杀（本改动只许减材料，不许让判定变乐观）──────────────────
def test_evidence_files_are_not_excluded(tmp_path):
    lib, root = _mk_library(tmp_path)
    keep = [
        "审计报告2023.pdf", "财务报表2024.pdf", "营业执照.pdf", "公司章程.pdf",
        "资产清单.pdf", "债权清单.pdf", "借款清单.pdf", "审计合同.pdf",
    ]
    for n in keep:
        (root / n).write_text("证据正文", encoding="utf-8")

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 0, \
        "「资产清单」这类合成词是证据，不能当考题误杀"
    assert _live_names(mf, lib, _db(tmp_path)) == set(keep)
    assert res["added"] == len(keep)


def test_evidence_text_file_is_not_sniffed_as_checklist(tmp_path):
    """正文嗅探只认「供给状态列 + 表头列」，普通正文不得被误判。"""
    lib, root = _mk_library(tmp_path)
    (root / "存货明细.txt").write_text(
        "序号\t材料名称\t数量\n1\t钢筋\t20\n2\t水泥\t100\n", encoding="utf-8"
    )
    (root / "访谈记录.txt").write_text("访谈内容：对方介绍了经营情况。", encoding="utf-8")

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 0
    assert _live_names(mf, lib, _db(tmp_path)) == {"存货明细.txt", "访谈记录.txt"}


# ── 3. 审计痕迹：只给计数与规则 id，不给文件名 ────────────────────────────
def test_exclusion_trace_contains_no_real_file_names(tmp_path, caplog):
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.txt").write_text("考题", encoding="utf-8")
    (root / "子目录" / "尽调资料清单").mkdir(parents=True)
    (root / "子目录" / "尽调资料清单" / "机构回执.pdf").write_text("回执", encoding="utf-8")
    (root / "审计报告2024.pdf").write_text("正文", encoding="utf-8")

    with caplog.at_level(logging.DEBUG):
        res = mf.build_manifest(lib, db_path=_db(tmp_path))

    blob = json.dumps(res, ensure_ascii=False, default=str)
    for needle in ("尽调清单", "机构回执", "审计报告2024", "子目录"):
        assert needle not in blob, f"排除结果里不得出现真实文件名：{needle}"
        assert needle not in caplog.text, f"排除日志里不得出现真实文件名：{needle}"

    # 计数与规则 id 必须在，审计要能读数。
    assert res["excluded_checklist_count"] == 2
    assert res["excluded_by_rule"]
    assert all(isinstance(k, str) and k.startswith("CL-") for k in res["excluded_by_rule"])


def test_manifest_summary_exposes_counters(tmp_path):
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.txt").write_text("考题", encoding="utf-8")
    (root / "审计报告2024.pdf").write_text("正文", encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))

    summary = mf.manifest_summary(lib, db_path=_db(tmp_path))

    assert summary["excluded_checklist_count"] == 1
    assert summary["rule_hit_but_not_excluded_count"] == 0
    assert summary["excluded_by_rule"]
    assert summary["checklist_exclusion"]["ruleset_version"]
    assert summary["total"] == 1, "材料库里只该剩证据"


def test_run_record_exposes_exclusion_block(tmp_path):
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.txt").write_text("考题", encoding="utf-8")
    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    run = mf.get_run(res["run_id"], db_path=_db(tmp_path))
    assert run is not None
    block = run["checklist_exclusion"]
    assert block["excluded_checklist_count"] == 1
    assert block["rule_hit_but_not_excluded_count"] == 0

    report = mf.get_checklist_exclusion_report(library_id=lib, db_path=_db(tmp_path))
    assert report["excluded_checklist_count"] == 1


# ── 4. rule_hit_but_not_excluded_count 恒为 0，且不是空转 ───────────────────
def test_counter_is_zero_and_actually_live(tmp_path, monkeypatch):
    """计数器必须真的在数东西：把排除动作打掉，它就必须变成非 0。

    做法：先用一条「什么都不匹配」的规则集把清单**正常入库**（模拟历史轮次
    已经把清单收进材料库），再切回内置规则集重扫 —— 此时清单命中规则，
    排除动作若失效，清单就会留在材料库里，计数器必须报出来。
    """
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.txt").write_text("考题", encoding="utf-8")

    # 第 1 轮：规则集什么都不匹配 ⇒ 清单被当作普通材料入库。
    noop = _write_rules(tmp_path, monkeypatch, {
        "ruleset_version": "test-noop",
        "rules": [{"rule_id": "X-001", "priority": 10, "kind": "filename_keyword",
                   "patterns": ["__NEVER_MATCH__"]}],
    })
    mf.build_manifest(lib, mode="full", db_path=_db(tmp_path))
    assert _live_names(mf, lib, _db(tmp_path)) == {"尽调清单.txt"}, "前置条件：清单已入库"

    # 第 2 轮：切回内置规则 ⇒ 清单被命中并赶出材料库。
    monkeypatch.delenv(mf.CHECKLIST_RULES_ENV, raising=False)
    mf._RULES_CACHE.clear()
    res = mf.build_manifest(lib, mode="full", db_path=_db(tmp_path))
    assert res["excluded_checklist_count"] == 1
    assert res["rule_hit_but_not_excluded_count"] == 0
    assert _live_names(mf, lib, _db(tmp_path)) == set(), "历史入库的清单必须退出材料库"

    # 第 3 轮：先让它回到「在库里」的状态，再把排除动作打掉 ⇒ 计数器必须报警
    #（证明它不是摆设：命中规则却仍在材料库，必须被数出来）。
    monkeypatch.setenv(mf.CHECKLIST_RULES_ENV, str(noop))
    mf._RULES_CACHE.clear()
    mf.build_manifest(lib, mode="full", db_path=_db(tmp_path))
    assert _live_names(mf, lib, _db(tmp_path)) == {"尽调清单.txt"}

    monkeypatch.delenv(mf.CHECKLIST_RULES_ENV, raising=False)
    mf._RULES_CACHE.clear()
    monkeypatch.setattr(mf, "_exclude_from_corpus", lambda *a, **kw: None)
    res3 = mf.build_manifest(lib, mode="full", db_path=_db(tmp_path))
    assert res3["rule_hit_but_not_excluded_count"] == 1, \
        "命中规则却仍在材料库 ⇒ 计数器必须报出来"


def test_exclusion_is_idempotent_across_runs(tmp_path):
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.txt").write_text("考题", encoding="utf-8")
    (root / "审计报告2024.pdf").write_text("正文", encoding="utf-8")

    first = mf.build_manifest(lib, mode="full", db_path=_db(tmp_path))
    second = mf.build_manifest(lib, mode="full", db_path=_db(tmp_path))

    assert first["excluded_checklist_count"] == 1
    assert second["excluded_checklist_count"] == 1, "重复扫描仍应识别并排除"
    assert second["rule_hit_but_not_excluded_count"] == 0
    assert second["added"] == 0 and second["unchanged"] == 1
    assert _live_names(mf, lib, _db(tmp_path)) == {"审计报告2024.pdf"}


def test_source_files_are_never_touched(tmp_path):
    """排除只作用于 Manifest，绝不删改客户原始文件。"""
    lib, root = _mk_library(tmp_path)
    p = root / "尽调清单.txt"
    p.write_text("考题正文", encoding="utf-8")
    before = p.stat().st_mtime_ns

    mf.build_manifest(lib, db_path=_db(tmp_path))

    assert p.exists(), "清单文件本身必须留在原处"
    assert p.stat().st_mtime_ns == before
    assert p.read_text(encoding="utf-8") == "考题正文"


# ── 5. 规则集可配置（运行时用 JSON 覆盖内置）─────────────────────────────
def test_ruleset_can_be_overridden_by_env_json(tmp_path, monkeypatch):
    lib, root = _mk_library(tmp_path)
    (root / "机构问卷.pdf").write_text("问卷正文", encoding="utf-8")
    (root / "尽调清单.pdf").write_text("考题", encoding="utf-8")
    (root / "审计报告2024.pdf").write_text("正文", encoding="utf-8")

    _write_rules(tmp_path, monkeypatch, {
        "ruleset_version": "custom-v1",
        "rules": [{"rule_id": "X-010-custom-name", "priority": 10,
                   "kind": "filename_keyword", "patterns": ["机构问卷"],
                   "description": "自定义口径：机构问卷也算考题"}],
    })

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 1
    assert list(res["excluded_by_rule"]) == ["X-010-custom-name"]
    assert res["checklist_rules"]["source"] == "env"
    assert res["checklist_rules"]["ruleset_version"] == "custom-v1"
    assert _live_names(mf, lib, _db(tmp_path)) == {"尽调清单.pdf", "审计报告2024.pdf"}, \
        "自定义规则集完全覆盖内置规则：内置口径下被排掉的「尽调清单」应当留在库里"


def test_custom_ruleset_can_use_extension_kind(tmp_path, monkeypatch):
    lib, root = _mk_library(tmp_path)
    (root / "数据.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (root / "数据.txt").write_text("a\tb\n1\t2\n", encoding="utf-8")

    _write_rules(tmp_path, monkeypatch, {
        "ruleset_version": "custom-ext",
        "rules": [{"rule_id": "X-020-ext", "priority": 10, "kind": "extension",
                   "extensions": [".tsv"]}],
    })

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 1
    assert list(res["excluded_by_rule"]) == ["X-020-ext"]
    assert _live_names(mf, lib, _db(tmp_path)) == {"数据.txt"}


def test_custom_ruleset_can_use_path_segment_kind(tmp_path, monkeypatch):
    lib, root = _mk_library(tmp_path)
    (root / "考题").mkdir()
    (root / "考题" / "a.pdf").write_text("正文", encoding="utf-8")
    (root / "证据").mkdir()
    (root / "证据" / "b.pdf").write_text("正文", encoding="utf-8")

    _write_rules(tmp_path, monkeypatch, {
        "ruleset_version": "custom-seg",
        "rules": [{"rule_id": "X-030-seg", "priority": 10, "kind": "path_segment",
                   "patterns": ["考题"]}],
    })

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 1
    assert _live_names(mf, lib, _db(tmp_path)) == {"b.pdf"}


def test_content_sniff_rule_catches_unnamed_table(tmp_path, monkeypatch):
    """名字里没有「清单」二字，但表头就是清单表 ⇒ 仍要排除。"""
    lib, root = _mk_library(tmp_path)
    (root / "第01批.txt").write_text(
        "序号\t材料名称\t是否提供\t备注\n1\t营业执照\t是\t\n2\t审计报告\t否\t补\n",
        encoding="utf-8",
    )
    (root / "会议纪要.txt").write_text("会议时间、地点、参会人。", encoding="utf-8")

    _write_rules(tmp_path, monkeypatch, {
        "ruleset_version": "custom-sniff",
        "rules": [{"rule_id": "X-040-sniff", "priority": 10, "kind": "content_sniff",
                   "extensions": [".txt"],
                   "require_all": [r"(是否提供|需提供)", r"(序号|编号|材料名称)"]}],
    })

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 1
    assert list(res["excluded_by_rule"]) == ["X-040-sniff"]
    assert _live_names(mf, lib, _db(tmp_path)) == {"会议纪要.txt"}


def test_priority_order_decides_which_rule_wins(tmp_path, monkeypatch):
    """同一文件命中多条规则时，必须由 priority 决定（结果确定、可复现）。"""
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.pdf").write_text("考题", encoding="utf-8")

    _write_rules(tmp_path, monkeypatch, {
        "ruleset_version": "custom-prio",
        "rules": [
            {"rule_id": "X-100-late", "priority": 90, "kind": "filename_keyword",
             "patterns": ["尽调清单"]},
            {"rule_id": "X-050-early", "priority": 5, "kind": "filename_keyword",
             "patterns": ["尽调清单"]},
        ],
    })

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert list(res["excluded_by_rule"]) == ["X-050-early"], "priority 小的先判、命中即止"
    assert res["excluded_checklist_count"] == 1


def test_broken_rules_file_falls_back_to_builtin(tmp_path, monkeypatch):
    """规则文件坏了 ⇒ 回退内置规则（排除不失效），并如实记录 load_error。"""
    lib, root = _mk_library(tmp_path)
    (root / "尽调清单.pdf").write_text("考题", encoding="utf-8")
    (root / "审计报告2024.pdf").write_text("正文", encoding="utf-8")

    p = tmp_path / "broken_rules.json"
    p.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv(mf.CHECKLIST_RULES_ENV, str(p))

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 1, "配置坏了也不能把清单放回材料库"
    assert res["checklist_rules"]["source"] == "builtin"
    assert res["checklist_rules"]["load_error"]
    assert _live_names(mf, lib, _db(tmp_path)) == {"审计报告2024.pdf"}


def test_ruleset_loader_is_deterministic_and_ordered():
    rules = mf.load_checklist_rules()
    ids = [r.rule_id for r in rules.rules]
    assert ids == sorted(ids, key=lambda rid: [r.priority for r in rules.rules
                                              if r.rule_id == rid][0])
    assert len(ids) == len(set(ids)), "规则 id 必须唯一"
    for r in rules.rules:
        assert r.rule_id and r.kind in mf._RULE_KINDS
        assert r.description, "每条规则都要有审计说明"


def test_classify_reports_rule_id_not_filename():
    """判定接口只返回规则 id 与类型，绝不返回文件名。"""
    rules = mf.load_checklist_rules()
    hit = mf.classify_checklist_file("材料/尽调清单.pdf", Path("材料/尽调清单.pdf"), rules)
    assert hit is not None
    rule_id, kind = hit
    # 「尽调清单」是强特征 ⇒ 命中优先级更靠前的 CL-002（确定性由 priority 决定）
    assert rule_id == "CL-002-exam-phrase-in-filename"
    assert kind == "filename_keyword"
    assert "清单" not in rule_id


def test_content_sniff_builtin_catches_list_table(tmp_path):
    """内置内容嗅探规则：表头像清单表的文件，即使名字没「清单」也要排除。"""
    lib, root = _mk_library(tmp_path)
    (root / "第一批.txt").write_text(
        "序号\t材料名称\t是否提供\n1\t营业执照\t是\n", encoding="utf-8"
    )
    (root / "审计报告2024.pdf").write_text("正文", encoding="utf-8")

    res = mf.build_manifest(lib, db_path=_db(tmp_path))

    assert res["excluded_checklist_count"] == 1
    assert "CL-004-checklist-table-header" in res["excluded_by_rule"]
    assert _live_names(mf, lib, _db(tmp_path)) == {"审计报告2024.pdf"}
