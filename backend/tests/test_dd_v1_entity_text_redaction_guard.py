"""H-3 脱敏**判定文案**那条线的回归守卫（补一处覆盖缺口）。

## 为什么单独一个文件

2026-10-22 A3 §2 判别力回退实验实测发现：
把 `rq.entity_scope_value()` **回退**成「直接写原值」，
**全仓没有任何用例转红** ⇒ **缺口定位文案**这条脱敏线
（`dd_v1_match_service.py::_requirement_summary` 里的
`主体范围={rq.entity_scope_value(obl['entity_scope'])}`）
**此前没有回归守卫**。

★ 顺带澄清一处口径（实测，不是推断）
  - 审核包 Excel 的「主体范围」列**不是**靠 `entity_scope_value()` 保护的 ——
    `dd_v1_package_service._entity_display_map` 对**每个**非空主体范围
    **无条件**分配稳定代号（`主体-1`…），`entity_scope_value()` 在那里
    只喂给一个**计数器**（`stats["masked"]`）；
  - `entity_scope_value()` 真正把关的是**判定文案**（本文件守的就是它）。
  ⇒ 两处是**两套独立机制**，A3-9 词条里「脱敏判定只出现在
    `rq.entity_scope_value()`」这句话**不精确**，本包据实更正。

★ 本文件**不写/不删仓库文件**：全部落在 `tmp_path`。
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_requirement_service as rq

_TEST_POLICY = {
    "policy_version": "test-v1",
    "default_level": "RESTRICTED",
    "levels": {
        "PUBLIC": {"externally_sendable": True, "requires_review": True},
        "INTERNAL": {"externally_sendable": False, "requires_review": True},
        "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True},
        "RESTRICTED": {"externally_sendable": False, "requires_review": True},
    },
    "rules": [],
}

_ENTITY = "示例科技有限公司"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    p = Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _setup(tmp_path, files: dict[str, str]):
    lib = "lib1"
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(lib, str(root), authorized_by="F1", db_path=_db(tmp_path))
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def test_missing_gap_text_never_shows_raw_entity_hint(tmp_path):
    """缺口定位文案**不得**出现主体原值（客户标识）。

    ★ 守的是 A2（G-A2-11）那条线：主体前缀是客户标识 ⇒
      摘要里只写脱敏标签「义务指名的主体（简称）」。
    ★ 本用例是 2026-10-22 A3 §2 判别力回退实验**实测发现覆盖缺口后补的**：
      把 `rq.entity_scope_value()` 回退成写原值，此前**无一条用例转红**。
    """
    # 库里**没有任何材料** ⇒ 义务必然 MISSING ⇒ 才会走「缺口定位摘要」那条路。
    lib = _setup(tmp_path, {})
    rq.register_entity(lib, "S1", _ENTITY, relation="subsidiary",
                       source_ref="工商登记", db_path=_db(tmp_path))
    rq.ingest_checklist(lib, [
        {"item_no": "1", "raw_text": f"{_ENTITY}：最新的营业执照正"}],
        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))

    conn = mf._connect(_db(tmp_path))
    raw = [r[0] for r in conn.execute(
        "SELECT entity_scope FROM dd_v1_obligations").fetchall()]
    raw = [str(x) for x in raw if x]
    assert raw, "前置条件：库里确有 entity_scope 原值"
    hints = [x for x in raw if x.startswith(rq.ENTITY_HINT_PREFIX)]
    assert hints, f"前置条件：entity_scope 必须是客户标识形态：{raw}"

    detail = str(st.get("missing_detail") or "")
    for h in hints:
        assert h not in detail, f"缺口定位文案不得出现主体原值：{detail}"
        assert _ENTITY not in detail, f"缺口定位文案不得出现客户标识：{detail}"
    assert rq.ENTITY_HINT_LABEL in detail, (
        f"必须写脱敏标签（不是删掉这一维）：{detail}")
