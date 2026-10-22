"""A2 · G-A2-11：**义务侧主体约束 + MATCHED 主体证据闸** —— 判别力用例。

## 为什么要有这个文件

独立监工第 30 轮实测：真实材料三案例的 ``dd_v1_obligations`` 里
**``entity_scope`` 319/319 全空、``entity_basis`` 319/319 全 UNKNOWN**；
而义务原文里**明明有主体前缀**（形如「<主体>：最新的营业执照正」）。

司仓**独立复现**属实，并查明**前缀在按「、」切分时丢失**
（「<主体>：最新的营业执照正、副本复印件」切成两条，第二条没了前缀）。

⇒ 判定层 `evaluate_file` 里 `elif not need_entities: ent_ok = 1`
⇒ **主体维度直接无门槛放行** ⇒ 存在**假 MATCHED** 的口子
（主体根本未经核对，却可能报「材料齐备」）。

## 本文件锁住的四件事

- **11a 主体前缀抽取**：保守（形状启发式 + 停用词 + 长度上限），宁可漏判不误判。
- **11b 简称可对上**：登记别名经归一后能解析成**该主体** ⇒ 主体维度成为门槛。
- **11c ★MATCHED 主体证据闸**：
  - 义务指名了主体但**没登记上** ⇒ 判 UNCERTAIN（不得 MATCHED）；
  - 义务**没**指名主体、而**本库登记了多于一个主体** ⇒ 主体维度**不可判定**
    ⇒ **不得**产出 MATCHED / PARTIAL。
  - ★ 该闸**只会把结论改保守**，绝不会放松任何硬 Gate。
- **11d 前缀传播**：同一条清单项切出的并列义务共享主体前缀。

## 敏感纪律

主体前缀是**客户标识** ⇒ 本文件一律用「甲公司/乙公司/丙公司」等**虚构简称**，
且**断言判据文案里不出现原文**（脱敏后统一写「义务指名的主体（简称）」）。

## ★ 判别力（双向）

- 回退生产端 ⇒ 本文件**必须 FAIL**（否则就是「写了没验」的假账）；
- 「登记了主体 + 别名对得上」时 ⇒ 闸门**不得**误伤（不得把合法路径一起打死）。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import (
    dd_v1_entity_service as es,
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_card_service as cs,
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
    mf.register_library(lib, str(root), authorized_by="A2", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _register(tmp_path, lib, eid, name, relation="subsidiary"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _alias(tmp_path, lib, eid, alias):
    es.register_entity_alias(lib, eid, alias, source_ref="工商登记",
                              db_path=_db(tmp_path))


def _ingest(tmp_path, lib, raw_text):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    return rq.list_obligations(lib, db_path=_db(tmp_path))


def _status(tmp_path, lib, raw_text):
    obl = _ingest(tmp_path, lib, raw_text)[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
# 11a 主体前缀抽取（保守）
# ═══════════════════════════════════════════════════════════════════════


def test_subject_hint_prefix_detects_subject():
    assert rq.subject_hint_prefix("甲公司：最新的营业执照正") == "甲公司"


def test_subject_hint_prefix_rejects_stopwords():
    """「说明：……」不得被当成主体（否则会把说明文字当主体口径）。"""
    assert rq.subject_hint_prefix("说明：需要提供审计报告") == ""
    assert rq.subject_hint_prefix("备注：营业执照复印件") == ""


def test_subject_hint_prefix_rejects_non_marker():
    """不含机构形态词的冒号前缀**不得**当主体（宁可漏判不误判）。"""
    assert rq.subject_hint_prefix("事项：需要提供审计报告") == ""
    assert rq.subject_hint_prefix("附件：营业执照") == ""


def test_subject_hint_prefix_rejects_too_long():
    """超过长度上限的前缀**不得**当主体。"""
    long_prefix = "甲" * 13
    assert rq.subject_hint_prefix(f"{long_prefix}：审计报告") == ""


def test_subject_hint_prefix_empty_when_no_colon():
    assert rq.subject_hint_prefix("需要提供审计报告") == ""


def test_parse_entity_scope_returns_hint_with_inferred_basis():
    """★ basis 必须是 INFERRED（简称是线索，不是法律事实）。"""
    scope, basis = rq.parse_entity_scope("甲公司：最新的营业执照正")
    assert scope == f"{rq.ENTITY_HINT_PREFIX}甲公司"
    assert basis == rq.INFERRED


# ═══════════════════════════════════════════════════════════════════════
# 11d 前缀传播到并列片段
# ═══════════════════════════════════════════════════════════════════════


def test_prefix_propagates_to_parallel_fragments(tmp_path):
    """★ 判别力：按「、」切开后，第二条义务**不得**丢掉主体前缀。

    丢了前缀 ⇒ 该条义务主体维度无门槛放行 ⇒ 假 MATCHED 的口子。
    """
    lib = _setup(tmp_path, {
        "甲公司/营业执照.pdf": "营业执照正本复印件，加盖公章。",
    })
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")
    obls = _ingest(tmp_path, lib, "甲公司：最新的营业执照正、副本复印件")
    assert len(obls) >= 2, f"本用例前提：这条应被切成多条义务，实际 {len(obls)}"
    for o in obls:
        assert o["entity_scope"].startswith(rq.ENTITY_HINT_PREFIX), \
            f"义务 {o['obligation_id']} 丢了主体前缀：{o['entity_scope']!r}"
        assert o["entity_basis"] == rq.INFERRED


# ═══════════════════════════════════════════════════════════════════════
# 11b 简称可对上 ⇒ 主体维度成为门槛
# ═══════════════════════════════════════════════════════════════════════


def test_resolve_entities_resolves_hint_via_alias(tmp_path):
    """★ 判别力：简称经别名归一后**必须**能解析成该主体（否则主体维度门槛形同虚设）。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.pdf": "营业执照正本复印件。"}, lib="lib1")
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")
    rows = rq.resolve_entities(lib, f"{rq.ENTITY_HINT_PREFIX}甲公司",
                               db_path=_db(tmp_path))
    assert len(rows) == 1, f"简称应解析到已登记主体，实际 {rows}"
    assert rows[0]["entity_id"] == "E1"


