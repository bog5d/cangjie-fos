"""cangjie-fos#71 WP03：Agent Adapter（用假 CLI，不调用真实模型、不联网）。"""
from __future__ import annotations

import json
import stat
import sys
import time
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_adapters as ad
from cangjie_fos.services import dd_v1_agent_result_service as ar

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71"
SNAP = FX / "snapshot"
META = json.loads((FX / "meta.json").read_text("utf-8"))
OBS = json.loads((FX / "obligations.json").read_text("utf-8"))

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake CLIs are POSIX shell scripts")


def _good_results(agent="fake"):
    s = ar.load_snapshot(SNAP, META)
    sid = ar.snapshot_id(s)

    def r(oid, item, verdict, fid=None, reason=None):
        c = []
        if fid:
            f = s[fid]
            c = [{"file_id": fid, "relative_path": f.relative_path, "sha256": f.sha256, "locator": "UNKNOWN",
                  "entity": f.entity, "period": f.period, "match_reason": "r"}]
        return {"item_id": item, "obligation_id": oid, "agent_id": agent, "provider": "fake",
                "model_id_or_unknown": "UNKNOWN", "prompt_version": ar.PROMPT_VERSION, "source_snapshot_id": sid,
                "candidate_files": c, "proposed_verdict": verdict, "confidence_or_uncertain": 0.9,
                "abstain_reason": reason, "warnings": [], "elapsed": "UNKNOWN", "token_usage_or_UNKNOWN": "UNKNOWN"}
    return {"results": [r("S1-O1", "S1", "MATCH", "F001"), r("S2-O1", "S2", "MATCH", "F004"),
                        r("S3-O1", "S3", "MISSING", reason="none")]}


def _script(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / "bin" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def _run(adapter, tmp_path, timeout=10.0):
    wd = tmp_path / "wd"
    wd.mkdir()
    return ad.run_agent(adapter, SNAP, META, OBS, ad.Budget(timeout_s=timeout), workdir=wd), wd


def test_codex_success_validated(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_good_results()), encoding="utf-8")
    # 模拟 codex：读 stdin（若 stdin 未关闭会挂起 → 由 /dev/null 保证立即 EOF），写 -o out.json
    body = (f'cat >/dev/null\ncp "{good}" out.json\n'
            'echo \'{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":3}}\'\n')
    rec, wd = _run(ad.CodexAdapter(_script(tmp_path, "codex", body)), tmp_path)
    assert rec["adapter"]["status"] == "OK"
    assert rec["adapter"]["token_usage_or_UNKNOWN"] == {"input_tokens": 5, "output_tokens": 3}
    assert rec["validation"]["mode"] == "AGENT_SUGGESTION" and len(rec["validation"]["accepted"]) == 3
    assert (wd / "events.jsonl").exists() and (wd / "run_record.json").exists()
    assert "-s" in rec["adapter"]["argv_summary"] and "read-only" in rec["adapter"]["argv_summary"]


def test_workdir_is_isolated(tmp_path):
    pkt = ar.build_task_packet(SNAP, META, OBS)
    wd = ad.prepare_workdir(pkt, base=tmp_path)
    assert sorted(p.name for p in wd.iterdir()) == ["packet.json", "schema.json"]


def test_timeout_kills_process_group_and_degrades(tmp_path):
    marker = tmp_path / "child_alive"
    body = f'(sleep 30; touch "{marker}") &\nsleep 30\n'
    t0 = time.monotonic()
    rec, _ = _run(ad.CodexAdapter(_script(tmp_path, "codex", body)), tmp_path, timeout=1.0)
    assert time.monotonic() - t0 < 10
    assert rec["adapter"]["status"] == "TIMEOUT"
    assert rec["validation"]["mode"] == "RULE_ONLY"
    assert rec["validation"]["degrade_reason"].startswith("AGENT_CALL_FAILED:TIMEOUT")
    time.sleep(0.5)
    assert not marker.exists()  # 子进程随进程组一起被杀


def test_nonzero_exit_degrades(tmp_path):
    rec, _ = _run(ad.CodexAdapter(_script(tmp_path, "codex", 'echo quota exceeded >&2\nexit 3\n')), tmp_path)
    assert rec["adapter"]["status"] == "CALL_FAILED" and rec["adapter"]["exit_code"] == 3
    assert "quota exceeded" in rec["adapter"]["reason"]
    assert rec["validation"]["mode"] == "RULE_ONLY"


def test_codex_garbage_output_degrades(tmp_path):
    rec, _ = _run(ad.CodexAdapter(_script(tmp_path, "codex", 'echo "not json" > out.json\n')), tmp_path)
    assert rec["adapter"]["status"] == "OK"
    assert rec["validation"]["degrade_reason"].startswith("INVALID_JSON")


