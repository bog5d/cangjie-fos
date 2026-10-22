"""A2（G-A2-4 / G-A2-5）：类型维度覆盖口径 + 期间三态 —— **补零覆盖**。

## 为什么要有这个文件

**独立 Reviewer 实测抓到的真缺陷**（不是自报）：

1. 回执写着「parse_period 增 _PERIOD_MENTION ⇒ 提到但解析不出返回 basis=unresolved」，
   但 ``_PERIOD_MENTION`` **在代码里根本不存在**，``unresolved`` **运行时永不产生**
   ⇒ 判据「提及期间但解析不出 ⇒ UNCERTAIN」在**绝对期间**那一半是**空的**；
2. 典型输入「最近三个月」⇒ 落成 ``UNKNOWN`` ⇒ judge 当作「文本压根没提期间」
   ⇒ **不构成门槛** ⇒ 期间闸门被**静默丢掉**（危险方向：闸门消失，不是变松）；
3. A2-4 / A2-5 **零测试覆盖** —— 新测试文件全不碰这两个行为。

⇒ 本文件补上生产端与**判别力**用例：修复前必须失败，修复后必须通过。

## 口径（三者互不相等，是本文件的核心断言）

| basis                   | 含义                                   | judge 行为                        |
|-------------------------|----------------------------------------|-----------------------------------|
| ``FACT``                | 解析出绝对区间                         | 正常判覆盖                        |
| ``relative_unresolved`` | 相对期间缺锚定年（「近三年」）         | UNCERTAIN +「期间无法解析」       |
| ``unresolved``          | 提到了期间但解析不出（「最近三个月」）  | UNCERTAIN +「期间无法解析」       |
| ``UNKNOWN``             | **文本压根没提期间**                    | **不构成门槛**（不因此判 UNCERTAIN）|
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
    mf.register_library(lib, str(root), authorized_by="A2", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _register(tmp_path, lib, eid, name, relation="subsidiary"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _obl_status(tmp_path, raw_text, lib):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}], db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
# A2-5 期间三态
# ═══════════════════════════════════════════════════════════════════════


def test_absolute_year_is_fact():
    pf, pt, basis, _ = rq.parse_period("2024年度审计报告")
    assert (pf, pt, basis) == (2024, 2024, "FACT")


def test_year_range_is_fact():
    pf, pt, basis, _ = rq.parse_period("2022年至2024年审计年报")
    assert (pf, pt, basis) == (2022, 2024, "FACT")


def test_relative_period_without_anchor_is_relative_unresolved():
    _pf, _pt, basis, _ = rq.parse_period("近三年的审计报告")
    assert basis == "relative_unresolved"


def test_relative_period_with_anchor_is_fact():
    pf, pt, basis, notes = rq.parse_period("近三年的审计报告", anchor_year=2024)
    assert basis == "FACT"
    assert (pf, pt) == (2022, 2024)
    assert notes


def test_relative_month_period_is_unresolved():
    """★ 判别力用例：修复前落 UNKNOWN（闸门被静默丢掉），修复后必须 unresolved。"""
    _pf, _pt, basis, _ = rq.parse_period("最近三个月的财务情况")
    assert basis == "unresolved", "「最近三个月」是期间提及，必须落 unresolved 而不是 UNKNOWN"


def test_this_year_is_unresolved():
    _pf, _pt, basis, _ = rq.parse_period("本年度财务报表")
    assert basis == "unresolved"


def test_last_year_is_unresolved():
    _pf, _pt, basis, _ = rq.parse_period("去年的审计报告")
    assert basis == "unresolved"


def test_no_period_mentioned_is_unknown():
    """★ 「压根没提期间」必须仍是 UNKNOWN（该维度不构成门槛）。"""
    _pf, _pt, basis, _ = rq.parse_period("营业执照正、副本复印件")
    assert basis == "UNKNOWN"


def test_unresolved_and_unknown_are_different():
    """★ 判别力用例：两者必须可区分（否则「提了却解析不出」与「没提」被混为一谈）。"""
    assert rq.parse_period("最近三个月")[2] != rq.parse_period("营业执照")[2]


def test_judge_unresolved_period_is_uncertain_with_reason(tmp_path):
    """端到端：提到期间却解析不出 ⇒ UNCERTAIN 且写明「期间无法解析」。"""
    lib = _setup(tmp_path, {"甲公司/审计报告.pdf": "本报告为2024年度财务审计结论。"})
    _register(tmp_path, lib, "E1", "甲公司")
    st = _obl_status(tmp_path, "最近三个月的审计报告", lib)
    assert st["verdict"] == ms.V_UNCERTAIN
    # ⚠️ missing_detail 是**分号连接的字符串**（不是 list）⇒ 按子串判
    assert "期间无法解析" in (st.get("missing_detail") or "")


def test_judge_unknown_period_is_not_a_threshold(tmp_path):
    """端到端：文本没提期间 ⇒ **不得**因为期间判 UNCERTAIN（该维度不构成门槛）。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.pdf": "营业执照正副本。统一社会信用代码 914301113528442821。"})
    _register(tmp_path, lib, "E1", "甲公司")
    st = _obl_status(tmp_path, "营业执照正、副本复印件", lib)
    assert st["verdict"] != ms.V_UNCERTAIN or "期间" not in (st.get("missing_detail") or "")


