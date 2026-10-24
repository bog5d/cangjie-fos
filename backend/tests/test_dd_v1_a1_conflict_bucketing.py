"""WP-A1（G6 v2）：冲突分桶 —— **主体未知（不在权威名单）**不得跨法人混桶报假 CONFLICT。

## 为什么是 v2（v1 错在哪）

v1 把「主体未知」实现成「``card.entity`` 为空」。但认知卡的 ``entity``
在**真实材料上就是父目录名**（``dd_v1_card_service.build_card`` 的 ``parts[-2]``，
``provenance=INFERRED``、``evidence.kind=path_segment``，全仓唯一写入点）——**非空**。

⇒ 「主体未登记」被误判成「主体已知」⇒ 同目录的**不同法人**落进同一个桶
⇒ 报假 CONFLICT；且 ``has_unknown_entities=False``
⇒ ``judge()`` 的「主体未登记 ⇒ 降级 UNCERTAIN」**根本不触发**。

v1 的用例靠 ``_blank_entities`` **直写数据库把 entity 置空**来制造「主体未知」，
**真实路径从未被覆盖** ⇒ 7/7 全绿也证明不了 G6 已修好。
v2 的用例**全部走真实建卡管线**，不手工改写卡片 entity。

## v2 口径

- **「主体未知」= 该主体不在权威名单 ``dd_v1_entities`` 里**（不是「字段为空」）；
- 主体未知 ⇒ 不参与 CONFLICT / STALE ⇒ ``judge()`` 报 UNCERTAIN
  并写明「主体未登记，无法判定是否同一主体」；
- 只有「**已登记**主体 + 同主体 + 同期间 + **同材料类型** + 内容哈希不同」才报 CONFLICT；
- 桶键 = ``(主体, 期间, 材料类型)`` ⇒ 不同材料类型（营业执照 vs 车辆登记证）不得互判冲突；
- 认知卡的 ``entity`` **仍保留**目录名线索（INFERRED）——它是线索，不是法律主体；
  但它**不得**冒充主体参与冲突判定。
"""
from __future__ import annotations

from pathlib import Path

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
    mf.register_library(lib, str(root), authorized_by="A1", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _audit(year, entity="子公司甲"):
    return f"审计报告\n本报告为{year}年度财务审计结论，由{entity}出具。\n"


def _register(tmp_path, lib, name, relation="subsidiary"):
    """登记权威主体（``source_ref`` 必填：没有权威依据的主体不得入册）。"""
    rq.register_entity(lib, "E-" + name, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _obl_status(tmp_path, raw_text, lib):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}], db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
# 判别性用例（**修复前必须失败、修复后必须通过**）
# ═══════════════════════════════════════════════════════════════════════


def test_same_directory_different_legal_persons_no_conflict(tmp_path):
    """**同目录、不同法人、均未登记** ⇒ 不得报 CONFLICT（G6 明文合成用例）。

    真实材料按目录放材料，同一目录里可能同时躺着母公司和子公司的文件，
    两张卡的 ``card.entity`` 都是同一个**父目录名**（INFERRED）。
    这是 v1 漏掉的那条路径：**不手工改 entity**，走真实建卡管线。
    """
    lib = _setup(tmp_path, {
        "归档目录/甲公司审计2024.txt": _audit(2024, "甲公司"),
        "归档目录/乙公司审计2024.txt": _audit(2024, "乙公司"),
    })
    st = _obl_status(tmp_path, "请提供2024年度审计报告", lib)
    assert st["has_conflict"] is False, \
        f"同目录不同法人、均未登记不得报冲突：{st.get('conflicts')}"
    assert st["verdict"] != ms.V_CONFLICT, f"不得判 CONFLICT：{st['verdict']}"
    assert "主体未登记，无法判定是否同一主体" in st["missing_detail"], \
        f"必须写明主体未登记：{st['missing_detail']}"


