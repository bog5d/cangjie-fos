"""DD-V1 **第三层自动考试**：**真实模型参与证明**（participated=true 必须有证据）。

对应施工令 WP2「第三层：真实模型自动考试」。

★ **本层的三条铁律**：
  1. **RULE_ONLY 不得冒充 HARNESS_MODEL**（没接模型 ⇒ participated=false，
     且选材来源必须标 ``RULE_HINT``）；
  2. **participated=true 必须有可核验证据**（真实进程 / 真实回执 / 盖章来源
     ``provenance_source=ADAPTER_IMPLEMENTATION`` / 可复算的指纹）；
  3. **模型失败必须报错**（不得静默降级成「跑过了」）。

★ **本文件里跑的是「本机真进程 harness」**（真的起子进程、真的收 stdout、真的盖章）
  ⇒ 用来证明**参与证明机制本身**是可靠的；
  ★ **它不等于「真实 DeepSeek 跑过了」** ⇒ 真实 DeepSeek 的那一次是
  ``test_real_deepseek_harness_probe``（**显式 opt-in**：默认 skip，
  由 ``DDV1_ALLOW_REAL_MODEL=1`` 打开；只喂**合成**材料）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

from cangjie_fos.services import dd_v1_agent_adapters as ad  # noqa: E402
from cangjie_fos.services import dd_v1_bridge_service as br  # noqa: E402
from cangjie_fos.services import dd_v1_exam_service as ex  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 1. RULE_ONLY 不得冒充模型参与
# ─────────────────────────────────────────────────────────────────────────────

def test_rule_only_run_is_not_credited_as_model_participation():
    """★ 不接适配器 ⇒ ``RULE_ONLY`` ⇒ participated=false、选材来源 RULE_HINT。"""
    packet = {"obligations": [{"obligation_id": "o1", "item_id": "1-1", "text": "t"}],
              "evidence": {}, "rule_hints": {}}
    sheet = ex.build_answer_sheet({}, packet)
    assert sheet.get("examinee", {}).get("mode") == "RULE_ONLY", sheet.get("examinee")
    assert not sheet.get("examinee", {}).get("participated"), sheet.get("examinee")
    for row in sheet.get("obligations") or []:
        assert row.get("selection_source") in ("", "RULE_HINT"), row


def test_spoofed_adapter_id_is_not_credited():
    """★ 自造 ``adapter_id`` 冒充已知 harness ⇒ **拿不到** HARNESS_MODEL 类别。"""
    class _Spoof:
        adapter_id = "codex-cli"
        vendor = "spoof"

        @property
        def participation_class(self):  # pragma: no cover - 只看实现来源
            return "HARNESS_MODEL"

    assert ad.participation_class_of(_Spoof()) != "HARNESS_MODEL"
    assert ad.declared_class_of("codex-cli") == "HARNESS_MODEL"
    # ★ 真认的是**实现来源**（id → 类别的映射 ＋ 实现类），不是自填字段
    assert br.KNOWN_HARNESS_ADAPTERS.get("prebaked-result") == "PREBAKED_RESULT"
    assert br.KNOWN_HARNESS_ADAPTERS.get("deepseek-harness") == "HARNESS_MODEL"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 本机真进程 harness：participated=true 必须有可核验证据
# ─────────────────────────────────────────────────────────────────────────────

_FAKE_HARNESS = '''#!/usr/bin/env python3
"""假 harness：**真的**起进程、真的读 stdin、真的吐 JSON。