def test_resolve_entities_hint_not_registered_returns_empty(tmp_path):
    """未登记的简称**不得**被猜成某个主体。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.pdf": "营业执照正本复印件。"}, lib="lib1")
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    rows = rq.resolve_entities(lib, f"{rq.ENTITY_HINT_PREFIX}丙公司",
                               db_path=_db(tmp_path))
    assert rows == [], "未登记的简称不得解析出主体"


# ═══════════════════════════════════════════════════════════════════════
# 11c ★MATCHED 主体证据闸
# ═══════════════════════════════════════════════════════════════════════


def test_unregistered_named_subject_is_uncertain(tmp_path):
    """★ 判别力：义务指名了**未登记**的主体 ⇒ 不得报 MATCHED/PARTIAL。"""
    lib = _setup(tmp_path, {
        "丙公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由丙公司出具。",
    })
    st = _status(tmp_path, lib, "丙公司：2022年度审计报告")
    assert st["verdict"] not in ("MATCHED", "PARTIAL"), \
        f"主体未登记却报了 {st['verdict']}：{st.get('missing_detail')}"
    assert st["verdict"] == "UNCERTAIN"


def test_unregistered_named_subject_partial_period_is_uncertain(tmp_path):
    """★★ **M-1 回归锁**（独立 Reviewer 第一轮抓到 · A2-14 FAIL）。

    复现口径（Reviewer）：库登记主体一、材料仅覆盖 2021、
    义务「丙公司：2021年至2022年度审计报告」（丙公司**未登记**）
    ⇒ **修复前** `verdict = PARTIAL`、`need_entities = 0`
    ⇒ 根因：`judge()` 的 elif 链里**期间分支早于主体闸**
    ⇒ 主体维度**从未核对过**却给出「部分齐备」的结论。

    ★ 修复后必须 **UNCERTAIN**（主体不可判定 ⇒ 该义务根本不能判）。

    ★ 合成材料用 **.txt**：`.pdf` 装纯文本 ⇒ 解析器读不出 ⇒ 期间提不出来
      ⇒ 走不到「期间部分覆盖」那条分支 ⇒ **测不到目标分支**。
    """
    lib = _setup(tmp_path, {
        "甲公司/2021年审计报告.txt":
            "审计报告\n本报告为2021年度财务审计结论，由甲公司出具。\n",
    })
    _register(tmp_path, lib, "E1", "甲公司全称")
    st = _status(tmp_path, lib, "丙公司：2021年至2022年度审计报告")
    assert st["need_entities"] == 0, \
        f"丙公司未登记 ⇒ need_entities 应为 0：{st['need_entities']}"
    assert st["verdict"] == "UNCERTAIN", (
        f"★ M-1：主体未登记 ⇒ 不得被「期间只覆盖一部分」抢先判成 PARTIAL："
        f"verdict={st['verdict']} / {st.get('missing_detail')}")
    assert "无权威主体名单" in str(st.get("missing_detail") or ""), \
        f"须写明主体无权威名单：{st.get('missing_detail')}"


# ═══════════════════════════════════════════════════════════════════════
# ★ m-4（独立 Reviewer 第二轮）：**verdict 断言本身**必须是判别点
# ═══════════════════════════════════════════════════════════════════════
#
# 上面那条锁在**回退主体闸顺序**后，verdict 断言仍通过，转红的是**文案断言**
# ⇒ 根因：该场景把登记全称写成与卡片 entity 父目录名**不同**的名字
#        ⇒ **候选主体未登记** ⇒ A1 时代的「主体未登记 ⇒ 一律 UNCERTAIN」闸
#           先把 PARTIAL 改回 UNCERTAIN ⇒ **次序缺陷被掩盖**。
#
# ★ 司仓独立实测（`gm_probe_m4_discriminative_scene.py`，/tmp 农场副本，worktree 零改动自证）：
#     S1 登记全称≠卡片目录名（= 上面那条）  当前 UNCERTAIN / 回退 UNCERTAIN ⇒ ❌ 不判别
#     S2 登记名==卡片目录名（候选主体已登记）当前 UNCERTAIN / 回退 **PARTIAL** ⇒ ★ 判别
#     S4 双主体库 + 义务指名未登记主体      当前 UNCERTAIN / 回退 **PARTIAL** ⇒ ★ 判别
#
# ⇒ 下面两条用例把「候选主体已登记」这个前提显式化，
#   使 **verdict 断言**成为真正的判别点（回退顺序 ⇒ verdict 变 PARTIAL ⇒ 用例转红）。


def test_candidate_subject_registered_keeps_verdict_discriminative(tmp_path):
    """★ **m-4 判别锁（单主体库 · 候选主体已登记）**。

    场景：材料放在「甲公司/」下，**登记全称 == 卡片 entity 父目录名「甲公司」**
    ⇒ 候选主体**已登记**；义务却指名**未登记**的「丙公司」，且期间只覆盖一半
    （材料 2021 / 需要 2021-2022）。

    ★ 期望（修后）：**UNCERTAIN** —— 义务指名的主体无权威登记 ⇒ 主体维度不可判定
      ⇒ 不得抢先判成「部分齐备」（PARTIAL）。

    ★ **判别力**：回退主体闸顺序（挪回 A1 位置，期间分支在前）⇒ verdict 变 **PARTIAL**
      ⇒ **本条 verdict 断言转红** ⇒ 这才是真正的判别点。
    """
    lib = _setup(tmp_path, {
        "甲公司/2021年审计报告.txt":
            "审计报告\n本报告为2021年度财务审计结论，由甲公司出具。\n",
    })
    # ★ 登记名 == 卡片 entity 父目录名 ⇒ 候选主体**已登记**（与上面那条的关键差异）
    _register(tmp_path, lib, "E1", "甲公司")
    st = _status(tmp_path, lib, "丙公司：2021年至2022年度审计报告")
    assert st["verdict"] == "UNCERTAIN", (
        f"★ m-4：候选主体已登记时，主体闸必须仍早于期间分支："
        f"verdict={st['verdict']} / {st.get('missing_detail')}")


def test_two_subject_library_keeps_verdict_discriminative(tmp_path):
    """★ **m-4 判别锁（双主体库 · 隐含要求不计入）**。

    场景：库里登记了**两个**主体（甲公司 / 乙公司）⇒ 隐含的「单主体要求」**不计入**
    ⇒ 义务指名未登记的「丙公司」时 `need_entities = 0`；材料只覆盖 2021，义务需要 2021-2022。

    ★ 期望（修后）：**UNCERTAIN**。
    ★ **判别力**：回退主体闸顺序 ⇒ verdict 变 **PARTIAL** ⇒ 本条 verdict 断言转红。
    """
    lib = _setup(tmp_path, {
        "甲公司/2021年审计报告.txt":
            "审计报告\n本报告为2021年度财务审计结论，由甲公司出具。\n",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _register(tmp_path, lib, "E2", "乙公司")
    st = _status(tmp_path, lib, "丙公司：2021年至2022年度审计报告")
    assert st["need_entities"] == 0, \
        f"双主体库 ⇒ 隐含要求不计入 ⇒ need_entities 应为 0：{st['need_entities']}"
    assert st["verdict"] == "UNCERTAIN", (
        f"★ m-4：主体闸必须早于期间分支：verdict={st['verdict']} / {st.get('missing_detail')}")


def test_unregistered_named_subject_full_period_still_uncertain(tmp_path):
    """★ M-1 的**对照组一**：主体未登记 + 期间**全覆盖** ⇒ 修复前后都应是 UNCERTAIN。

    ⇒ 证明新用例转红的原因是**分支顺序**，不是别的。
    """
    lib = _setup(tmp_path, {
        "甲公司/2021年审计报告.txt":
            "审计报告\n本报告为2021年度财务审计结论，由甲公司出具。\n",
        "甲公司/2022年审计报告.txt":
            "审计报告\n本报告为2022年度财务审计结论，由甲公司出具。\n",
    })
    _register(tmp_path, lib, "E1", "甲公司全称")
    st = _status(tmp_path, lib, "丙公司：2021年至2022年度审计报告")
    assert st["verdict"] == "UNCERTAIN", \
        f"主体未登记 ⇒ 无论期间覆盖与否都必须 UNCERTAIN：{st['verdict']}"


def test_registered_named_subject_partial_period_stays_partial(tmp_path):
    """★ M-1 的**对照组二**：主体**已登记** + 期间部分覆盖 ⇒ **PARTIAL 合法**。

    ⇒ 证明新闸**没有误伤**合法路径（判别力的另一半）。
    """
    lib = _setup(tmp_path, {
        "甲公司/2021年审计报告.txt":
            "审计报告\n本报告为2021年度财务审计结论，由甲公司出具。\n",
    })
    _register(tmp_path, lib, "E1", "甲公司全称")
    _alias(tmp_path, lib, "E1", "甲公司")
    st = _status(tmp_path, lib, "甲公司：2021年至2022年度审计报告")
    assert st["need_entities"] == 1, \
        f"主体已登记 ⇒ need_entities 应为 1：{st['need_entities']}"
    assert st["verdict"] == "PARTIAL", (
        f"★ 主体已登记 + 期间部分覆盖 ⇒ PARTIAL 合法（不得误伤）："
        f"verdict={st['verdict']} / {st.get('missing_detail')}")


def test_unregistered_named_subject_detail_is_desensitized(tmp_path):
    """★ 敏感：判据文案**不得**出现客户标识原文。"""
    lib = _setup(tmp_path, {
        "丙公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由丙公司出具。",
    })
    st = _status(tmp_path, lib, "丙公司：2022年度审计报告")
    detail = str(st.get("missing_detail") or "")
    assert "丙公司" not in detail, f"判据文案泄漏了主体原文：{detail}"
    assert "义务指名的主体（简称）" in detail, \
        f"应写脱敏标签：{detail}"


def test_multi_entity_library_without_subject_blocks_matched(tmp_path):
    """★ 判别力：义务**没**指名主体 + 本库登记了**多于一个**主体
    ⇒ 主体维度不可判定 ⇒ **不得**产出 MATCHED / PARTIAL。

    这是监工指出的「假 MATCHED 口子」的正面对撞用例。
    """
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由甲公司出具。",
    })
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _register(tmp_path, lib, "E2", "乙集团有限公司")
    st = _status(tmp_path, lib, "2022年度审计报告")
    assert st["verdict"] not in ("MATCHED", "PARTIAL"), \
        f"主体维度不可判定却报了 {st['verdict']}：{st.get('missing_detail')}"
    assert st["verdict"] == "UNCERTAIN"
    assert "主体维度不可判定" in str(st.get("missing_detail") or "")


def test_single_entity_library_without_subject_not_blocked(tmp_path):
    """★ 判别力（反向）：本库**只登记一个**主体 ⇒ 主体维度可判定
    ⇒ 闸门**不得**误伤（不得把合法路径一起打死）。"""
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由甲公司出具。",
    })
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    st = _status(tmp_path, lib, "2022年度审计报告")
    assert "主体维度不可判定" not in str(st.get("missing_detail") or ""), \
        f"单一主体的库不该触发不可判定闸：{st.get('missing_detail')}"


def test_registered_named_subject_not_blocked(tmp_path):
    """★ 判别力（反向）：义务指名的主体**已登记**且**别名对得上**
    ⇒ 主体维度成为门槛且可判定 ⇒ 闸门**不得**误伤。"""
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由甲公司出具。",
    })
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")
    st = _status(tmp_path, lib, "甲公司：2022年度审计报告")
    assert "主体维度不可判定" not in str(st.get("missing_detail") or ""), \
        f"已登记主体不该触发不可判定闸：{st.get('missing_detail')}"


def test_gate_only_downgrades_never_relaxes(tmp_path):
    """★ 红线：该闸**只会把结论改保守**，绝不把 UNCERTAIN/MISSING 放宽。"""
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由甲公司出具。",
    })
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _register(tmp_path, lib, "E2", "乙集团有限公司")
    st = _status(tmp_path, lib, "完全找不到的材料名称xyz")
    assert st["verdict"] in ("MISSING", "UNCERTAIN"), \
        f"闸门不得把更严的结论放宽：{st['verdict']}"


# ═══════════════════════════════════════════════════════════════════════
# 脱敏单一来源
# ═══════════════════════════════════════════════════════════════════════


def test_scope_value_desensitizes_hint():
    v = rq.entity_scope_value(f"{rq.ENTITY_HINT_PREFIX}丙公司")
    assert "丙公司" not in v, f"展示值泄漏了原文：{v}"
    assert v == rq.ENTITY_HINT_LABEL


def test_scope_label_desensitizes_hint():
    lbl = rq.entity_scope_label(f"{rq.ENTITY_HINT_PREFIX}丙公司")
    assert "丙公司" not in lbl, f"文案标签泄漏了原文：{lbl}"
    assert lbl == rq.ENTITY_HINT_LABEL


def test_scope_label_keeps_non_hint_verbatim():
    """非前缀 scope 的文案**逐字不变**（既有断言不受影响）。"""
    assert rq.entity_scope_label("group_and_subs") == "主体范围「group_and_subs」"
    assert rq.entity_scope_value("group_and_subs") == "group_and_subs"


def test_scope_label_empty_for_empty():
    assert rq.entity_scope_label("") == ""
    assert rq.entity_scope_value("") == ""


def test_requirement_summary_does_not_leak_raw_hint():
    """★ 敏感：MISSING 的缺口明细会带义务摘要 ⇒ 摘要**不得**出现主体原文。"""
    obl = {"obligation_id": "O1", "entity_scope": f"{rq.ENTITY_HINT_PREFIX}丙公司",
           "doc_type": "license", "period_from": 0, "period_to": 0,
           "period_basis": "UNKNOWN", "seal_required": "",
           "needs_attachments": 0}
    summary = ms._requirement_summary(obl)
    assert "丙公司" not in summary, f"义务摘要泄漏了主体原文：{summary}"


def test_hint_prefix_constant_is_single_source():
    """★ 单一来源：`entity_hint:` 前缀只能有一个常量定义。"""
    import inspect
    from cangjie_fos.services import dd_v1_match_service as _ms
    for mod in (rq, _ms):
        src = inspect.getsource(mod)
        # 常量定义本身允许出现一次；其余出现必须走常量
        assert src.count('"entity_hint:"') <= 1, \
            f"{mod.__name__} 里出现多处裸字面量"