def test_authority_list_not_covering_dir_name_no_conflict(tmp_path):
    """**权威名单非空但不覆盖该目录名** ⇒ 不得报 CONFLICT。

    权威名单里登记的是「丙公司」，卡片主体是父目录名「归档目录」⇒
    两者不是同一主体 ⇒ 不得混桶。
    """
    lib = _setup(tmp_path, {
        "归档目录/甲公司审计2024.txt": _audit(2024, "甲公司"),
        "归档目录/乙公司审计2024.txt": _audit(2024, "乙公司"),
    })
    _register(tmp_path, lib, "丙公司")
    st = _obl_status(tmp_path, "请提供2024年度审计报告", lib)
    assert st["has_conflict"] is False, \
        f"权威名单不覆盖该目录名时不得报冲突：{st.get('conflicts')}"


def test_same_entity_different_doc_types_no_conflict(tmp_path):
    """**同主体 + 同期间 + 不同材料类型** ⇒ 不得互判冲突。

    真实材料上「营业执照」与「车辆登记证」曾被当成同主体同期冲突
    （桶键只有 ``(entity, period)``，不含材料类型）。
    """
    lib = _setup(tmp_path, {
        "子公司甲/营业执照2024.txt": "营业执照\n统一社会信用代码 91330000MA2XXXXX1A\n内容一。\n",
        "子公司甲/车辆登记证2024.txt": "车辆登记证\n号牌 沪A12345\n内容二。\n",
    })
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供子公司甲的营业执照", lib)
    assert st["has_conflict"] is False, \
        f"不同材料类型不得互判冲突：{st.get('conflicts')}"


def test_registered_same_entity_same_type_diff_hash_conflicts(tmp_path):
    """**回归红线**：已登记 + 同主体 + 同期间 + 同类型 + 异哈希 ⇒ **仍须**报 CONFLICT。

    G6 v2 改的是「谁算已知主体」和「桶键多一个类型维度」，
    **不得**把真正的同主体版本冲突一起改没了。
    """
    lib = _setup(tmp_path, {
        "子公司甲/审计报告2023正文.txt": _audit(2023) + "补充说明一。\n",
        "子公司甲/审计报告2023草稿.txt": _audit(2023) + "补充说明二，完全不同。\n",
    })
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供2023年度审计报告", lib)
    assert st["has_conflict"] is True, "同主体同类型异哈希必须仍报冲突"
    assert st["verdict"] == ms.V_CONFLICT, f"必须判 CONFLICT：{st['verdict']}"


def test_registered_different_entities_same_period_no_conflict(tmp_path):
    """**回归红线**：不同**已登记**主体同年材料 ⇒ 不得报冲突。"""
    lib = _setup(tmp_path, {
        "子公司甲/审计报告2023.txt": _audit(2023, "子公司甲"),
        "子公司乙/审计报告2023.txt": _audit(2023, "子公司乙"),
    })
    _register(tmp_path, lib, "子公司甲")
    _register(tmp_path, lib, "子公司乙")
    st = _obl_status(tmp_path, "请提供2023年度审计报告", lib)
    assert st["has_conflict"] is False, "不同已登记主体不得报同一主体冲突"


# ═══════════════════════════════════════════════════════════════════════
# 口径与降级路径
# ═══════════════════════════════════════════════════════════════════════


def test_card_entity_is_inferred_directory_name_not_legal_subject(tmp_path):
    """记录事实并锁死语义：卡片 ``entity`` = 父目录名、``provenance=INFERRED``。

    它**是线索、不是法律主体**；v2 保留这条线索（改掉会波及桥接的
    ``CARD_INFERRED`` 主体档与 A2 的 G-A2-3），但判定层**不再采信它**。
    """
    lib = _setup(tmp_path, {"归档目录/甲公司审计2024.txt": _audit(2024, "甲公司")})
    rows = list(mf.list_manifest(lib, limit=10, db_path=_db(tmp_path)))
    conn = mf._connect(_db(tmp_path))
    row = conn.execute("SELECT * FROM dd_v1_manifest WHERE rel_path=?",
                       ("归档目录/甲公司审计2024.txt",)).fetchone()
    card = cs.get_card(row["file_id"], db_path=_db(tmp_path)) or {}
    fld = (card.get("fields") or {}).get("entity") or {}
    kinds = [e.get("kind") for e in (fld.get("evidence") or [])]
    assert card.get("entity") == "归档目录", f"entity 应为父目录名：{card.get('entity')!r}"
    assert fld.get("provenance") == "INFERRED", f"provenance 应为 INFERRED：{fld.get('provenance')}"
    assert "path_segment" in kinds, f"证据来源应为 path_segment：{kinds}"


