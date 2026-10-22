"""F1（监工第 35 轮 · P0）：CONFLICT 的**相关性闸** —— 冲突只影响相关义务。

## 为什么这是 P0（司仓独立复现，不是采信口述）

冲突是**候选池内部**的发现（桶键 = 主体 × 期间 × 材料类型），
与「本义务要求哪一类材料」**无关**。
旧实现让**任意**类型的冲突对无条件覆盖本义务的最终判定 ⇒
一对「2024 审计报告 + 2024 审计报告补充说明」把**整库**义务全打成 CONFLICT ⇒
与该义务毫无关系的「缺专利证书」这类**可行动缺口信号被覆盖**
⇒ 材料包为空 ⇒ **系统在该库上完全不可用**。

复现（`/tmp/f1_repro.py`，真实产品管线 + 合成材料 + 隔离环境）修复前实测：

    L1 审计报告义务（本就该 CONFLICT） → CONFLICT   ✔
    L2 营业执照义务（与冲突无关）      → CONFLICT   ✘
    L3 专利证书义务（库里零 ip 材料）  → CONFLICT   ✘（缺口信号被覆盖）

## 修法（与 A2 G-A2-12 同构）

冲突**只影响相关义务**：冲突对里有「**可能是本义务要求的那一份**」的候选时
（`_may_be_required`，**同一套**相关性口径）本义务才改判 CONFLICT；
否则**只留痕**、**不改判**。

## 本文件锁死的三件事

1. **无关义务不再被染黑**（L2 / L3）—— 缺口信号必须回到可行动状态；
2. **真冲突必须仍然报**（L1）—— 且义务**未指名类型**时最保守地照报；
3. **冲突事实一个都不丢** —— `has_conflict` / `conflicts` / `anomalies_json`
   与留痕文案全部保留（T3 语义不变）。

★ 本文件**不写/不删仓库文件**：全部落在 `tmp_path`。
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
    mf.register_library(lib, str(root), authorized_by="F1", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _register(tmp_path, lib, name, relation="subsidiary"):
    rq.register_entity(lib, "E-" + name, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _obl_status(tmp_path, raw_text, lib):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}], db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[-1]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# 一对「同主体 + 同期间 + 同类型 + 异哈希」⇒ 真冲突（audit_report = ANNUAL_UNIQUE）
_CONFLICT_PAIR = {
    "子公司甲/子公司甲审计报告2024.txt":
        "审计报告\n本报告为2024年度财务审计结论，由子公司甲出具。\n",
    "子公司甲/子公司甲审计报告2024补充说明.txt":
        "审计报告\n本补充说明为2024年度审计报告之补充说明，由子公司甲出具。\n",
    # 无关材料：营业执照（license = MULTI_LEGAL）
    "子公司甲/子公司甲营业执照2024.txt":
        "营业执照\n子公司甲，注册资本1000万元，2024年度。\n",
}


# ═══════════════════════════════════════════════════════════════════════
# 1 · 无关义务不再被冲突染黑
# ═══════════════════════════════════════════════════════════════════════


def test_unrelated_license_obligation_is_not_shadowed_by_conflict(tmp_path):
    """审计报告冲突**不得**把「营业执照」义务打成 CONFLICT。"""
    lib = _setup(tmp_path, dict(_CONFLICT_PAIR))
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供子公司甲的营业执照", lib)
    assert st["verdict"] != ms.V_CONFLICT, (
        f"与冲突无关的义务不得判 CONFLICT：{st['verdict']} / {st['missing_detail']}")


def test_absent_ip_obligation_keeps_its_actionable_gap(tmp_path):
    """库里**零** ip 材料 ⇒ 义务必须回到「类型维缺口」，而不是被冲突覆盖。

    这是 F1 最硬的一条：可行动的缺口信号（「材料类型缺 1/1 份」）被无关冲突盖掉，
    等于把「缺什么」这条信息也一起丢了。
    """
    lib = _setup(tmp_path, dict(_CONFLICT_PAIR))
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供子公司甲的专利证书", lib)
    assert st["verdict"] != ms.V_CONFLICT, (
        f"零 ip 材料的义务不得判 CONFLICT：{st['verdict']} / {st['missing_detail']}")
    assert "材料类型缺" in (st.get("missing_detail") or ""), (
        f"类型维缺口必须回到可行动状态：{st.get('missing_detail')}")


# ═══════════════════════════════════════════════════════════════════════
# 2 · 真冲突必须仍然报（判据双向）
# ═══════════════════════════════════════════════════════════════════════


def test_related_audit_obligation_still_conflicts(tmp_path):
    """**回归红线**：冲突对与本义务要求的类型**一致** ⇒ 仍须判 CONFLICT。"""
    lib = _setup(tmp_path, dict(_CONFLICT_PAIR))
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供子公司甲2024年度审计报告", lib)
    assert st["has_conflict"] is True, "同主体同类型异哈希必须仍报冲突"
    assert st["verdict"] == ms.V_CONFLICT, f"必须判 CONFLICT：{st['verdict']}"


def test_obligation_without_named_type_still_conflicts(tmp_path):
    """义务**未指名材料类型** ⇒ 任何候选都可能是 ⇒ **最保守**：仍判 CONFLICT。

    这条锁死「加闸不许把真冲突放过」：闸只对**类型确定不同**的义务关门。
    """
    lib = _setup(tmp_path, dict(_CONFLICT_PAIR))
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供2024年度相关材料", lib)
    assert st["has_conflict"] is True, "未指名类型时不得吞掉冲突"
    assert st["verdict"] == ms.V_CONFLICT, f"未指名类型必须判 CONFLICT：{st['verdict']}"


# ═══════════════════════════════════════════════════════════════════════
# 3 · 冲突事实一个都不丢
# ═══════════════════════════════════════════════════════════════════════


def test_conflict_fact_is_still_recorded_for_irrelevant_obligation(tmp_path):
    """**不放宽冲突本身**：无关义务虽然不改判，冲突**事实与留痕**必须保留。

    - `has_conflict` 仍为 True；
    - `conflicts` 组数不减；
    - `missing_detail` 里必须有「留痕」字样与「需人工裁定」的实质。
    """
    lib = _setup(tmp_path, dict(_CONFLICT_PAIR))
    _register(tmp_path, lib, "子公司甲")
    st = _obl_status(tmp_path, "请提供子公司甲的专利证书", lib)
    assert st["has_conflict"] is True, "冲突事实必须仍然记录"
    assert st.get("conflicts"), "冲突组必须仍然报出"
    detail = st.get("missing_detail") or ""
    assert "留痕" in detail, f"必须留痕（不得静默丢弃）：{detail}"
    assert "人工裁定" in detail, f"留痕必须保留「需人工裁定」的实质：{detail}"


def test_anomalies_json_still_carries_the_conflict(tmp_path):
    """审计面（``anomalies_json``）必须仍带冲突记录 ⇒ T3 语义不变。"""
    lib = _setup(tmp_path, dict(_CONFLICT_PAIR))
    _register(tmp_path, lib, "子公司甲")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供子公司甲的专利证书"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[-1]
    ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    conn = mf._connect(_db(tmp_path))
    row = conn.execute(
        "SELECT anomalies_json FROM dd_v1_obligation_status WHERE obligation_id=?",
        (obl["obligation_id"],),
    ).fetchone()
    import json as _json
    anom = _json.loads(row["anomalies_json"] or "{}")
    assert anom.get("has_conflict") is True, f"审计面必须仍带冲突：{anom}"
    assert anom.get("conflicts"), f"审计面必须仍带冲突组：{anom}"