def test_missing_binary_is_call_failed_not_crash(tmp_path):
    rec, _ = _run(ad.CodexAdapter(str(tmp_path / "nope")), tmp_path)
    assert rec["adapter"]["status"] == "CALL_FAILED" and rec["adapter"]["exit_code"] == 127
    assert "SPAWN_FAILED" in rec["adapter"]["reason"]
    assert rec["validation"]["mode"] == "RULE_ONLY"


def test_minimax_pi_parses_assistant_message(tmp_path):
    txt = json.dumps(_good_results("pi"))
    ev_user = {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "q"}]}}
    ev_upd = {"type": "message_update"}
    ev_end = {"type": "message_end", "message": {"role": "assistant", "model": "MiniMax-Fake",
              "usage": {"totalTokens": 9}, "content": [{"type": "thinking"}, {"type": "text", "text": txt}]}}
    lines = tmp_path / "ev.jsonl"
    lines.write_text("\n".join(json.dumps(e) for e in (ev_user, ev_upd, ev_end)), encoding="utf-8")
    rec, wd = _run(ad.MiniMaxPiAdapter(_script(tmp_path, "pi", f'cat >/dev/null\ncat "{lines}"\n')), tmp_path)
    a = rec["adapter"]
    assert a["role"] == "AUX" and a["model_id_or_unknown"] == "MiniMax-Fake"
    assert a["token_usage_or_UNKNOWN"] == {"totalTokens": 9}
    assert rec["validation"]["mode"] == "AGENT_SUGGESTION"
    assert "message_update" not in (wd / "events.compact.jsonl").read_text("utf-8")
    assert "--no-tools" in a["argv_summary"]


def test_manual_exchange_pending_then_complete(tmp_path):
    rec, wd = _run(ad.ManualExchangeAdapter(), tmp_path)
    assert rec["adapter"]["status"] == "PENDING_MANUAL"
    assert rec["validation"]["mode"] == "RULE_ONLY"
    assert (wd / "PROMPT.txt").exists()
    (wd / "reply.json").write_text(json.dumps(_good_results("manual")), encoding="utf-8")
    rec2 = ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, workdir=wd)
    assert rec2["adapter"]["status"] == "OK" and rec2["validation"]["mode"] == "AGENT_SUGGESTION"


def test_manual_reply_with_fabricated_file_rejected(tmp_path):
    rec, wd = _run(ad.ManualExchangeAdapter(), tmp_path)
    bad = _good_results("manual")
    bad["results"][0]["candidate_files"][0]["relative_path"] = "/etc/passwd"
    (wd / "reply.json").write_text(json.dumps(bad), encoding="utf-8")
    rec2 = ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, workdir=wd)
    assert "CANDIDATE_0_PATH_MISMATCH" in rec2["validation"]["rejected"][0]["errors"]


def test_deepseek_harness_is_blocked_stub_without_any_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not spawn")
    monkeypatch.setattr(ad.subprocess, "Popen", boom)
    rec, _ = _run(ad.DeepSeekHarnessAdapter(), tmp_path)
    assert rec["adapter"]["status"] == "UNAVAILABLE"
    assert rec["adapter"]["role"] == "EXAMINEE_3" and "BLOCKED" in rec["adapter"]["reason"]
    assert rec["validation"]["mode"] == "RULE_ONLY"


def test_budget_rejects_zero_calls():
    with pytest.raises(ValueError):
        ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, ad.Budget(max_calls=0))


def test_kernel_has_no_vendor_names():
    src = Path(ar.__file__).read_text("utf-8").lower()
    for v in ("codex", "minimax", "deepseek", "openai", "subprocess"):
        assert v not in src


def test_adapters_do_not_import_model_clients_or_dd_llm_client():
    src = Path(ad.__file__).read_text("utf-8")
    for bad in ("dd_llm_client", "import openai", "import httpx", "import requests", "import anthropic"):
        assert bad not in src


def test_relative_workdir_is_resolved_to_absolute(tmp_path, monkeypatch):
    """WP03 Mac 实测回归：相对 --workdir 让 codex -C 被二次拼接 → exit 1。"""
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_good_results()), encoding="utf-8")
    # 假 codex：校验 -C 参数（第 6 个）是存在的目录，再写 out.json
    body = f'[ -d "$5" ] || {{ echo "No such file or directory" >&2; exit 1; }}\ncp "{good}" "$5/out.json"\n'
    exe = _script(tmp_path, "codex", body)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs" / "codex").mkdir(parents=True)
    rec = ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS, ad.Budget(timeout_s=10), workdir=Path("runs/codex"))
    c_arg = rec["adapter"]["argv_summary"][rec["adapter"]["argv_summary"].index("-C") + 1]
    assert Path(c_arg).is_absolute()
    assert rec["adapter"]["status"] == "OK" and rec["validation"]["mode"] == "AGENT_SUGGESTION"
