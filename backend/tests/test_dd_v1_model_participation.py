"""DD-V1「模型参与语义判断」接线回归：MODEL 与 RULE_ONLY **严格分开**。

## 本文件锁死的六件事

1. **没接适配器 ⇒ 全程 RULE_ONLY**（零外部调用、零费用）；
2. **接了适配器 ⇒ 模型判断真的驱动选材**（答卷里 `selection_source=MODEL`，
   不是「模型跑了但选材还是规则链干的」）；
3. ★ **参与身份只认适配器实现**（`codex-cli`/`dsh`/`pi`/`manual-exchange`）⇒
   替身/未知适配器 ⇒ `UNKNOWN_ADAPTER` ⇒ **不得**计为「模型参与」的凭据；
   贴进来的回执 ⇒ `PREBAKED_RESULT` ⇒ **同样不算**（它不是本机 Harness 运行）；
4. ★ **排除式选择凭据**：模型必须说清「**为什么**不选别的」；
   池里只有一种类型、或它只是「取第一个」⇒ 读数 `WEAK`（如实记账，不吹）；
5. ★ R4 硬校验：排除项必须在快照内、**且不得**是它自己选中���那一件；
6. ★ **凭据不证明模型身份**：回执只说明「哪个适配器、哪次调用、回了什么摘要」。

## 纪律

★ 本文件**不调用任何模型**（沙箱里也没有）⇒ 用**替身适配器**驱动接线，
  替身一律标 `test-standin` ⇒ 参与类别恒为 `UNKNOWN_ADAPTER` ⇒
  **不得**被当成「模型参与了」的证据 —— 这正是本文件要守的那条线。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_agent_adapters as ad,
    dd_v1_agent_result_service as ar,
    dd_v1_bridge_service as br,
    dd_v1_exam_service as ex,
)

_REPO = Path(__file__).resolve().parents[2]
WP04_SNAPSHOT = _REPO / "backend" / "tests" / "fixtures" / "dd_v1_fos71_wp04" / "snapshot"
R4_FIX = _REPO / "backend" / "tests" / "fixtures" / "dd_v1_fos71"
R4_SNAP = R4_FIX / "snapshot"
R4_META = json.loads((R4_FIX / "meta.json").read_text("utf-8"))
R4_OBS = json.loads((R4_FIX / "obligations.json").read_text("utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
# 替身适配器（★ 不是 Harness ⇒ 参与类别恒为 UNKNOWN_ADAPTER）
# ═══════════════════════════════════════════════════════════════════════════

class _StandInAdapter:
    """按 packet 里的证据池**生成一份合规 R4 结果**（模拟一个谨慎的模型）。

    ★ 它**不是**模型，也不是 Harness ⇒ ``adapter_id="test-standin"``
      ⇒ 参与类别必须判成 ``UNKNOWN_ADAPTER``。
    """

    adapter_id, vendor, role = "test-standin", "test", "MANUAL"

    def __init__(self, *, non_default: bool = True, rejected: bool = True):
        self.non_default = non_default
        self.rejected = rejected

    def run(self, packet, workdir, budget):
        res = ad.AdapterResult(self.adapter_id, self.vendor, self.role,
                                status=ad.OK, workdir=str(workdir))
        # ★ 留一条**运行痕迹**（argv 摘要）⇒ 回执里才有可核验的「跑了什么」
        res.argv_summary = ["test-standin", "--fake-run"]
        results = []
        for ob in packet.get("obligations") or []:
            oid = str(ob.get("obligation_id") or "")
            ev = list((packet.get("evidence") or {}).get(oid) or [])
            if not ev:
                continue
            want_entity = str(ob.get("entity") or "")
            hit = [e for e in ev if want_entity and str(e.get("entity") or "") == want_entity]
            pool = hit or ev
            pick = pool[1] if (self.non_default and len(pool) > 1) else pool[0]
            cands = [{"file_id": str(pick.get("file_id") or ""),
                      "relative_path": str(pick.get("relative_path") or ""),
                      "sha256": str(pick.get("sha256") or ""),
                      "locator": str(pick.get("locator") or ""),
                      "entity": str(pick.get("entity") or ""),
                      "period": str(pick.get("period") or ""),
                      "match_reason": "替身：从同主体候选里挑的一份"}]
            rej = []
            if self.rejected and len(pool) > 1:
                rej = [{"file_id": str(pool[0].get("file_id") or ""),
                        "reason": "替身：这份的期间与要求不一致"}]
            results.append({
                "item_id": str(ob.get("source_obligation_id") or oid),
                "obligation_id": oid,
                "agent_id": "standin", "provider": "test",
                "model_id_or_unknown": "UNKNOWN", "prompt_version": "",
                "source_snapshot_id": str(packet.get("source_snapshot_id") or ""),
                "candidate_files": cands,
                "proposed_verdict": "MATCH",
                "confidence_or_uncertain": 0.8,
                "abstain_reason": None, "warnings": [], "elapsed": "UNKNOWN",
                "token_usage_or_UNKNOWN": "UNKNOWN",
                "rejected_alternatives": rej,
            })
        res.raw_text = json.dumps({"results": results}, ensure_ascii=False)
        res.exit_code = 0
        res.provenance = {"note": "替身：测试用，不是模型"}
        return res


# ═══════════════════════════════════════════════════════════════════════════
# 1. 参与身份：只认适配器实现
# ═══════════════════════════════════════════════════════════════════════════


def test_only_known_harness_adapters_are_credited():
    """★ 权威判定：**按实现类**（不是按自填 id）。

    ★ 第 5 轮独立复核缺陷 ②：原先只查 ``adapter_id`` 字符串 ⇒ 自填即可冒充。
      现在判定入口是 :func:`br.adapter_participation_class`（按**实现类**精确匹配）。
    """
    # ── 权威路径：传**适配器对象** ⇒ 按实现类判定
    assert br.adapter_participation_class(ad.CodexAdapter()) == "HARNESS_MODEL"
    assert br.adapter_participation_class(ad.MiniMaxPiAdapter()) == "HARNESS_MODEL"
    assert br.adapter_participation_class(ad.DeepSeekHarnessAdapter()) == "HARNESS_MODEL"
    assert br.adapter_participation_class(ad.ManualExchangeAdapter()) == "HARNESS_MANUAL"
    # ── id 级函数只是**旁证**（它反映「这个 id 在白名单里」，不构成参与主张）
    assert br.adapter_provenance("codex-cli") == "HARNESS_MODEL"
    assert br.adapter_provenance("deepseek-harness") == "HARNESS_MODEL"
    assert br.adapter_provenance("pi") == "HARNESS_MODEL"
    assert br.adapter_provenance("manual-exchange") == "HARNESS_MANUAL"


def test_unknown_adapter_is_not_credited_as_model():
    assert br.adapter_provenance("test-standin") == "UNKNOWN_ADAPTER"
    assert br.adapter_provenance("") == "UNKNOWN_ADAPTER"
    assert br.adapter_provenance("whatever") == "UNKNOWN_ADAPTER"
    # ★ 按实现类判定时：不在注册表里的对象（含替身）一律 UNKNOWN
    assert br.adapter_participation_class(_StandInAdapter()) == "UNKNOWN_ADAPTER"
    assert br.adapter_participation_class(None) == "UNKNOWN_ADAPTER"


class _SpoofAdapter(_StandInAdapter):
    """★ 自填 ``adapter_id="codex-cli"`` 的替身（第 5 轮复核缺陷 ② 的原样复现）。"""

    adapter_id, vendor, role = "codex-cli", "openai-codex", "EXAMINEE_2"


def test_spoof_adapter_with_known_id_is_not_credited_as_model():
    """★ **自填 id 冒充模型 ⇒ 必须落 UNKNOWN_ADAPTER**（缺陷 ② 的负向回归）。

    ★ 旧字节上这条**是红的**：旧实现按 id 字符串查表 ⇒ 直接判成 ``HARNESS_MODEL``。
    """
    spoof = _SpoofAdapter()
    assert spoof.adapter_id == "codex-cli"
    # ★ 权威判定按**实现类** ⇒ 替身（哪怕 id 冒充）**拿不到** HARNESS_MODEL
    assert br.adapter_participation_class(spoof) == "UNKNOWN_ADAPTER"
    # ★ id 级旁证仍会说「这个 id 在白名单里」⇒ 必须与权威判定**分开记**
    assert br.adapter_provenance(spoof.adapter_id) == "HARNESS_MODEL"


def test_prebaked_result_is_not_a_harness_run():
    """★ 贴进来的回执 ⇒ **不是** Harness 运行 ⇒ 不得计为模型凭据。

    ★ 第 5 轮独立复核缺陷 ③：原先 ``KNOWN_HARNESS_ADAPTERS`` 里**没有**
      ``prebaked-result`` ⇒ 真正的 :class:`PrebakedResultAdapter` 落 ``UNKNOWN_ADAPTER``
      （与文档口径「预置回执 ⇒ PREBAKED_RESULT」不符）⇒ 现在两类都对得上。
    """
    assert br.KNOWN_HARNESS_ADAPTERS["prebaked-result"] == "PREBAKED_RESULT"
    assert br.adapter_provenance("prebaked-result") == "PREBAKED_RESULT"
    # ★ 实现类判定同样是 PREBAKED_RESULT（**可达**、且**不是** HARNESS_MODEL）
    assert br.adapter_participation_class(
        ad.PrebakedResultAdapter("/nonexistent/reply.json")) == "PREBAKED_RESULT"
    assert br.adapter_participation_class(
        ad.PrebakedResultAdapter("/nonexistent/reply.json")) != "HARNESS_MODEL"


def test_build_adapter_returns_none_for_rule_only():
    assert ad.build_adapter("") is None
    assert ad.build_adapter("none") is None


def test_build_adapter_prebaked_needs_a_path():
    with pytest.raises(ValueError):
        ad.build_adapter("prebaked")


# ═══════════════════════════════════════════════════════════════════════════
# 2. R4：排除式凭据的硬校验
# ═══════════════════════════════════════════════════════════════════════════


def _result(**over):
    s = ar.load_snapshot(R4_SNAP, R4_META)
    f = s["F001"]
    r = {"item_id": "S1", "obligation_id": "S1-O1", "agent_id": "t", "provider": "test",
         "model_id_or_unknown": "UNKNOWN", "prompt_version": ar.PROMPT_VERSION,
         "source_snapshot_id": ar.snapshot_id(s),
         "candidate_files": [{"file_id": "F001", "relative_path": f.relative_path,
                              "sha256": f.sha256, "locator": "UNKNOWN",
                              "entity": f.entity, "period": f.period, "match_reason": "r"}],
         "proposed_verdict": "MATCH", "confidence_or_uncertain": 0.9,
         "abstain_reason": None, "warnings": [], "elapsed": "UNKNOWN",
         "token_usage_or_UNKNOWN": "UNKNOWN"}
    r.update(over)
    return r


def _run(results):
    return ar.validate_agent_output(json.dumps({"results": results}), R4_SNAP, R4_META, R4_OBS)


def test_valid_rejected_alternatives_are_accepted():
    s = ar.load_snapshot(R4_SNAP, R4_META)
    other = [k for k in s if k != "F001"][0]
    rep = _run([_result(rejected_alternatives=[{"file_id": other, "reason": "主体不符"}])])
    assert rep.accepted, rep.rejected
    assert rep.accepted[0]["rejected_alternatives"][0]["file_id"] == other


def test_rejected_alternative_not_in_snapshot_is_rejected():
    rep = _run([_result(rejected_alternatives=[{"file_id": "F999", "reason": "编的"}])])
    assert not rep.accepted
    assert any("REJECTED_ALT_0_NOT_IN_SNAPSHOT" in e
               for e in rep.rejected[0]["errors"]), rep.rejected


def test_rejected_alternative_cannot_be_the_picked_file():
    rep = _run([_result(rejected_alternatives=[{"file_id": "F001", "reason": "自相矛盾"}])])
    assert not rep.accepted
    assert any("REJECTED_ALT_0_IS_PICKED" in e
               for e in rep.rejected[0]["errors"]), rep.rejected


def test_rejected_alternative_needs_a_reason():
    rep = _run([_result(rejected_alternatives=[{"file_id": "F002"}])])
    assert not rep.accepted
    assert any("REJECTED_ALT_0_MISSING_FIELDS" in e
               for e in rep.rejected[0]["errors"]), rep.rejected


# ═══════════════════════════════════════════════════════════════════════════
# 3. 排除式读数：PASS / WEAK
# ═══════════════════════════════════════════════════════════════════════════


def test_discrimination_pass_requires_multitype_pool_nondefault_and_reason():
    pool = [{"file_id": "A", "doc_type": "audit_report"},
            {"file_id": "B", "doc_type": "license"}]
    r = br._discrimination_readings(pool, ["B"], [{"file_id": "A", "reason": "期间不符"}])
    assert r["discrimination"] == "PASS", r
    assert r["pool_doc_type_count"] == 2
    assert r["non_default_pick"] is True
    assert r["rejected_with_reason"] == 1


def test_discrimination_weak_when_pool_has_single_type():
    pool = [{"file_id": "A", "doc_type": "audit_report"},
            {"file_id": "B", "doc_type": "audit_report"}]
    r = br._discrimination_readings(pool, ["B"], [{"file_id": "A", "reason": "x"}])
    assert r["discrimination"] == "WEAK", r
    assert r["pool_doc_type_count"] == 1


def test_discrimination_weak_when_pick_is_the_first():
    pool = [{"file_id": "A", "doc_type": "audit_report"},
            {"file_id": "B", "doc_type": "license"}]
    r = br._discrimination_readings(pool, ["A"], [{"file_id": "B", "reason": "x"}])
    assert r["discrimination"] == "WEAK", r
    assert r["non_default_pick"] is False


def test_discrimination_weak_when_no_rejection_recorded():
    pool = [{"file_id": "A", "doc_type": "audit_report"},
            {"file_id": "B", "doc_type": "license"}]
    r = br._discrimination_readings(pool, ["B"], [])
    assert r["discrimination"] == "WEAK", r
    assert r["rejected_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. 答卷层：MODEL 与 RULE_ONLY 严格分开
# ═══════════════════════════════════════════════════════════════════════════


def _pkt():
    return {
        "obligations": [{"obligation_id": "O1", "item_id": "I1", "text": "提供审计报告",
                         "entity": "子公司甲", "entity_basis": "AUTHORITY",
                         "period": "2024", "doc_type": "audit_report"}],
        "evidence": {"O1": [{"file_id": "F1", "sha256": "a" * 64,
                             "relative_path": "a.txt", "locator": "L1",
                             "entity": "子公司甲", "period": "2024",
                             "doc_type": "audit_report"}]},
        "rule_hints": {"O1": {"verdict": "MATCH", "files": ["F1"]}},
    }


def test_answer_sheet_without_model_is_rule_only():
    sheet = ex.build_answer_sheet({}, _pkt())
    assert sheet["examinee"]["mode"] == "RULE_ONLY", sheet["examinee"]
    assert sheet["obligations"][0]["selection_source"] == "RULE_HINT"
    assert sheet["examinee"]["model_selection_obligations"] == 0


def test_answer_sheet_with_model_results_marks_model_selection():
    rec = {"semantic_validation": {"accepted": [{
        "obligation_id": "O1", "item_id": "I1", "agent_id": "a", "provider": "p",
        "model_id_or_unknown": "UNKNOWN", "source_snapshot_id": "",
        "candidate_files": [{"file_id": "F1", "sha256": "a" * 64,
                             "relative_path": "a.txt", "locator": "L1",
                             "entity": "子公司甲", "period": "2024",
                             "match_reason": "r"}],
        "proposed_verdict": "MATCH", "confidence_or_uncertain": 0.9,
        "abstain_reason": None, "warnings": [], "elapsed": "UNKNOWN",
        "token_usage_or_UNKNOWN": "UNKNOWN"}], "rejected": [], "mode": "AGENT_SUGGESTION"},
        "adapter": {"adapter_id": "test-standin", "vendor": "test",
                    "status": "OK", "provenance": "UNKNOWN_ADAPTER"}}
    sheet = ex.build_answer_sheet(rec, _pkt())
    assert sheet["obligations"][0]["selection_source"] == "MODEL", sheet["obligations"][0]
    assert sheet["examinee"]["mode"] == "UNKNOWN_ADAPTER", sheet["examinee"]
    assert sheet["examinee"]["model_selection_obligations"] == 1
    # ★ 替身**不得**被当成模型凭据
    assert sheet["examinee"]["mode"] != "HARNESS_MODEL"


def test_answer_sheet_marks_prebaked_result_distinctly():
    rec = {"semantic_validation": {"accepted": [{
        "obligation_id": "O1", "item_id": "I1", "agent_id": "a", "provider": "p",
        "model_id_or_unknown": "UNKNOWN", "source_snapshot_id": "",
        "candidate_files": [{"file_id": "F1", "sha256": "a" * 64,
                             "relative_path": "a.txt", "locator": "L1",
                             "entity": "子公司甲", "period": "2024",
                             "match_reason": "r"}],
        "proposed_verdict": "MATCH", "confidence_or_uncertain": 0.9,
        "abstain_reason": None, "warnings": [], "elapsed": "UNKNOWN",
        "token_usage_or_UNKNOWN": "UNKNOWN"}], "rejected": [], "mode": "AGENT_SUGGESTION"},
        "adapter": {"adapter_id": "prebaked-result", "vendor": "operator-prebaked",
                    "status": "OK", "provenance": "PREBAKED_RESULT"}}
    sheet = ex.build_answer_sheet(rec, _pkt())
    assert sheet["examinee"]["mode"] == "PREBAKED_RESULT", sheet["examinee"]
    assert sheet["obligations"][0]["selection_source"] == "MODEL"


def test_model_selection_without_receipt_is_labelled():
    """★ 有模型选材、但**没有回执** ⇒ 必须标出来（不许装作正常模型参与）。"""
    rec = {"semantic_validation": {"accepted": [{
        "obligation_id": "O1", "item_id": "I1", "agent_id": "a", "provider": "p",
        "model_id_or_unknown": "UNKNOWN", "source_snapshot_id": "",
        "candidate_files": [{"file_id": "F1", "sha256": "a" * 64,
                             "relative_path": "a.txt", "locator": "L1",
                             "entity": "子公司甲", "period": "2024",
                             "match_reason": "r"}],
        "proposed_verdict": "MATCH", "confidence_or_uncertain": 0.9,
        "abstain_reason": None, "warnings": [], "elapsed": "UNKNOWN",
        "token_usage_or_UNKNOWN": "UNKNOWN"}], "rejected": [], "mode": "AGENT_SUGGESTION"}}
    sheet = ex.build_answer_sheet(rec, _pkt())
    assert sheet["examinee"]["mode"] == "MODEL_SELECTION_WITHOUT_RECEIPT", sheet["examinee"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. 端到端：桥接 → 模型选材 → 答卷（接线真的通了）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    from cangjie_fos.services import dd_v1_manifest_service as mf
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _build_library(tmp_path, root: Path, lib: str, checklist):
    from cangjie_fos.services import (dd_v1_card_service as cs,
                                      dd_v1_manifest_service as mf,
                                      dd_v1_parser_service as ps,
                                      dd_v1_requirement_service as rq)
    mf.register_library(lib, str(root), authorized_by="MP", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    rq.ingest_checklist(lib, [{"item_no": str(i + 1), "raw_text": t}
                              for i, t in enumerate(checklist)], db_path=_db(tmp_path))
    return lib


def test_bridge_with_standin_produces_model_selection(tmp_path):
    """★ 端到端：接了适配器 ⇒ 桥接产出**模型选材** ＋ 回执 ＋ 排除式读数。"""
    lib = _build_library(tmp_path, WP04_SNAPSHOT, "模型参与库",
                         ["子公司甲：提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=WP04_SNAPSHOT, db_path=_db(tmp_path),
                            adapter=_StandInAdapter())
    assert out["mode"] == "AGENT_SUGGESTION", out["mode"]
    assert out["model_participation"]["participated"] is True, out["model_participation"]
    # ★ 替身 ⇒ 参与类别必须判成 UNKNOWN_ADAPTER（**不得**计为模型凭据）
    assert out["model_participation"]["provenance"] == "UNKNOWN_ADAPTER", out["model_participation"]
    rc = out["agent_receipt"]
    assert rc["adapter_id"] == "test-standin", rc
    assert rc["raw_digest"].startswith("sha256:"), rc
    picked = [ob for ob in out["obligations"] if ob.get("model_selection")]
    assert picked, out["obligations"]
    d = picked[0]["model_selection"]["discrimination"]
    assert d["pool_size"] >= 1, d
    assert d["discrimination"] in ("PASS", "WEAK"), d
    # ★ 回执**不证明**模型身份
    assert "不证明" in str(rc.get("note") or ""), rc


def test_bridge_without_adapter_is_rule_only(tmp_path):
    """★ 没接适配器 ⇒ RULE_ONLY ＋ 零外部调用（既有行为一字不变）。"""
    lib = _build_library(tmp_path, WP04_SNAPSHOT, "纯规则库",
                         ["子公司甲：提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=WP04_SNAPSHOT, db_path=_db(tmp_path))
    assert out["mode"] == "RULE_ONLY", out["mode"]
    assert out["external_model_calls"] == 0, out
    assert out["model_participation"]["participated"] is False, out["model_participation"]
    assert out["model_participation"]["provenance"] == "RULE_ONLY", out["model_participation"]
    assert all(not ob.get("model_selection") for ob in out["obligations"]), out["obligations"]


def test_cli_bridge_to_answer_sheet_carries_model_selection(tmp_path):
    """★ CLI 路径：桥接 JSON → 机器答卷 ⇒ 选材来源标 MODEL、参与类别如实标。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dd_cli", _REPO / "tools" / "dd_team_channel.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    lib = _build_library(tmp_path, WP04_SNAPSHOT, "CLI模型库",
                         ["子公司甲：提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=WP04_SNAPSHOT, db_path=_db(tmp_path),
                            adapter=_StandInAdapter())
    rec, pkt = {}, cli._answer_sheet_from_bridge(out)
    _acc = pkt.pop("_accepted", []) or []
    assert _acc, "桥接里的模型选材必须能还原成答卷消费的形状"
    rec["semantic_validation"] = {"accepted": _acc, "rejected": [], "mode": "AGENT_SUGGESTION"}
    rc = pkt.get("agent_receipt") or {}
    rec["adapter"] = {"adapter_id": rc.get("adapter_id"), "vendor": rc.get("vendor"),
                      "status": rc.get("status"),
                      "provenance": rc.get("provenance")}
    sheet = ex.build_answer_sheet(rec, pkt)
    assert sheet["obligations"][0]["selection_source"] == "MODEL", sheet["obligations"][0]
    assert sheet["examinee"]["mode"] == "UNKNOWN_ADAPTER", sheet["examinee"]


def test_bridge_receipt_judges_identity_by_implementation_not_by_id(tmp_path):
    """★ 缺陷 ② 的**端到端**负向回归：自填 id 的替身 ⇒ 回执**不得**出现 HARNESS_MODEL。

    ★ 旧字节上这条**是红的**：回执的 `provenance` 只看 `adapter_id` 字符串
      ⇒ 替身冒充 ⇒ 直接落 `HARNESS_MODEL`（= 一条假凭据）。
    """
    lib = _build_library(tmp_path, WP04_SNAPSHOT, "冒充库",
                         ["子公司甲：提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=WP04_SNAPSHOT, db_path=_db(tmp_path),
                            adapter=_SpoofAdapter())
    rc = out["agent_receipt"]
    # ★ 权威判定（按实现类）⇒ 冒充者**拿不到**模型凭据
    assert rc["provenance"] == "UNKNOWN_ADAPTER", rc
    assert rc["provenance_source"] == "ADAPTER_IMPLEMENTATION", rc
    assert rc["implementation_verified"] is False, rc
    # ★ id 级旁证仍会说「这个 id 在白名单里」⇒ 必须**分开记**且**标出不一致**
    assert rc["declared_provenance"] == "HARNESS_MODEL", rc
    assert rc["provenance_mismatch"] is True, rc
    # ★ 最外层读数同样不得宣称模型参与
    assert out["model_participation"]["provenance"] == "UNKNOWN_ADAPTER", out["model_participation"]


def test_bridge_receipt_carries_verifiable_run_traces(tmp_path):
    """★ 回执要带**可核验运行痕迹**（跑了什么），不只带一个自报 id。"""
    lib = _build_library(tmp_path, WP04_SNAPSHOT, "痕迹库",
                         ["子公司甲：提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=WP04_SNAPSHOT, db_path=_db(tmp_path),
                            adapter=_StandInAdapter())
    rc = out["agent_receipt"]
    assert rc["raw_digest"].startswith("sha256:"), rc
    assert rc["argv_digest"].startswith("sha256:"), rc
    assert "workdir_digest" in rc, rc
    assert rc["provenance_source"] == "ADAPTER_IMPLEMENTATION", rc