def test_unknown_subject_reports_uncertain_not_conflict(tmp_path):
    """主体未知 ⇒ **UNCERTAIN**（需人工确认），不是 CONFLICT。

    平铺布局（``card.entity`` 本就为空）与子目录布局（entity=目录名）都要走到这条路径。
    """
    lib = _setup(tmp_path, {
        "归档目录/甲公司审计2024.txt": _audit(2024, "甲公司"),
        "归档目录/甲公司审计2024修订.txt": _audit(2024, "甲公司") + "补充说明，内容不同。\n",
    })
    st = _obl_status(tmp_path, "请提供2024年度审计报告", lib)
    assert st["has_conflict"] is False, "主体未知不得报内容冲突"
    assert st["verdict"] == ms.V_UNCERTAIN, f"主体未知必须判 UNCERTAIN：{st['verdict']}"
    assert "主体未登记，无法判定是否同一主体" in st["missing_detail"]


def test_detect_anomalies_reports_unknown_entity_note(tmp_path):
    """``detect_anomalies`` 直接调用：主体未知时给 ``unknown_entities`` 说明，不产冲突组。"""
    lib = _setup(tmp_path, {
        "归档目录/甲公司审计2024.txt": _audit(2024, "甲公司"),
        "归档目录/乙公司审计2024.txt": _audit(2024, "乙公司"),
    })
    obl = {"obligation_id": "T", "period_from": 2024, "period_to": 2024}
    conn = mf._connect(_db(tmp_path))
    pool = []
    for rel in ("归档目录/甲公司审计2024.txt", "归档目录/乙公司审计2024.txt"):
        row = conn.execute("SELECT * FROM dd_v1_manifest WHERE rel_path=?",
                           (rel,)).fetchone()
        card = cs.get_card(row["file_id"], db_path=_db(tmp_path))
        pool.append({"file_id": row["file_id"], "card": card, "manifest": dict(row)})
    anom = ms.detect_anomalies(obl, pool, [])
    assert anom["has_conflict"] is False
    assert anom["unknown_entities"], "主体未知必须显式报告，不得静默混桶"
    assert anom["has_unknown_entities"] is True


def test_authority_list_never_supplies_subject_by_directory_name(tmp_path):
    """**不得用目录名冒充主体**：目录名进了权威名单 ⇒ 才算同一主体。

    这条锁的是 G6 的「登记同主体且哈希不同才报 CONFLICT」：
    权威名单是**唯一**的「已登记」来源，目录名本身不算。
    """
    lib = _setup(tmp_path, {
        "归档目录/甲公司审计2024.txt": _audit(2024, "甲公司"),
        "归档目录/甲公司审计2024修订.txt": _audit(2024, "甲公司") + "补充说明。\n",
    })
    # 权威名单**没有**「归档目录」⇒ 主体未知
    st = _obl_status(tmp_path, "请提供2024年度审计报告", lib)
    assert st["has_conflict"] is False, "目录名不得冒充主体参与冲突判定"
    # 权威名单登记了「归档目录」⇒ 此时才算已登记主体
    _register(tmp_path, lib, "归档目录", relation="other")
    st2 = _obl_status(tmp_path, "请提供2024年度审计报告", lib)
    assert st2["has_conflict"] is True, "已登记主体 + 同期间 + 异哈希必须报冲突"


# ═══════════════════════════════════════════════════════════════════════
# WP-A1（G6 v3 · R1）：**材料类型认不出**时不得互判 CONFLICT
# ═══════════════════════════════════════════════════════════════════════
#
# 洞是怎么来的：G6 v2 把桶键改成 (主体, 期间, 材料类型)，
# 但**类型认不出时第三元取的是空串**，空串照样入桶 ⇒
# 两份「类型未知」材料落进同一个桶 (entity, period, "") ⇒
# 同主体 + 同期间 + 异哈希 ⇒ 误报「同主体同期内容冲突」。
#
# 为什么 G6 v2 的用例测不出来：那些用例里主体**也没登记**
# ⇒ 全部先落 unknown_bucket ⇒ 类型这一格根本没走到。
# ⇒ 权威名单一旦填上（= A2 的 G-A2-3/G-A2-8），这个洞立刻显性化。
#
# 诚实性口径：认不出材料类型 ⇒ **无法判定两份材料是不是同一材料类型的两个版本**
# ⇒ 不得断言「内容冲突」⇒ 不参与冲突判定，单列 unknown_type_bucket，
#   并由 judge() 降级为 UNCERTAIN 且写明原因（**不静默放行**）。
#
# 红线：**同主体 + 同期间 + 同类型（已识别）+ 异哈希 ⇒ 仍必须报 CONFLICT**。


