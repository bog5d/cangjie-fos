"""DD-V1 接线回归：多源主体识别 ＋ 候选分批扩展（本轮新接进真实组包链路）。

## 为什么要有这个文件

上一版把两个模块写好了、也测过了，但**生产链路零调用方**（只有它们自己的测试 import 它们）
⇒ 「多源主体认领」「候选触顶后分批扩展」在真实组包里**根本没生效**。
独立 Reviewer 第一轮就抓到这一点（`REVIEW-REPORT-PR86.md` §4 ④，判 `M03=PARTIAL`）。

本文件锁死的是**「接上了」这件事本身**：

- **正例**：材料目录**不携带法人级**（分类目录）时，多源识别能把主体认出来 ⇒ 主体维度不再是死路；
- **反例**：认不出就**认不出** ⇒ 绝不猜、绝不放行（判定与接线前一致）；
- **判别力**：把接线参数关掉 ⇒ 正例必须回到「认不出」⇒ 证明是这个接线在起作用，
  而不是「反正都会命中」。

## 敏感纪律

主体名属客户标识 ⇒ 本文件一律用**虚构简称**（甲科技有限责任公司/乙实业集团有限公司/丙公司…），
不出现任何真实客户名。

## 与既有口径的关系

★ 接线**只补位**：主口径（整段逐字相等）判「认不出（UNREGISTERED）」时才接管；
  主口径已判「命中 / 另一个法人」的**一律不动** ⇒ 既有六态口径与既有测试不变。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import (
    dd_v1_card_service as cs,
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
)


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _setup(tmp_path, files: dict[str, str], lib="lib1"):
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.register_library(lib, str(root), authorized_by="WIRING", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _register(tmp_path, lib, eid, name, relation="subsidiary"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _matches(tmp_path, obl_id):
    """从**持久化的留痕表**读（`dd_v1_matches`）——审计看的就是它。"""
    rows = ms._conn(_db(tmp_path)).execute(
        "SELECT file_id, entity_ok, deliverable, evidence FROM dd_v1_matches "
        "WHERE obligation_id=? ORDER BY rank", (obl_id,)).fetchall()
    return [dict(r) for r in rows]


def _ingest(tmp_path, lib, raw_text):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    return rq.list_obligations(lib, db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════════
# 一、多源主体识别：接线进真实组包链路（正反回归）
# ═══════════════════════════════════════════════════════════════════════════

#: 分类目录名（**不带法人级**）—— 这是 `#108` 实测的失败形态
#: ★ 主体名一律用**≥4 字的虚构全称**：多源模块有一道防误命中闸
#:   （`_MIN_FULLNAME_LEN`，短名不进「文件名命中」那一档）⇒ 测试名太短会**测不到东西**。
_CATEGORY_DIR = "审计报告"


def _two_entity_library(tmp_path):
    """两个登记主体 ＋ 一份「分类目录 + 文件名带登记全称」的材料 ＋ 一份无关材料。"""
    lib = _setup(tmp_path, {
        f"{_CATEGORY_DIR}/甲科技有限责任公司-2024年度审计报告.txt": "审计报告\n2024 年度审计报告正文",
        f"{_CATEGORY_DIR}/无名机构-2024年度审计报告.txt": "审计报告\n2024 年度审计报告正文",
    })
    _register(tmp_path, lib, "E1", "甲科技有限责任公司")
    _register(tmp_path, lib, "E2", "乙实业集团有限公司")
    return lib


def test_positive_filename_carries_registered_name_resolves_subject(tmp_path):
    """★ 正例：目录不带法人级，**文件名带登记全称** ⇒ 主体维度认得出 ⇒ 不再死路。"""
    lib = _two_entity_library(tmp_path)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]

    res = ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path))
    st = ms.get_status(obl["obligation_id"], db_path=_db(tmp_path))
    assert st is not None
    # ★ 主体维度**成为门槛**（有实证）⇒ 不再「主体维度不可判定」
    #   （最终 verdict 还受披露策略/可交付性影响 ⇒ 那一维不在本文件断言范围内）
    assert float(st["entity_cov"]) == 1.0, st
    assert "主体维度不可判定" not in str(st.get("missing_detail") or ""), st

    # ★ 留痕：是哪一档证据认出来的（机器可复核，从**持久化的留痕表**读）
    rows = _matches(tmp_path, obl["obligation_id"])
    assert rows, st
    joined = " ".join(str(r["evidence"] or "") for r in rows)
    assert "多源识别" in joined, joined
    assert "REGISTRY_DISPLAY_NAME" in joined, joined
    assert res["obligations"] == 1


def test_negative_unknown_material_stays_unresolved(tmp_path):
    """★ 反例：文件名/正文都认不出 ⇒ **仍然认不出** ⇒ 不得判命中（不许猜）。"""
    lib = _setup(tmp_path, {
        f"{_CATEGORY_DIR}/无名机构-2024年度审计报告.txt": "审计报告\n2024 年度审计报告正文",
    })
    _register(tmp_path, lib, "E1", "甲科技有限责任公司")
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]

    ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path))
    st = ms.get_status(obl["obligation_id"], db_path=_db(tmp_path))
    assert st is not None
    # ★ 认不出 ⇒ 主体维度**仍不可判定**（保留不确定状态，不猜、不放行）
    assert float(st["entity_cov"]) == 0.0, st
    # ★ 文案口径随闸不同而不同（「主体维度不可判定」/「主体未登记」）⇒ 断语义不断原句
    assert "未登记" in str(st.get("missing_detail") or ""), st
    rows = _matches(tmp_path, obl["obligation_id"])
    joined = " ".join(str(r["evidence"] or "") for r in rows)
    assert "多源识别" not in joined, joined
    assert all(int(r["entity_ok"] or 0) == 0 for r in rows), rows


def test_body_text_carries_registered_name_resolves_subject(tmp_path):
    """★ 正文命中登记全称 ⇒ 也能认出来（BODY_TEXT 那一档）。"""
    lib = _setup(tmp_path, {
        f"{_CATEGORY_DIR}/编号007-年度审计报告.txt":
            "审计报告\n甲科技有限责任公司 2024 年度审计报告正文",
    })
    _register(tmp_path, lib, "E1", "甲科技有限责任公司")
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]

    ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path))
    st = ms.get_status(obl["obligation_id"], db_path=_db(tmp_path))
    assert st is not None
    assert float(st["entity_cov"]) == 1.0, st
    assert "主体维度不可判定" not in str(st.get("missing_detail") or ""), st
    rows = _matches(tmp_path, obl["obligation_id"])
    joined = " ".join(str(r["evidence"] or "") for r in rows)
    assert "BODY_TEXT" in joined, joined


def test_confirmed_map_outranks_filename(tmp_path):
    """★ 人工确认映射（`HUMAN_CONFIRMED`）**优先于**文件名/正文那一档。"""
    lib = _setup(tmp_path, {
        f"{_CATEGORY_DIR}/甲科技有限责任公司-2024年度审计报告.txt": "审计报告\n2024 年度审计报告正文",
        f"{_CATEGORY_DIR}/乙实业集团有限公司-2024年度审计报告.txt": "审计报告\n2024 年度审计报告正文",
    })
    _register(tmp_path, lib, "E1", "甲科技有限责任公司")
    _register(tmp_path, lib, "E2", "乙实业集团有限公司")
    obl = _ingest(tmp_path, lib, "乙实业集团有限公司：提供 2024 年度审计报告")[0]

    # 人工确认：把「乙实业集团有限公司」那一份判给甲科技有限责任公司 ⇒ 判定必须跟着人工确认走
    obl_rows = rq.list_obligations(lib, db_path=_db(tmp_path))
    obl_id = obl_rows[0]["obligation_id"]
    files = mf.build_manifest(lib, db_path=_db(tmp_path))  # 取一遍 manifest
    manifest_rows = ms._conn(_db(tmp_path)).execute(
        "SELECT file_id, rel_path, file_name FROM dd_v1_manifest").fetchall()
    target = [r for r in manifest_rows if "乙实业集团有限公司" in str(r["file_name"])]
    assert target, files
    confirmed = {str(target[0]["file_id"]): {"entity": "甲科技有限责任公司", "entity_id": "E1",
                                              "source_ref": "人工确认"}}

    ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path),
                     confirmed_map=confirmed)
    st = ms.get_status(obl_id, db_path=_db(tmp_path))
    assert st is not None
    rows = _matches(tmp_path, obl_id)
    joined = " ".join(str(r["evidence"] or "") for r in rows)
    assert "HUMAN_CONFIRMED" in joined, joined


def test_judgement_without_wiring_stays_unresolved(tmp_path):
    """★ **判别力**：把多源补位关掉 ⇒ 正例必须回到「认不出」。

    ⇒ 证明是这个接线在起作用（而不是「反正都会命中」）。
    """
    lib = _two_entity_library(tmp_path)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    obl_id = obl["obligation_id"]

    # 直接走 evaluate_file，不给 multi_source_subject ⇒ 等价于「没接线」
    card = cs.get_card(
        str(ms._conn(_db(tmp_path)).execute(
            "SELECT file_id FROM dd_v1_manifest ORDER BY file_id LIMIT 1").fetchone()[0]),
        db_path=_db(tmp_path))
    mrow = dict(ms._conn(_db(tmp_path)).execute(
        "SELECT * FROM dd_v1_manifest ORDER BY file_id LIMIT 1").fetchone())
    scope = rq.resolve_entities(lib, "entity_hint:甲科技有限责任公司", None, _db(tmp_path))
    auth = rq.resolve_entities(lib, "group_and_subs", None, _db(tmp_path))
    ev = ms.evaluate_file(obl, card, mrow, scope, authority_entities=auth)
    assert ev["entity_state"] == ms.SUBJECT_UNREGISTERED, ev
    assert ev["entity_ok"] == 0, ev
    # 同一个材料，接上补位后应当认得出
    ev2 = ms.evaluate_file(obl, card, mrow, scope, authority_entities=auth,
                           multi_source_subject=ms.resolve_subject_multi_source(
                               mrow, card, scope, auth, {}, body_text=""))
    assert ev2["entity_state"] == ms.SUBJECT_MATCHED, ev2
    assert ev2["entity_ok"] == 1, ev2
    assert obl_id


def test_primary_other_legal_is_not_overridden(tmp_path):
    """★ 主口径判「另一个已登记法人」时，多源补位**不得**覆盖它。

    ★ 对抗构造：目录名逐字等于「乙实业集团有限公司」（⇒ 主口径判 OTHER_LEGAL），
      而**文件名里出现「甲科技有限责任公司」**（⇒ 多源那一档会说甲科技有限责任公司）⇒
      若补位覆盖了主口径，就会把「乙实业集团有限公司的材料」误判成「甲科技有限责任公司的材料」⇒ 必须不覆盖。
    """
    lib = _setup(tmp_path, {
        "乙实业集团有限公司/甲科技有限责任公司-2024年度审计报告.txt": "审计报告\n2024 年度审计报告正文",
    })
    _register(tmp_path, lib, "E1", "甲科技有限责任公司")
    _register(tmp_path, lib, "E2", "乙实业集团有限公司")
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    obl_id = obl["obligation_id"]

    conn = ms._conn(_db(tmp_path))
    row = conn.execute("SELECT * FROM dd_v1_manifest ORDER BY file_id LIMIT 1").fetchone()
    mrow = dict(row)
    card = cs.get_card(str(mrow["file_id"]), db_path=_db(tmp_path))
    scope = rq.resolve_entities(lib, "entity_hint:甲科技有限责任公司", None, _db(tmp_path))
    auth = rq.resolve_entities(lib, "group_and_subs", None, _db(tmp_path))
    ev = ms.evaluate_file(obl, card, mrow, scope, authority_entities=auth,
                          multi_source_subject=lambda: ms.resolve_subject_multi_source(
                              mrow, card, scope, auth, {}, body_text=""))
    assert ev["entity_state"] == ms.SUBJECT_OTHER_LEGAL, ev
    assert ev["entity_ok"] == 0, ev
    assert obl_id


# ═══════════════════════════════════════════════════════════════════════════
# 二、候选分批扩展：接线进实际检索流程（>20 候选）
# ═══════════════════════════════════════════════════════════════════════════


def _many_materials_library(tmp_path, n=30, lib="lib2"):
    """造 n 份同类型材料；**正确答案故意排在召回窗口之外**（第 26 位）。"""
    files = {}
    for i in range(n):
        # 文件名里带序号；正文只含类型词（召回靠 doc_type 词）
        files[f"{_CATEGORY_DIR}/材料{i:02d}-2024年度审计报告.txt"] = (
            f"审计报告\n2024 年度审计报告正文 第{i}号")
    lib = _setup(tmp_path, files, lib=lib)
    _register(tmp_path, lib, "E1", "甲科技有限责任公司")
    return lib


def _designate_deep_candidate(tmp_path, lib, obl_id, depth=25):
    """把「排在第 depth 位」的那份材料定为**只有扩窗才看得到**的那一份。"""
    obl = dict(ms._conn(_db(tmp_path)).execute(
        "SELECT * FROM dd_v1_obligations WHERE obligation_id=?", (obl_id,)).fetchone())
    cands, capped, _terms, trunc = ms._recall_candidates(obl, lib, 200, _db(tmp_path))
    assert len(cands) > depth, f"召回池只有 {len(cands)} 份，构不出 >20 的场景"
    deep_id = cands[depth]["file_id"]
    first20 = {c["file_id"] for c in cands[:20]}
    assert deep_id not in first20
    return deep_id, len(cands)


def test_expansion_finds_candidate_beyond_first_window(tmp_path):
    """★ 候选窗口 20 看不到的那份，**分批扩展**后看得到 ⇒ 结论跟着变。"""
    lib = _many_materials_library(tmp_path)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    obl_id = obl["obligation_id"]
    deep_id, pool = _designate_deep_candidate(tmp_path, lib, obl_id)
    assert pool > 20

    # 第一遍（cap=20）：看不到那份
    st1 = ms.match_obligation(lib, obl_id, candidate_cap=20, db_path=_db(tmp_path))
    assert int(st1.get("capped") or 0) == 1, st1
    assert int(st1.get("truncated_candidate_count") or 0) > 0, st1
    ids1 = {r["file_id"] for r in _matches(tmp_path, obl_id)}
    assert deep_id not in ids1

    # 分批扩展：窗口放大 ⇒ 看得到
    res = ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path))
    exp = res["candidate_expansion"]
    assert exp["expanded_obligations"] == 1, exp
    row = exp["obligations"][0]
    assert row["candidates_checked"] > 20, row
    assert row["stop_reason"] in ("VERDICT_STABLE", "BUDGET_EXHAUSTED", "STEPS_EXHAUSTED"), row
    ids2 = {r["file_id"] for r in _matches(tmp_path, obl_id)}
    assert deep_id in ids2, "扩展后应当看得到窗口外那份"


def test_expansion_readings_reach_outermost_container(tmp_path):
    """★ **读数必须到最外层容器**：库级结果里要有扩展读数（不是只在内层函数里算）。"""
    lib = _many_materials_library(tmp_path)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    _designate_deep_candidate(tmp_path, lib, obl["obligation_id"])

    res = ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path))
    exp = res.get("candidate_expansion")
    assert exp, res
    assert exp["enabled"] is True
    assert exp["expanded_obligations"] >= 1
    assert exp["obligations"], exp
    assert exp["obligations"][0]["candidates_checked"] >= 20
    assert "note" in exp and exp["note"]


def test_expansion_reports_unchecked_honestly(tmp_path):
    """★ 预算用完时必须**如实报「还有 N 份没看」**（禁静默漏检）。"""
    lib = _many_materials_library(tmp_path, n=30)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    obl_id = obl["obligation_id"]
    _designate_deep_candidate(tmp_path, lib, obl_id)

    # 预算卡在 25 ⇒ 一定看不完 ⇒ 必须报未看数 + 预算耗尽
    res = ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path),
                           expansion_steps=(25,), max_candidates=25)
    row = res["candidate_expansion"]["obligations"][0]
    assert row["stop_reason"] == "BUDGET_EXHAUSTED", row
    assert row["candidates_unchecked"] > 0, row
    assert "未看" in row["note"], row


def test_expansion_can_be_switched_off(tmp_path):
    """★ 关闭开关 ⇒ 不扩展（成本纪律可控），且读数如实说「没扩」。"""
    lib = _many_materials_library(tmp_path)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    _designate_deep_candidate(tmp_path, lib, obl["obligation_id"])

    res = ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path),
                           expand_candidates=False)
    exp = res["candidate_expansion"]
    assert exp["enabled"] is False
    assert exp["expanded_obligations"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 五、第 5 轮独立复核抓到的缺陷 ①：扩展路径**丢掉人工确认映射**
# ═══════════════════════════════════════════════════════════════════════════

def test_expansion_keeps_human_confirmed_evidence(tmp_path):
    """★ 缺陷 ①：候选扩展**必须透传** `confirmed_map`（人工确认是最强的一档证据）。

    ★ 旧字节上这条**是红的**：扩展路径调 `match_obligation` 时**没传** `confirmed_map`
      ⇒ 触顶义务（最需要人工确认的那批）的最终结论是在「无人工确认口径」下算出来的
      ⇒ 主体依据从 `HUMAN_CONFIRMED` 掉回 `BODY_TEXT`/`UNRESOLVED`。
    """
    lib = _many_materials_library(tmp_path, n=30)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    obl_id = obl["obligation_id"]
    deep_id, pool = _designate_deep_candidate(tmp_path, lib, obl_id)
    assert pool > 20

    # 人工确认：把**窗口外那份**（只有扩窗才看得到）认成登记主体
    confirmed = {deep_id: {"entity": "甲科技有限责任公司", "entity_id": "E1",
                           "source_ref": "人工确认（测试夹具）"}}
    res = ms.match_library(lib, candidate_cap=20, db_path=_db(tmp_path),
                           confirmed_map=confirmed)
    exp = res["candidate_expansion"]
    assert exp["expanded_obligations"] == 1, exp

    rows = [r for r in _matches(tmp_path, obl_id) if r["file_id"] == deep_id]
    assert rows, "扩窗后窗口外那份必须进入留痕"
    ev = str(rows[0].get("evidence") or "")
    assert "HUMAN_CONFIRMED" in ev, (
        f"扩展后丢了人工确认这一档证据 ⇒ 扩展结论与第一遍不同口径：{ev[:400]}")


def test_confirmed_map_key_case_does_not_matter(tmp_path):
    """★ 条件项 ④：查表键**大小写归一** ⇒ 表里写 `FILE-ABC` 也要能命中。

    ★ 旧字节上这条**是红的**：只归一「行内键」、不归一「表内键」
      ⇒ 大写键**静默不命中**（看起来像「人工没确认过」）。
    """
    lib = _two_entity_library(tmp_path)
    obl = _ingest(tmp_path, lib, "甲科技有限责任公司：提供 2024 年度审计报告")[0]
    obl_id = obl["obligation_id"]

    # 先拿一份材料的 file_id（大写形式写进表里）
    cand = ms._conn(_db(tmp_path)).execute(
        "SELECT file_id FROM dd_v1_manifest LIMIT 1").fetchone()
    fid = str(cand["file_id"])
    confirmed = {fid.upper(): {"entity": "甲科技有限责任公司", "entity_id": "E1"}}

    st = ms.match_obligation(lib, obl_id, db_path=_db(tmp_path), confirmed_map=confirmed)
    rows = _matches(tmp_path, obl_id)
    hit = [r for r in rows if r["file_id"] == fid]
    assert hit, rows
    assert "HUMAN_CONFIRMED" in str(hit[0].get("evidence") or ""), (
        f"大写查表键没命中（看起来像「人工没确认」）：{hit[0].get('evidence')}")


def test_confirmed_map_exact_key_wins_over_case_variant(tmp_path):
    """★ 查表键归一**不许串味**：表里同时有 `FILE-ABC` 与 `file-abc`（**不同主体**）⇒ 各归各的。

    ★ 第 6 轮独立复核抓到的**误命中**：先前把「大小写不敏感」做成**单一索引**，
      表里的 `FILE-ABC` 会被 `file-abc` **顶掉** ⇒ 行内 `file_id=FILE-ABC` 的材料
      会被判成**另一个主体**（人工确认反了）。
    ★ 修法：**两级查表** —— ① 原样键精确命中优先 ② 大小写不敏感只作兜底。
    """
    from cangjie_fos.services import dd_v1_entity_resolution_service as ers

    row_up = {"file_id": "FILE-ABC", "sha256": "1" * 64,
              "relative_path": "a/FILE-ABC.txt"}
    row_lo = {"file_id": "file-abc", "sha256": "2" * 64,
              "relative_path": "b/file-abc.txt"}
    confirmed = {
        "FILE-ABC": {"entity": "甲科技有限责任公司", "entity_id": "E-UPPER"},
        "file-abc": {"entity": "乙实业集团有限公司", "entity_id": "E-LOWER"},
    }
    up = ers.resolve_material_entity(row_up, [], {}, confirmed_map=confirmed)
    lo = ers.resolve_material_entity(row_lo, [], {}, confirmed_map=confirmed)
    assert up["entity_id"] == "E-UPPER", up
    assert lo["entity_id"] == "E-LOWER", lo

    # ★ 只有大写键时 ⇒ 行内小写键**仍能命中**（大小写不敏感那档兜底）
    only_upper = ers.resolve_material_entity(
        row_lo, [], {}, confirmed_map={"FILE-ABC": {"entity": "甲科技有限责任公司",
                                                    "entity_id": "E-UPPER"}})
    assert only_upper["entity_id"] == "E-UPPER", only_upper
    assert only_upper["matched_by"] == "HUMAN_CONFIRMED", only_upper
