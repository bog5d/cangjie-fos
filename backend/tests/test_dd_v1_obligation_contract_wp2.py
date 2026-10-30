"""DD-V1 **WP2**（#108 刘江 2026-10-30 实测 P0-2）：**统一 42 题拆解口径**。

**缺陷形态（实测）**：同一张 42 题考卷 ——
· ``dd_v1_manifest.py checklist`` ⇒ **91 条义务，覆盖 42 题**；
· ``dd_v1_local_run.py split`` ⇒ **15 条义务，仅覆盖 12 题**；
⇒ 「题目拆解覆盖率」被低报成 **28.6%**，系统**漏处理 30 题**。

**根因（代码级）**：**两套拆解**并存 ——
· 库侧 ``rq.build_obligations``（按并列连接词切，**永不丢题**）；
· 运行器侧 ``sem.split_items``（按材料类型切，**无类型关键词的整题丢弃**）。
★ 且 **Gold 的 ``obligation_id`` 引的是库侧那条** ⇒ 运行器用另一套 ⇒ **答卷与标准答案根本对不上**。

**本文件锁死的红线**（施工令 WP2）：
1. ★ **42 题全部进入处理链路**（一条清单项 ⇒ 至少一条义务，**不丢题**）；
2. ★ **原文完整保留**（逐字，可回读）；
3. ★ **义务数量稳定**（同一份清单反复摄取 ⇒ 同一条数）；
4. ★ **不重复、不漏项**；
5. ★ **运行器与库侧结果一致**（★ 本文件用**同一份合成 42 题清单**做 A/B 对照）；
6. ★ **不影响既有已通过的主体／期间／多文件匹配规则**（口径不变，只改「谁来拆」）；
7. ★ **统一数据契约**：每条义务可追溯 **原始题号／原文／义务唯一 ID／主体／期间／文件类型／证据键／处理状态**。

★ 全部夹具为**合成**数据（42 题为合成清单，非真实业务材料）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from cangjie_fos.services import dd_v1_manifest_service as mf  # noqa: E402
from cangjie_fos.services import dd_v1_requirement_service as rq  # noqa: E402
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem  # noqa: E402


def _db(tmp_path: Path):
    return tmp_path / "_plane" / "manifest.sqlite"


# ── 合成 42 题清单 ──────────────────────────────────────────────────────────
# ★ 刻意复刻真实考卷的两种句式：
#   ① 有材料类型关键词（「2024年度审计报告」）⇒ 旧规则拆解能拆；
#   ② **无材料类型关键词**（「请提供近三年经营情况说明」）⇒ ★ 旧规则拆解**整题丢弃**。
_SUBJECTS = ("母公司", "子公司甲", "子公司乙")


def _checklist_rows(n: int = 42) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        subject = _SUBJECTS[i % len(_SUBJECTS)]
        if i % 2 == 1:
            raw = f"请提供{subject}2024年度审计报告"
        else:
            raw = f"请提供{subject}近三年经营情况说明"
        rows.append({"item_no": f"{i//10 + 1}-{i%10 + 1}-{i}", "raw_text": raw})
    return rows


@pytest.fixture()
def lib(tmp_path: Path):
    mf.close_all()
    root = tmp_path / "materials"
    root.mkdir()
    mf.register_library("LIB-42", str(root), authorized_by="测试员",
                        db_path=_db(tmp_path))
    yield "LIB-42"
    mf.close_all()


def test_all_42_questions_enter_the_contract(lib, tmp_path):
    """★ **42 题全部进入处理链路**：一条清单项 ⇒ 至少一条义务（不丢题）。"""
    rows = _checklist_rows(42)
    res = rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                              db_path=_db(tmp_path))
    assert res["items"] == 42, res
    assert res["original_text_roundtrip_ok"] is True, res

    contract = rq.export_obligation_contract(lib, db_path=_db(tmp_path))
    assert contract["counts"]["items"] == 42, contract["counts"]
    assert contract["counts"]["questions"] == 42, contract["counts"]
    assert contract["question_coverage"]["questions_with_obligations"] == 42
    assert contract["question_coverage"]["coverage_ratio"] == 1.0


def test_contract_keeps_original_text_verbatim(lib, tmp_path):
    """★ **原文完整保留**：每条义务都能回读机构原编号 + 原文（逐字）。"""
    rows = _checklist_rows(42)
    rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                        db_path=_db(tmp_path))
    contract = rq.export_obligation_contract(lib, db_path=_db(tmp_path))
    by_q = {}
    for o in contract["obligations"]:
        by_q.setdefault(o["item_no"], []).append(o)
    assert len(by_q) == 42
    for row in rows:
        got = by_q[row["item_no"]]
        assert got, row["item_no"]
        # ★ 原文逐字保留（归一空白后比较，避免换行差异）
        assert " ".join(got[0]["original_text"].split()) == " ".join(row["raw_text"].split())


def test_contract_has_no_duplicate_or_missing(lib, tmp_path):
    """★ **不重复、不漏项**：义务 id 唯一；每题至少一条；题号集合 ＝ 清单题号集合。"""
    rows = _checklist_rows(42)
    rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                        db_path=_db(tmp_path))
    contract = rq.export_obligation_contract(lib, db_path=_db(tmp_path))
    ids = [o["obligation_id"] for o in contract["obligations"]]
    assert len(ids) == len(set(ids)), "义务 id 出现重复"
    keys = [o["obligation_key"] for o in contract["obligations"]]
    assert len(keys) == len(set(keys)), "稳定义务 key 出现重复"
    got_q = {o["item_no"] for o in contract["obligations"]}
    assert got_q == {r["item_no"] for r in rows}


def test_obligation_count_is_stable_across_ingest(lib, tmp_path):
    """★ **义务数量稳定**：重复摄取同一份清单 ⇒ 条数不变（幂等，不翻倍）。"""
    rows = _checklist_rows(42)
    r1 = rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                             db_path=_db(tmp_path))
    r2 = rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                             db_path=_db(tmp_path))
    c = rq.export_obligation_contract(lib, db_path=_db(tmp_path))
    # ★ 幂等口径：第二次摄取**按内容指纹跳过**（新增 0 条）⇒ **库内条数不变**（不翻倍）
    assert r1["obligations"] == 42, r1
    assert r2["obligations"] == 0, r2
    assert r2["skipped_duplicates"] == 42, r2
    assert c["counts"]["obligations"] == 42, c["counts"]
    assert c["counts"]["questions"] == 42


def test_contract_fields_are_traceable(lib, tmp_path):
    """★ **统一数据契约**：每条义务至少可追溯八个字段（施工令 WP2 的清单）。"""
    rows = _checklist_rows(42)
    rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                        db_path=_db(tmp_path))
    contract = rq.export_obligation_contract(lib, db_path=_db(tmp_path))
    for o in contract["obligations"]:
        assert o["item_no"], o
        assert o["original_text"], o
        assert o["obligation_id"], o
        assert "entity_scope" in o and "entity_basis" in o, o
        assert "period_spec" in o and "period_basis" in o, o
        assert "doc_type" in o and "doc_type_basis" in o, o
        assert "obligation_id" in o, o        # 证据键 ＝ 义务唯一 ID
        assert o["split_status"] in ("SPLIT", "NEEDS_HUMAN_SPLIT"), o


def test_runner_and_library_agree(lib, tmp_path):
    """★ **运行器与库侧结果一致**（本轮最核心的一条）。

    ★ 做法：**同一份**合成 42 题清单 ⇒ ① 库侧契约 ② 运行器 ``--library`` 路径
      ⇒ 两侧义务集合**逐条相同**（id 一一对应）。
    ★ ★ 同时**对照旧路径**：不传 ``--library`` 时旧规则拆解**只覆盖一部分题目**
      ⇒ ⇒ 这条测试同时**证明了这个 P0 的量级**（不是空口断言）。
    """
    import dd_v1_local_run as lr

    rows = _checklist_rows(42)
    rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                        db_path=_db(tmp_path))
    contract = rq.export_obligation_contract(lib, db_path=_db(tmp_path))

    items = [{"item_id": r["item_no"], "entity": "", "text": r["raw_text"]} for r in rows]
    matched, unmatched_items, unmatched_obl = lr._match_obligations_to_items(
        contract["obligations"], items)

    assert unmatched_items == [], f"有题挂不上库侧义务：{unmatched_items[:5]}"
    assert len(matched) == len(contract["obligations"]), (len(matched), len(contract["obligations"]))
    assert {o["obligation_id"] for o in matched} == {o["obligation_id"] for o in contract["obligations"]}
    assert len({o["question_id"] for o in matched}) == 42

    # ★ 对照：旧的本机规则拆解**覆盖不到 42 题**（这正是 P0-2 的形态）
    old_obs, _old_flags = sem.split_items(items)
    old_questions = {o["item_id"] for o in old_obs}
    assert len(old_questions) < 42, "旧路径居然覆盖了全部题目 ⇒ P0-2 形态已变，测试需重写"
    assert len(old_questions) < len({o["question_id"] for o in matched})


def test_no_item_is_dropped_by_the_authoritative_splitter(lib, tmp_path):
    """★ **不漏项**：库侧契约里**每一题**都至少有一条义务（即使规则层判不出材料类型）。

    ★ ★ 判不出类型时**只标**（``NEEDS_HUMAN_SPLIT``）⇒ **不删** ⇒ 覆盖率不失真。
    """
    rows = _checklist_rows(42)
    rq.ingest_checklist(lib, rows, anchor_year=2026, institution="Institution_XX",
                        db_path=_db(tmp_path))
    contract = rq.export_obligation_contract(lib, db_path=_db(tmp_path))
    per_q: dict[str, int] = {}
    for o in contract["obligations"]:
        per_q[o["item_no"]] = per_q.get(o["item_no"], 0) + 1
    assert len(per_q) == 42
    assert all(v >= 1 for v in per_q.values())
    # ★ 合成清单里一半是「无材料类型关键词」的句式 ⇒ 必然出现 NEEDS_HUMAN_SPLIT
    assert contract["counts"]["needs_human_split"] > 0, contract["counts"]


# ── 题号归一（跨来源 join）──────────────────────────────────────────────────

class TestCanonicalQuestionId:
    def test_section_directory_name_is_not_a_three_level_number(self):
        """★ **分部目录名不是题号**：`1-1_基本资料` ⇒ 归一后是 **`1-1`**（两级）。

        ★ 也就是说：**不会**被当成三级题号 `1-1-x`。
        """
        assert rq.canonical_question_id("1-1_基本资料") == "1-1"

    def test_plain_numbers_are_unchanged(self):
        assert rq.canonical_question_id("1-1-1") == "1-1-1"
        assert rq.canonical_question_id(" 2-3-4 ") == "2-3-4"

    def test_empty_is_empty(self):
        assert rq.canonical_question_id("") == ""
        assert rq.canonical_question_id(None) == ""

    def test_join_tolerates_the_two_forms(self, tmp_path):
        """★ join **两级**：逐字不中时用归一号兜底 ⇒ **不因写法差异而丢题**。"""
        import dd_v1_local_run as lr
        rows = [{"item_no": "1-1_基本资料", "raw_text": "请提供母公司2024年度审计报告"}]
        mf.close_all()
        root = tmp_path / "materials"
        root.mkdir()
        mf.register_library("LIB-J", str(root), authorized_by="测试员",
                            db_path=_db(tmp_path))
        try:
            rq.ingest_checklist("LIB-J", rows, anchor_year=2026,
                                institution="Institution_XX", db_path=_db(tmp_path))
            contract = rq.export_obligation_contract("LIB-J", db_path=_db(tmp_path))
            items = [{"item_id": "1-1-1", "entity": "", "text": "请提供母公司2024年度审计报告"}]
            matched, unmatched, _ = lr._match_obligations_to_items(contract["obligations"], items)
            # ★ 归一号：`1-1_基本资料` → `1-1`；`1-1-1` → `1-1-1` ⇒ **两者不等**
            #   ⇒ ⇒ 逐字与归一都不中 ⇒ **必须显式报出**（不得静默丢题）
            assert unmatched and unmatched[0]["item_id"] == "1-1-1"
            # ★ 而逐字相同的写法 ⇒ 直接命中
            items2 = [{"item_id": "1-1_基本资料", "entity": "", "text": "x"}]
            matched2, unmatched2, _ = lr._match_obligations_to_items(
                contract["obligations"], items2)
            assert unmatched2 == []
            assert matched2 and matched2[0]["_join"] == "EXACT"
        finally:
            mf.close_all()