def test_unknown_doc_type_no_conflict(tmp_path):
    """**类型认不出** + 主体已登记 + 同期间 + 异哈希 ⇒ 不得报 CONFLICT。

    走**真实建卡管线**：文件名与正文都**不含任何类型关键词**，
    主体目录名已登记进权威名单 ⇒ 只剩「类型未知」这一个变量。
    """
    lib = _setup(tmp_path, {
        "子公司甲/材料一2024.txt": "合成样本甲，本材料用于回归验证，内容一。\n",
        "子公司甲/材料二2024.txt": "合成样本乙，本材料用于回归验证，内容二完全不同。\n",
    })
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供2024年度相关材料", lib)
    assert st["has_conflict"] is False, \
        f"类型认不出不得报冲突：{st.get('conflicts')}"
    assert st["verdict"] != ms.V_CONFLICT, f"不得判 CONFLICT：{st['verdict']}"
    assert "材料类型认不出" in st["missing_detail"], \
        f"必须写明材料类型认不出：{st['missing_detail']}"


def test_known_doc_type_still_conflicts_after_r1(tmp_path):
    """**正向红线**：类型已识别 + 主体已登记 + 同期间 + 异哈希 ⇒ **仍须**报 CONFLICT。

    R1 只把「类型认不出」的材料移出冲突桶，**不得**把真冲突一起改没。
    """
    lib = _setup(tmp_path, {
        "子公司甲/审计报告2023正文.txt": _audit(2023) + "补充说明一。\n",
        "子公司甲/审计报告2023草稿.txt": _audit(2023) + "补充说明二，完全不同。\n",
    })
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供2023年度审计报告", lib)
    assert st["has_conflict"] is True, "类型已识别时同主体异哈希必须仍报冲突"
    assert st["verdict"] == ms.V_CONFLICT, f"必须判 CONFLICT：{st['verdict']}"
    assert "材料类型认不出" not in st["missing_detail"], \
        f"类型已识别不得写「类型认不出」：{st['missing_detail']}"


def test_detect_anomalies_reports_unknown_type_note(tmp_path):
    """``detect_anomalies`` 直接调用：类型认不出时给 ``unknown_types`` 说明，不产冲突组。"""
    lib = _setup(tmp_path, {
        "子公司甲/材料一2024.txt": "合成样本甲，本材料用于回归验证，内容一。\n",
        "子公司甲/材料二2024.txt": "合成样本乙，本材料用于回归验证，内容二完全不同。\n",
    })
    _register(tmp_path, lib, "子公司甲")
    obl = {"obligation_id": "T", "period_from": 2024, "period_to": 2024}
    conn = mf._connect(_db(tmp_path))
    pool = []
    for rel in ("子公司甲/材料一2024.txt", "子公司甲/材料二2024.txt"):
        row = conn.execute("SELECT * FROM dd_v1_manifest WHERE rel_path=?",
                           (rel,)).fetchone()
        card = cs.get_card(row["file_id"], db_path=_db(tmp_path))
        pool.append({"file_id": row["file_id"], "card": card, "manifest": dict(row)})
    ents = [{"entity_id": "E-子公司甲", "display_name": "子公司甲",
             "relation": "subsidiary", "valid_from": 0, "valid_to": 0,
             "is_group_root": 0, "source_ref": "工商登记"}]
    anom = ms.detect_anomalies(obl, pool, ents)
    assert anom["has_conflict"] is False, "类型认不出不得产冲突组"
    assert anom["has_unknown_types"] is True, "类型认不出必须显式报告"
    assert anom["unknown_types"], "unknown_types 说明不得为空"
    assert "类型认不出" in anom["unknown_types"][0]["note"]
