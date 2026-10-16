"""cangjie-fos#71 WP03：Agent Adapter（用 Python 写的假 CLI，不调用真实模型、不联网）。

假 CLI 以 ``[sys.executable, fake.py]`` 形式传给 Adapter，Windows/macOS/Linux 都能跑（复核 N5）。
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_adapters as ad
from cangjie_fos.services import dd_v1_agent_result_service as ar

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71"
SNAP = FX / "snapshot"
META = json.loads((FX / "meta.json").read_text("utf-8"))
OBS = json.loads((FX / "obligations.json").read_text("utf-8"))


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


def _fake(tmp_path: Path, name: str, body: str) -> list[str]:
    p = tmp_path / "bin" / f"{name}.py"
    p.parent.mkdir(exist_ok=True)
    p.write_text("import sys, os, json, time, subprocess\n" + textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(p)]


def _wd(tmp_path, name="wd"):
    d = tmp_path / name
    d.mkdir()
    return d


def _run(adapter, tmp_path, timeout=20.0, **budget):
    wd = _wd(tmp_path)
    return ad.run_agent(adapter, SNAP, META, OBS, ad.Budget(timeout_s=timeout, **budget), workdir=wd), wd


def _codex_writing(tmp_path, payload: dict | str, extra=""):
    src = tmp_path / "payload.json"
    src.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return _fake(tmp_path, "codex", f"""
        sys.stdin.read()  # stdin 未关闭会挂起；/dev/null 保证立即 EOF
        open("out.json", "w", encoding="utf-8").write(open({str(src)!r}, encoding="utf-8").read())
        print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 5, "output_tokens": 3}}}}))
        {extra}
    """)


def test_codex_success_validated(tmp_path):
    rec, wd = _run(ad.CodexAdapter(_codex_writing(tmp_path, _good_results())), tmp_path)
    assert rec["adapter"]["status"] == "OK"
    assert rec["adapter"]["token_usage_or_UNKNOWN"] == {"input_tokens": 5, "output_tokens": 3}
    assert rec["validation"]["mode"] == "AGENT_SUGGESTION" and len(rec["validation"]["accepted"]) == 3
    assert (wd / "events.jsonl").exists() and (wd / "run_record.json").exists()
    assert "read-only" in rec["adapter"]["argv_summary"]
    assert rec["calls_used"] == 1


def test_workdir_is_isolated(tmp_path):
    pkt = ar.build_task_packet(SNAP, META, OBS)
    wd = ad.prepare_workdir(pkt, base=tmp_path)
    assert sorted(p.name for p in wd.iterdir()) == ["packet.json", "schema.json"]


def test_timeout_kills_process_tree_and_degrades(tmp_path):
    marker = tmp_path / "child_alive"
    child = f"import time; time.sleep(8); open({str(marker)!r}, 'w').write('x')"
    exe = _fake(tmp_path, "codex", f"""
        subprocess.Popen([sys.executable, "-c", {child!r}])
        time.sleep(30)
    """)
    t0 = time.monotonic()
    rec, _ = _run(ad.CodexAdapter(exe), tmp_path, timeout=2.0)
    assert time.monotonic() - t0 < 15
    assert rec["adapter"]["status"] == "TIMEOUT"
    assert rec["validation"]["degrade_reason"].startswith("AGENT_CALL_FAILED:TIMEOUT")
    time.sleep(9)
    assert not marker.exists()  # 子进程随进程组/进程树一起被杀


def test_nonzero_exit_degrades(tmp_path):
    exe = _fake(tmp_path, "codex", 'sys.stderr.write("quota exceeded\\n"); sys.exit(3)\n')
    rec, _ = _run(ad.CodexAdapter(exe), tmp_path)
    assert rec["adapter"]["status"] == "CALL_FAILED" and rec["adapter"]["exit_code"] == 3
    assert "quota exceeded" in rec["adapter"]["reason"]
    assert rec["validation"]["mode"] == "RULE_ONLY"


def test_codex_garbage_output_degrades(tmp_path):
    rec, _ = _run(ad.CodexAdapter(_codex_writing(tmp_path, "not json")), tmp_path)
    assert rec["adapter"]["status"] == "OK"
    assert rec["validation"]["degrade_reason"].startswith("INVALID_JSON")


def test_missing_binary_is_call_failed_not_crash(tmp_path):
    rec, _ = _run(ad.CodexAdapter(str(tmp_path / "nope")), tmp_path)
    assert rec["adapter"]["status"] == "CALL_FAILED" and rec["adapter"]["exit_code"] == 127
    assert "SPAWN_FAILED" in rec["adapter"]["reason"]


def _pi_events(tmp_path, cost=0):
    txt = json.dumps(_good_results("pi"))
    evs = [{"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "q"}]}},
           {"type": "message_update"},
           {"type": "message_end", "message": {"role": "assistant", "model": "MiniMax-Fake",
            "usage": {"totalTokens": 9, "cost": {"total": cost}},
            "content": [{"type": "thinking"}, {"type": "text", "text": txt}]}}]
    f = tmp_path / "ev.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in evs), encoding="utf-8")
    return _fake(tmp_path, "pi", f'sys.stdin.read(); sys.stdout.write(open({str(f)!r}, encoding="utf-8").read())\n')


def test_minimax_pi_parses_assistant_message(tmp_path):
    rec, wd = _run(ad.MiniMaxPiAdapter(_pi_events(tmp_path)), tmp_path)
    a = rec["adapter"]
    assert a["role"] == "AUX" and a["model_id_or_unknown"] == "MiniMax-Fake"
    assert a["cost_usd_or_UNKNOWN"] == 0
    assert rec["validation"]["mode"] == "AGENT_SUGGESTION"
    assert "message_update" not in (wd / "events.compact.jsonl").read_text("utf-8")
    assert "--no-tools" in a["argv_summary"]


# ---- 复核 N1：人工交换来源 ----

def test_manual_exchange_pending_then_complete_with_provenance(tmp_path):
    rec, wd = _run(ad.ManualExchangeAdapter(), tmp_path)
    assert rec["adapter"]["status"] == "PENDING_MANUAL" and rec["validation"]["mode"] == "RULE_ONLY"
    reply = json.dumps(_good_results("manual"))
    (wd / "reply.json").write_text(reply, encoding="utf-8")
    (wd / "reply.provenance.json").write_text(json.dumps(
        {"reply_source": "copied_from_AUX_minimax-pi_run", "declared_by": "operator-test"}), encoding="utf-8")
    rec2 = ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, workdir=wd)
    prov = rec2["adapter"]["provenance"]
    import hashlib
    assert prov["reply_sha256"] == hashlib.sha256(reply.encode()).hexdigest()
    assert prov["reply_source"] == "copied_from_AUX_minimax-pi_run"
    assert prov["independent_examinee_answer"] is False
    assert rec2["validation"]["mode"] == "AGENT_SUGGESTION"


def test_manual_reply_without_provenance_is_marked_undeclared(tmp_path):
    wd = _wd(tmp_path)
    (wd / "reply.json").write_text(json.dumps(_good_results("manual")), encoding="utf-8")
    rec = ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, workdir=wd)
    assert rec["adapter"]["provenance"]["reply_source"] == "UNDECLARED_OPERATOR_PASTE"
    assert rec["adapter"]["provenance"]["independent_examinee_answer"] is False


def test_manual_reply_with_fabricated_file_rejected(tmp_path):
    wd = _wd(tmp_path)
    bad = _good_results("manual")
    bad["results"][0]["candidate_files"][0]["relative_path"] = "/etc/passwd"
    (wd / "reply.json").write_text(json.dumps(bad), encoding="utf-8")
    rec = ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, workdir=wd)
    assert "CANDIDATE_0_PATH_MISMATCH" in rec["validation"]["rejected"][0]["errors"]


# ---- 复核 N2：非空 workdir ----

def test_nonempty_workdir_rejected_for_cli_adapters(tmp_path):
    wd = _wd(tmp_path)
    (wd / "out.json").write_text(json.dumps(_good_results("stale")), encoding="utf-8")
    exe = _fake(tmp_path, "codex", "pass\n")  # 不写 out.json；若读到残留就会误判成功
    with pytest.raises(ValueError, match="WORKDIR_NOT_EMPTY"):
        ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS, workdir=wd)


def test_codex_never_reads_stale_out_json_even_in_reused_dir(tmp_path):
    wd = _wd(tmp_path)
    (wd / "out.json").write_text(json.dumps(_good_results("stale")), encoding="utf-8")
    exe = _fake(tmp_path, "codex", "pass\n")
    res = ad.CodexAdapter(exe).run({}, wd, ad.Budget(timeout_s=20))
    assert res.raw_text is None  # 运行前已删除残留


def test_manual_workdir_rejects_unexpected_files(tmp_path):
    wd = _wd(tmp_path)
    (wd / "secret.pdf").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="secret.pdf"):
        ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, workdir=wd)


# ---- 复核 N3：max_calls / 费用预算 ----

def _flaky(tmp_path, fail_times: int):
    cnt = tmp_path / "count.txt"
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_good_results()), encoding="utf-8")
    return _fake(tmp_path, "codex", f"""
        p = {str(cnt)!r}
        n = int(open(p).read()) + 1 if os.path.exists(p) else 1
        open(p, "w").write(str(n))
        if n <= {fail_times}:
            sys.exit(2)
        open("out.json", "w", encoding="utf-8").write(open({str(good)!r}, encoding="utf-8").read())
    """), cnt


def test_max_calls_retries_until_success(tmp_path):
    exe, cnt = _flaky(tmp_path, fail_times=2)
    rec, _ = _run(ad.CodexAdapter(exe), tmp_path, max_calls=3)
    assert rec["calls_used"] == 3 and cnt.read_text() == "3"
    assert [a["status"] for a in rec["attempts"]] == ["CALL_FAILED", "CALL_FAILED", "OK"]
    assert rec["validation"]["mode"] == "AGENT_SUGGESTION"


def test_max_calls_stops_and_degrades(tmp_path):
    exe, cnt = _flaky(tmp_path, fail_times=5)
    rec, _ = _run(ad.CodexAdapter(exe), tmp_path, max_calls=2)
    assert rec["calls_used"] == 2 and cnt.read_text() == "2"
    assert rec["validation"]["mode"] == "RULE_ONLY"


def test_non_retryable_status_not_retried(tmp_path):
    rec, _ = _run(ad.DeepSeekHarnessAdapter(), tmp_path, max_calls=5)
    assert rec["calls_used"] == 1


def test_cost_budget_exceeded_discards_output(tmp_path):
    rec, _ = _run(ad.MiniMaxPiAdapter(_pi_events(tmp_path, cost=0.02)), tmp_path)  # 默认 max_cost_usd=0
    assert rec["adapter"]["status"] == "BUDGET_EXCEEDED" and rec["adapter"]["raw_text"] is None
    assert rec["validation"]["mode"] == "RULE_ONLY"


def test_cost_within_budget_ok(tmp_path):
    rec, _ = _run(ad.MiniMaxPiAdapter(_pi_events(tmp_path, cost=0.02)), tmp_path, max_cost_usd=0.05)
    assert rec["adapter"]["status"] == "OK"


@pytest.mark.parametrize("kw", [{"max_calls": 0}, {"max_cost_usd": -1}])
def test_budget_validation(kw):
    with pytest.raises(ValueError):
        ad.run_agent(ad.ManualExchangeAdapter(), SNAP, META, OBS, ad.Budget(**kw))


def test_deepseek_harness_is_blocked_stub_without_any_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not spawn")
    monkeypatch.setattr(ad.subprocess, "Popen", boom)
    rec, _ = _run(ad.DeepSeekHarnessAdapter(), tmp_path)
    assert rec["adapter"]["status"] == "UNAVAILABLE"
    assert rec["adapter"]["role"] == "EXAMINEE_3" and "BLOCKED" in rec["adapter"]["reason"]


def test_relative_workdir_is_resolved_to_absolute(tmp_path, monkeypatch):
    """WP03 Mac 实测回归：相对 --workdir 让 codex -C 被二次拼接 → exit 1。"""
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_good_results()), encoding="utf-8")
    exe = _fake(tmp_path, "codex", f"""
        d = sys.argv[sys.argv.index("-C") + 1]
        if not os.path.isdir(d):
            sys.stderr.write("No such file or directory"); sys.exit(1)
        open(os.path.join(d, "out.json"), "w", encoding="utf-8").write(open({str(good)!r}, encoding="utf-8").read())
    """)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs" / "codex").mkdir(parents=True)
    rec = ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS, ad.Budget(timeout_s=20), workdir=Path("runs/codex"))
    c_arg = rec["adapter"]["argv_summary"][rec["adapter"]["argv_summary"].index("-C") + 1]
    assert Path(c_arg).is_absolute()
    assert rec["adapter"]["status"] == "OK"


def test_kernel_has_no_vendor_names():
    src = Path(ar.__file__).read_text("utf-8").lower()
    for v in ("codex", "minimax", "deepseek", "openai", "subprocess"):
        assert v not in src


def test_adapters_do_not_import_model_clients_or_dd_llm_client():
    src = Path(ad.__file__).read_text("utf-8")
    for bad in ("dd_llm_client", "import openai", "import httpx", "import requests", "import anthropic"):
        assert bad not in src
