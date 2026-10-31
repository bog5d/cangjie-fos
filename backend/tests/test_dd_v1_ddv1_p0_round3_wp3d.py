"""WP3-d 收口：候选窗口触顶的读数必须**透出到用户可见面**（禁静默漏检）。

## 为什么必须有这个文件（★独立 Reviewer 在终局复核阶段抓出来的★）

`d03de17c` 把 6 个截断读数（``candidate_cap`` / ``candidates_total`` /
``candidates_used`` / ``candidate_truncated`` / ``truncated_candidate_count`` /
``candidate_cap_note``）加到了 ``retrieve_minimal_evidence_detailed`` 的**返回值**里，
★**但 ``build_semantic_packet`` 组 ``evidence_status`` 时只搬了 4 个键**
⇒ 那 6 个键**在 packet 层被丢掉** ⇒

- ``dd_v1_bridge_service`` 读的 ``st.get("candidate_truncated")`` **永远是 None**
  ⇒ ``:497`` 的 ``if _st.get("candidate_truncated")`` **永假**
  ⇒ 「N 条义务的候选窗口已达上限，合计还有 M 份候选未看」这条 **warnings 永不触发**；
- ``tools/dd_v1_local_run.py``（DSH 路径）读**同一个容器** ⇒ **同样读不到**。

⇒ ★**语义层窗口是 ``MAX_FILES_PER_OBLIGATION = 6``（★默认触发的就是它★）**
⇒ ★**触顶时用户侧「一切正常」，而实际还有 N 份候选没看 ⇒ 静默漏检成立**
⇒ ★**且交接文档 §2.3 / §3 当时正告诉操作员「语义层触顶会显式报数」—— ★那是假的**。

## 本文件锁死的判据

1. **packet 层**（★判据 A★）：``packet["evidence_status"][oid]`` 必须带齐那 6 个读数，
   且 ``candidate_truncated=True``、``truncated_candidate_count`` ＝ 真实未看份数、
   ``candidate_cap`` ＝ 6、``candidates_used`` ＝ 6、``candidates_total`` ＞ 6、
   ``candidate_cap_note`` 非空且含「未看」；
2. **bridge 层**（★判据 B★）：``bridge_library(...)`` 返回的 ``warnings`` 里必须出现
   「已达候选上限」（★**这条才是真正卡住缺陷的那条**★）。

## 纪律

- 全部材料**现场合成**（tmp_path），**零真实材料 / 零模型 / 零费用**；
- **不读 Gold Set**（``gold.json`` / ``frozen/grader/`` 一律不碰）；
- ★**只走规则层（RULE_ONLY）**，不接任何适配器 ⇒ 零外部调用；
- ★**``allow_real_material=True`` 只是路径闸**（材料根不在 ``tests/fixtures`` 下），
  ★**材料本身全部是本文件现场合成的字符串**，不含任何真实信息。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_bridge_service as bs,
    dd_v1_card_service as cs,
    dd_v1_manifest_service as mf,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
    dd_v1_semantic_retrieval_service as sem,
)

#: 合成主体（虚构，不含任何真实机构名）
PARENT = "合成甲控股母公司"
LIB = "lib-wp3d"

#: 语义层窗口上限（产品侧常量，测试**引用**它，禁另抄一份数字）
CAP = sem.MAX_FILES_PER_OBLIGATION
#: 候选池份数 ＝ 上限 + 2 ⇒ 必然触顶，且未看份数恰为 2
POOL = CAP + 2


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """每个用例独立数据面 + 独立库（零交叉污染）。"""
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path) -> Path:
    return tmp_path / "_plane" / "manifest.sqlite"


def _audit(y: int, i: int) -> str:
    return (f"审计报告\n主体：{PARENT}\n"
            f"本报告为{y}年度财务审计结论（第{i}份），由{PARENT}出具。\n")


def _setup(tmp_path):
    """建库 → 扫描 → 解析 → 建卡 → 登记主体 → 摄取清单。返回 (lib, root)。"""
    root = tmp_path / "materials"
    (root / PARENT).mkdir(parents=True, exist_ok=True)
    for i in range(POOL):
        (root / PARENT / f"审计报告2024-{i:02d}.txt").write_text(
            _audit(2024, i), encoding="utf-8")
    mf.register_library(LIB, str(root), authorized_by="WP3D", db_path=_db(tmp_path))
    mf.build_manifest(LIB, db_path=_db(tmp_path))
    ps.parse_pending_batch(LIB, db_path=_db(tmp_path))
    cs.build_cards_for_library(LIB, db_path=_db(tmp_path))
    rq.register_entity(LIB, "E1", PARENT, relation="parent",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    rq.ingest_checklist(LIB, [{"item_no": "1",
                               "raw_text": f"请提供{PARENT}2024年度审计报告"}],
                        db_path=_db(tmp_path))
    return LIB, root


def _packet_and_status(tmp_path, lib, root):
    """走**桥接链同款**路径产出 packet（★不是手搓 meta★）。"""
    meta, _stats = bs.build_meta(lib, db_path=_db(tmp_path))
    obl_rows = rq.list_obligations(lib, db_path=_db(tmp_path))
    obl_out, _s = bs.build_semantic_obligations(obl_rows, meta, library_id=lib,
                                                db_path=_db(tmp_path))
    assert obl_out, "应产出语义义务"
    pkt = sem.build_semantic_packet(root, meta, [], obligations=obl_out)
    st_map = pkt.get("evidence_status") or {}
    assert st_map, "packet 必须带 evidence_status"
    return pkt, next(iter(st_map.values()))


def test_A_packet_surfaces_candidate_truncation_readings(tmp_path):
    """★判据 A★：**packet 层**必须带齐 6 个截断读数（★本条在修产品码之前是红的★）。"""
    lib, root = _setup(tmp_path)
    _pkt, st = _packet_and_status(tmp_path, lib, root)

    for k in ("candidate_cap", "candidates_total", "candidates_used",
              "candidate_truncated", "truncated_candidate_count",
              "candidate_cap_note"):
        assert k in st, (
            f"packet.evidence_status **缺**截断读数 {k!r} ⇒ 该读数在 packet 层被丢掉，"
            f"桥接层/DSH 路径永远读不到（静默漏检）。实际内容：{st}")

    assert st["candidate_truncated"] is True, st
    assert st["candidate_cap"] == CAP, st
    assert st["candidates_total"] == POOL, st
    assert st["candidates_used"] == CAP, st
    assert st["truncated_candidate_count"] == POOL - CAP, st
    assert "未看" in (st["candidate_cap_note"] or ""), st


def test_B_bridge_warns_when_candidate_window_truncated(tmp_path):
    """★判据 B★：**桥接层**必须就候选触顶告警（★本条在修产品码之前是红的★）。

    ★ 这是真正卡住缺陷的那条：语义层算对了，但 warnings 分支永不触发 ⇒
      操作员侧「一切正常」，而实际还有 N 份候选没看。
    """
    lib, root = _setup(tmp_path)
    # ★ allow_real_material=True **只是路径闸**（材料根不在 tests/fixtures 下）；
    #   材料本身是本文件现场合成的字符串，零真实信息。
    res = bs.bridge_library(lib, material_root=root, db_path=_db(tmp_path),
                            allow_real_material=True)
    warns = res.get("warnings") or []
    # ★ 产品侧原话：「N 条义务的候选窗口已达上限，合计还有 M 份候选未看」
    hit = [w for w in warns if "候选窗口已达上限" in w]
    assert hit, (
        "桥接层必须就「候选窗口触顶」告警（还有 N 份候选未看）⇒ "
        f"当前 warnings={warns}（静默漏检）")
    assert "份候选未看" in hit[0], hit
    assert "不得" in hit[0] and "不存在" in hit[0], \
        f"告警必须写明「未看部分不得当作不存在」：{hit[0]}"
