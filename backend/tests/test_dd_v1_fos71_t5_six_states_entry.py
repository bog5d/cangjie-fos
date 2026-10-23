"""T5：六态（候选为空的原因）**贯通到正式入口**。

本文件锁住四件事：

1. **桥接层透传**：候选为空时，桥接产出的 ``rule_hint`` 里必须带
   ``no_candidate_reason``（语义层算好的**封闭六态**之一），
   而不是只剩一个笼统的 ``MISSING``。
2. **薄入口输出**：正式入口（``tools/dd_team_channel.py``）的机读产物里，
   每条义务都带 ``evidence_status``／``candidate_status``／``diagnostics``；
   人看的报告里也写得出「为什么没有候选」。
3. **六态不被压成一种**：两种不同的空候选场景必须给出**不同**的原因
   ⇒ 证明入口没有把六种原因统一伪装成 ``MISSING``。
4. **可达态数实测**（探针）：生产路径上实测可达 **3/6**；
   另三项在语义层**可写**、但在生产路径**不可达**，各带机械理由。

★ 六态取值域只从权威枚举 ``dd_v1_semantic_retrieval_service.NO_CANDIDATE_REASONS`` 取，
  本文件**不另抄一份**（抄一份就变成第二套表）。
★ 「可写」≠「生产路径可达」——两者在第 4 条里**分开**断言。
★ 跑批作用域：只跑本文件；全量由独立复核席在终态合并面跑。
★ 材料全部**自造合成内容**（零真实客户标识），跑完即删。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

import dd_team_channel as tc  # noqa: E402
from cangjie_fos.services import (  # noqa: E402
    dd_v1_bridge_service as br,
    dd_v1_card_service as cs,
    dd_v1_manifest_service as mf,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
    dd_v1_semantic_retrieval_service as sem,
)

SIX = tuple(sem.NO_CANDIDATE_REASONS)
FOUR = tuple(sem.CANDIDATE_STATUSES)
TOOLS = REPO / "tools"
AUD = "审计报告\n本报告为{year}年度财务审计结论，由{ent}出具。\n"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _synthetic_materials(tmp_path, name: str, n: int = 1, *, draft: bool = False) -> Path:
    """造一个**合成**材料库（主体放在子目录里 ⇒ 主体由卡片推断）。"""
    root = tmp_path / name
    (root / "示例科技").mkdir(parents=True)
    for i in range(n):
        suffix = "草稿" if draft else ""
        (root / "示例科技" / f"审计报告2024{suffix}{i}.txt").write_text(
            AUD.format(year=2024, ent="示例科技"), encoding="utf-8")
    return root


def _build_library(tmp_path, root: Path, lib: str, checklist: list[str]):
    """清单 → 认知卡 → 义务，全部落在 tmp 数据面里（材料**不复制**，只读原路径）。"""
    mf.register_library(lib, str(root), authorized_by="T5", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    rq.ingest_checklist(lib, [{"item_no": str(i + 1), "raw_text": t}
                              for i, t in enumerate(checklist)], db_path=_db(tmp_path))
    return lib


def _bridge(tmp_path, root: Path, lib: str, checklist: list[str]):
    """走**生产路径**（薄入口调用的同一个函数 ``bridge_library``）。"""
    lib = _build_library(tmp_path, root, lib, checklist)
    return br.bridge_library(lib, material_root=root, db_path=_db(tmp_path),
                             allow_real_material=True)


def _empty_rows(out: dict) -> list[dict]:
    """桥接产物里「没有可用候选」的义务行（按语义层口径：原因非空）。"""
    return [ob for ob in out["obligations"]
            if (ob.get("evidence_status") or {}).get("no_candidate_reason")]


# ── 1. 桥接层透传：rule_hint 必须带原因，不能只剩一个笼统的 MISSING ──────────

def test_bridge_rule_hint_carries_no_candidate_reason(tmp_path):
    """候选为空时，规则提示里必须带**封闭六态之一**的原因。"""
    root = _synthetic_materials(tmp_path, "材料1")
    out = _bridge(tmp_path, root, "T5桥接库", ["请提供示例科技的说明材料"])
    rows = _empty_rows(out)
    assert rows, "本场景应当出现「没有可用候选」的义务"
    for ob in rows:
        st = ob["evidence_status"]
        reason = st["no_candidate_reason"]
        assert reason in SIX, f"原因不在封闭六态内：{reason}"
        assert st["candidate_status"] in FOUR, st
        # ★ 透传：规则提示里也带着同一个原因（不是只有一个 verdict）
        assert ob["rule_hint"]["no_candidate_reason"] == reason, ob["rule_hint"]
        # ★ 候选为空 ⇒ 候选状态必须是 NO_CANDIDATE（不是 OK）
        assert st["candidate_status"] == "NO_CANDIDATE", st


# ── 2. 桥接层：每条义务都带结构化状态 ───────────────────────────────────────

def test_bridge_exposes_evidence_status_for_every_obligation(tmp_path):
    """每条义务都带 ``evidence_status``（三键齐全）＋ 候选状态合法。"""
    root = _synthetic_materials(tmp_path, "材料2")
    out = _bridge(tmp_path, root, "T5桥接库2",
                  ["请提供2024年度审计报告", "请提供示例科技的说明材料"])
    assert out["obligations"], out["counts"]
    for ob in out["obligations"]:
        st = ob["evidence_status"]
        assert set(st) >= {"no_candidate_reason", "candidate_status", "diagnostics"}, st
        assert st["candidate_status"] in FOUR, st
        assert isinstance(st["diagnostics"], dict), st
        # 候选不为空 ⇒ 原因必须留空（**不得**谎报「没有材料」）
        if st["candidate_status"] == "OK":
            assert st["no_candidate_reason"] is None, st


# ── 3. 六态不被压成一种：不同场景 ⇒ 不同原因 ────────────────────────────────

def test_two_empty_candidate_scenarios_give_different_reasons(tmp_path):
    """★ 核心：两个空候选场景必须给出**不同**的原因 ⇒ 没有统一伪装成 MISSING。"""
    root_a = _synthetic_materials(tmp_path, "材料A")
    root_b = _synthetic_materials(tmp_path, "材料B")
    a = _bridge(tmp_path, root_a, "T5场景A", ["请提供示例科技2024年度营业执照"])
    b = _bridge(tmp_path, root_b, "T5场景B", ["请提供示例科技的说明材料"])
    ra = {o["evidence_status"]["no_candidate_reason"] for o in _empty_rows(a)}
    rb = {o["evidence_status"]["no_candidate_reason"] for o in _empty_rows(b)}
    assert ra and rb, (ra, rb)
    assert ra != rb, f"两个场景的原因相同 ⇒ 被压成一种：{ra}"
    assert ra <= set(SIX) and rb <= set(SIX), (ra, rb)
    # ★ 两种场景的原因都不许是「笼统的缺材料」这一个标签
    assert len(ra | rb) >= 2, (ra, rb)


# ── 4. 薄入口：机读产物带三键 ──────────────────────────────────────────────

def test_thin_entry_json_carries_three_keys(tmp_path):
    """正式入口的机读形态：每条义务带 ``evidence_status``／``candidate_status``／``diagnostics``。"""
    root = _synthetic_materials(tmp_path, "材料4")
    out = _bridge(tmp_path, root, "T5入口库", ["请提供示例科技的说明材料"])
    payload = tc._bridge_json({"ok": True, "result": out})
    assert payload["ran"] is True
    assert payload["obligations"]
    for ob in payload["obligations"]:
        assert "evidence_status" in ob
        assert "candidate_status" in ob
        assert "diagnostics" in ob
        assert ob["candidate_status"] in FOUR
        assert isinstance(ob["diagnostics"], dict)
    empty = [ob for ob in payload["obligations"] if ob["evidence_status"]["no_candidate_reason"]]
    assert empty, "本场景应当有「没有可用候选」的义务"
    for ob in empty:
        assert ob["evidence_status"]["no_candidate_reason"] in SIX
        assert ob["no_candidate_reason"] == ob["evidence_status"]["no_candidate_reason"]
        assert ob["candidate_status"] == "NO_CANDIDATE"
        # ★ 不是笼统的一个 MISSING：原因必须落在封闭六态里
        assert ob["no_candidate_reason"] != "MISSING"


# ── 5. 薄入口：人看的报告写得出「为什么没有候选」 ───────────────────────────

def test_thin_entry_report_states_why_no_candidate(tmp_path):
    """★ 端到端：跑一次正式入口，报告里必须写得出六态原因（不只是机读 JSON）。"""
    materials = tmp_path / "材料库"
    (materials / "示例科技").mkdir(parents=True)
    (materials / "示例科技" / "审计报告2024.txt").write_text(
        AUD.format(year=2024, ent="示例科技"), encoding="utf-8")
    cl = tmp_path / "清单.tsv"
    cl.write_text("1\t请提供示例科技的说明材料\n", encoding="utf-8")
    env = dict(os.environ)
    env["CANGJIE_DD_V1_DATA_DIR"] = str(tmp_path / "_plane")
    env["CANGJIE_DD_V1_POLICY"] = str(tmp_path / "无策略.json")
    env["PYTHONPATH"] = str(REPO / "backend" / "src")
    r = subprocess.run(
        [sys.executable, str(TOOLS / "dd_team_channel.py"), "run",
         "--library", "T5端到端库", "--root", str(materials),
         "--checklist", str(cl), "--allow-real-material"],
        env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    mds = list((tmp_path / "_plane" / "团队报告").glob("*.md"))
    jss = list((tmp_path / "_plane" / "团队报告").glob("*.json"))
    assert mds and jss, list((tmp_path / "_plane").rglob("*"))
    md = mds[0].read_text(encoding="utf-8")
    data = json.loads(jss[0].read_text(encoding="utf-8"))
    # 机读面：三键确实出去了
    bridge_json = data["semantic_bridge"]
    assert bridge_json["ran"] is True
    assert any(ob.get("no_candidate_reason") for ob in bridge_json["obligations"]), bridge_json
    # 人读面：写得出「为什么没有候选」＋ 六态取值域
    assert "候选为空的义务" in md, md[-3000:]
    assert "UNRESOLVED_DOC_TYPE" in md, md[-3000:]
    for r6 in SIX:
        assert r6 in md, f"报告里没出现六态取值域的一项：{r6}"


# ── 6. 探针：生产路径可达态数实测（「可写」≠「可达」） ──────────────────────

def test_production_reachable_states_measured_three_of_six(tmp_path):
    """★ 探针实测：生产路径（薄入口 ⇒ 桥接 ⇒ 语义层）上可达 **3/6**。

    ★ 另三项在语义层**可写**（反事实可触发），但在生产路径**不可达**：
      · ``NO_MATERIAL``       —— 桥接把义务主体取自「**有该类型材料**的主体」
                                 ⇒ 主体非空 ⇒ 候选池非空 ⇒ 「池为空」那一族分支走不到；
                                 主体为空时又被 ``UNKNOWN_ENTITY`` 先占（判定顺序写死）。
      · ``PERMISSION_BLOCKED`` —— 需要 meta 带 ``access``／``restricted``；
                                 两个生产 meta 生产者（``build_meta``／``cmd_scaffold``）
                                 **都不写**这两个字段 ⇒ 生产路径无生产者。
      · ``OTHER``             —— 需要读材料抛 ``OSError``（``read_errors>0``）；
                                 生产路径在更早的闸口就拒了（``local_material_snapshot``
                                 先校验文件存在，``PermissionError`` 又被原样上抛不计数）。
    """
    observed: set[str] = set()
    # 场景 1：义务侧类型判不出（材料里没有「类型也判不出」的那份）
    root1 = _synthetic_materials(tmp_path, "探针1")
    out1 = _bridge(tmp_path, root1, "T5探针1", ["请提供示例科技的说明材料"])
    observed |= {o["evidence_status"]["no_candidate_reason"] for o in _empty_rows(out1)}
    # 场景 2：该类型无材料 ⇒ 主体取不到 ⇒ UNKNOWN_ENTITY
    root2 = _synthetic_materials(tmp_path, "探针2")
    out2 = _bridge(tmp_path, root2, "T5探针2", ["请提供示例科技2024年度营业执照"])
    observed |= {o["evidence_status"]["no_candidate_reason"] for o in _empty_rows(out2)}
    assert observed == {"UNRESOLVED_DOC_TYPE", "UNKNOWN_ENTITY"}, observed

    # 场景 3：候选超上限且全不可用 ⇒ RETRIEVAL_EXHAUSTED（8 份草稿，超过上限 6）
    root3 = _synthetic_materials(tmp_path, "探针3", n=8, draft=True)
    out3 = _bridge(tmp_path, root3, "T5探针3", ["请提供示例科技2024年度审计报告"])
    ex = {o["evidence_status"]["no_candidate_reason"] for o in out3["obligations"]}
    assert "RETRIEVAL_EXHAUSTED" in ex, out3["obligations"]
    observed |= ex
    assert observed == {"UNRESOLVED_DOC_TYPE", "UNKNOWN_ENTITY", "RETRIEVAL_EXHAUSTED"}, observed
    # ★ 报数口径：3/6，**不是** 6/6（「可写」≠「生产路径可达」）
    assert len(observed) == 3 and observed <= set(SIX)
    assert len(observed) < len(SIX)

    # ③ 生产 meta 生产者都不写 access/restricted ⇒ PERMISSION_BLOCKED 无生产者
    for rel, fn in (("backend/src/cangjie_fos/services/dd_v1_bridge_service.py", "build_meta"),
                    ("tools/dd_v1_local_run.py", "cmd_scaffold")):
        body = (REPO / rel).read_text(encoding="utf-8").split(f"def {fn}", 1)[1][:4000]
        assert '"access"' not in body and '"restricted"' not in body, \
            f"{fn} 疑似写了 access/restricted ⇒ 已知缺口已变化，请更新本用例的可达态数"