★ 它把**收到的请求指纹**原样回吐 ⇒ 外部可核验「请求确实发出去了」。
"""
import hashlib, json, sys, time

payload = sys.stdin.read()
sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
out = {
    "results": [],
    "echo_prompt_sha256": sha,
    "echo_prompt_bytes": len(payload),
    "echo_started_at": time.time(),
}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''


def test_real_process_harness_is_credited_with_verifiable_evidence(tmp_path):
    """★ 真进程 harness 跑通 ⇒ 证据可核验（进程确实启动 / 请求确实发出 / 响应确实收到）。

    ★ 核验点（缺一不可）：
      · 真的起了**子进程**（argv 有记录、有退出码）；
      · 真的把请求**发出去**（子进程回吐的请求指纹 == 本地算出的指纹）；
      · 真的收到**响应**（stdout 有内容、落盘可复核）；
      · 参与类别由**适配器实现**判定（不是自填字段）。
    """
    hp = tmp_path / "fake_harness.py"
    hp.write_text(_FAKE_HARNESS, encoding="utf-8")
    binary = [sys.executable, str(hp)]
    adapter = ad.DeepSeekHarnessAdapter(enabled=True, binary=binary, profile="headless")
    packet = {"obligations": [{"obligation_id": "o1", "item_id": "1-1", "text": "t"}],
              "instructions": "合成任务", "schema": "x"}
    wd = tmp_path / "wd"
    wd.mkdir()
    res = adapter.run(packet, wd, ad.Budget(timeout_s=30.0, max_calls=1))
    assert res.status == ad.OK, res
    assert res.exit_code == 0, res
    assert (res.elapsed_s or 0) >= 0, res
    assert res.argv_summary, "★ 必须记录真实 argv（可核验「进程确实启动」）"
    assert (wd / "answer.txt").is_file(), "★ 响应必须落盘（可复核）"
    # 请求确实发出：子进程回吐的指纹 == 我们这边算的 prompt 指纹
    import hashlib
    expect = hashlib.sha256(ad._prompt_for(packet, "deepseek-harness",
                                            "deepseek-harness", inline=True).encode()).hexdigest()
    assert res.raw_text and expect in res.raw_text, \
        "★ 证据不足：子进程没收到我们发出的请求（指纹对不上）"
    # 参与类别：认实现，不认自填
    assert ad.participation_class_of(adapter) == "HARNESS_MODEL"


def test_answer_sheet_marks_model_selection_when_model_answered(tmp_path):
    """★ 模型真的答了 ⇒ 答卷标 ``selection_source=MODEL``（不是 RULE_HINT）。"""
    packet = {
        "obligations": [{"obligation_id": "o1", "item_id": "1-1", "text": "t",
                         "doc_type": "audit_report"}],
        "evidence": {"o1": [{"file_id": "f1", "sha256": "a" * 64,
                             "relative_path": "x.txt", "locator": "L1",
                             "entity": "主体甲", "period": "2024"}]},
        "rule_hints": {"o1": {"files": ["f1"], "verdict": "MATCH"}},
        # ★ 回执口径（RECEIPT）：答卷只认「盖章 ＋ 回执口径」⇒ 参与才算数
        "model_participation": {"provenance": "HARNESS_MODEL",
                                "provenance_source": "ADAPTER_IMPLEMENTATION",
                                "declared_provenance": "HARNESS_MODEL",
                                "participated": True,
                                "participated_scope": "RECEIPT",
                                "run_participated": True,
                                "run_participated_scope": "RECEIPT"},
    }
    rec = {"semantic_validation": {"accepted": [{
        "obligation_id": "o1", "item_id": "1-1", "agent_id": "fake",
        "provider": "local", "model_id_or_unknown": "FAKE-LOCAL-HARNESS",
        "prompt_version": "", "source_snapshot_id": "",
        "candidate_files": [{"file_id": "f1", "sha256": "a" * 64,
                             "relative_path": "x.txt", "locator": "L1",
                             "entity": "主体甲", "period": "2024"}],
        "proposed_verdict": "MATCH", "proposed_doc_type": "audit_report",
        "confidence_or_uncertain": "HIGH", "abstain_reason": "", "warnings": [],
        "elapsed": 0, "token_usage_or_UNKNOWN": "UNKNOWN",
        "rejected_alternatives": [],
    }], "rejected": [], "mode": "AGENT_SUGGESTION"}}
    sheet = ex.build_answer_sheet(rec, packet)
    row = (sheet.get("obligations") or [])[0]
    assert row.get("selection_source") == "MODEL", row
    assert sheet.get("examinee", {}).get("mode") != "RULE_ONLY", sheet.get("examinee")


def test_missing_stamp_means_not_participated(tmp_path):
    """★ 回执**缺盖章** ⇒ participated 默认 **False**（认不出就当没有参与）。"""
    packet = {"obligations": [{"obligation_id": "o1", "item_id": "1-1", "text": "t"}],
              "evidence": {}, "rule_hints": {}}
    rec = {"model_participation": {"provenance": "HARNESS_MODEL"}}  # ★ 无盖章
    sheet = ex.build_answer_sheet(rec, packet)
    assert sheet.get("examinee", {}).get("participated") is False, sheet.get("examinee")


# ─────────────────────────────────────────────────────────────────────────────
# 3. 真实 DeepSeek（**显式 opt-in**，只喂合成材料）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(os.environ.get("DDV1_ALLOW_REAL_MODEL") != "1",
                    reason="真实模型调用需显式打开（DDV1_ALLOW_REAL_MODEL=1）；"
                           "只允许喂**合成**材料")
def test_real_deepseek_harness_probe():
    """★ 真实 DeepSeek Harness 跑一次合成任务 ⇒ participated=true 且证据可核验。

    ★ **前置**：本机装了 ``dsh`` 且 ``~/.dsh`` 里配好了凭证；
      未满足 ⇒ 断言失败并写明「真实模型未验证」（**不得**用 RULE_ONLY 冒充）。
    """
    import shutil
    dsh = shutil.which("dsh")
    assert dsh, "★ 本机没有 dsh ⇒ 真实模型层未验证（不得用 RULE_ONLY 冒充）"
    adapter = ad.DeepSeekHarnessAdapter(enabled=True, binary=[dsh], profile="headless")
    wd = Path(os.environ.get("DDV1_REAL_MODEL_WD") or (REPO / ".audit" / "real-model"))
    wd.mkdir(parents=True, exist_ok=True)
    packet = {"obligations": [{"obligation_id": "o1", "item_id": "1-1",
                                "text": "请提供合成母公司2024年度审计报告",
                                "doc_type": "audit_report"}],
              "instructions": "只输出 JSON；这是合成测试材料。",
              "schema": "x"}
    res = adapter.run(packet, wd, ad.Budget(timeout_s=300.0, max_calls=1))
    evidence = {
        "adapter_id": res.adapter_id, "status": res.status, "exit_code": res.exit_code,
        "elapsed_s": res.elapsed_s, "argv_summary": res.argv_summary,
        "provenance": res.provenance, "workdir": str(wd),
    }
    (wd / "real-model-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), "utf-8")
    assert res.status == ad.OK, f"真实模型调用失败：{evidence}"
    assert res.exit_code == 0, evidence
    assert res.raw_text, "★ 必须收到真实响应"