# ═══════════════════════════════════════════════════════════════════════
# A2-4 类型维度覆盖口径
# ═══════════════════════════════════════════════════════════════════════


def _result(entity: str, period: str, doctype_ok=True, period_ok=True):
    return {
        "card": {"entity": entity, "fiscal_period": period},
        "manifest": {"library_id": "lib1", "rel_path": f"{entity}/{period}.pdf"},
        "ev": {"doctype_ok": doctype_ok, "period_ok": period_ok,
               "attachment_ok": True, "deliverable": True},
    }


def _obl(**kw):
    base = {"obligation_id": "OB-1",
            "doc_type": "audit_report", "doc_type_basis": "FACT",
            "period_basis": "FACT", "entity_scope": "group_and_subs",
            "caliber": "", "seal_required": False, "needs_attachments": False}
    base.update(kw)
    return base


def test_doctype_cov_denominator_is_entities_times_years():
    """★ 判别力用例：分母 = 主体数 × 年数（2×2=4），只覆盖 2 格 ⇒ cov=0.5。

    若分母被硬编码为 1 或恒置 1 ⇒ cov 会是 1.0 ⇒ 本用例失败。
    """
    obl = _obl(period_from=2023, period_to=2024)
    need = [{"entity_id": "E1", "display_name": "主体甲"},
            {"entity_id": "E2", "display_name": "主体乙"}]
    results = [_result("主体甲", "2023"), _result("主体乙", "2023")]
    st = ms.judge(obl, results, need, capped=False)
    assert st["doctype_cov"] == pytest.approx(0.5, abs=1e-3), (
        f"分母应是 主体数×年数=4，实际 cov={st['doctype_cov']}")


def test_doctype_cov_full_when_all_cells_covered():
    obl = _obl(period_from=2023, period_to=2024)
    need = [{"entity_id": "E1", "display_name": "主体甲"},
            {"entity_id": "E2", "display_name": "主体乙"}]
    results = [_result("主体甲", "2023"), _result("主体乙", "2023"),
               _result("主体甲", "2024"), _result("主体乙", "2024")]
    st = ms.judge(obl, results, need, capped=False)
    assert st["doctype_cov"] == pytest.approx(1.0, abs=1e-3)


def test_doctype_cov_not_constant_one():
    """★ 判别力用例：只覆盖 1/4 时 cov 必须 < 1（不得恒置 1）。"""
    obl = _obl(period_from=2023, period_to=2024)
    need = [{"entity_id": "E1", "display_name": "主体甲"},
            {"entity_id": "E2", "display_name": "主体乙"}]
    results = [_result("主体甲", "2023")]
    st = ms.judge(obl, results, need, capped=False)
    assert st["doctype_cov"] < 1.0


def test_capped_marks_low_confidence():
    """候选池打满 ⇒ 类型维度结论置信度低 ⇒ 必须显式标注。"""
    obl = _obl(period_from=2023, period_to=2024)
    need = [{"entity_id": "E1", "display_name": "主体甲"}]
    st = ms.judge(obl, [_result("主体甲", "2023")], need, capped=True)
    blob = " ".join(str(st.get(k) or "") for k in st)
    assert "置信" in blob, f"capped 时必须标注置信度低，实际 status={st}"
