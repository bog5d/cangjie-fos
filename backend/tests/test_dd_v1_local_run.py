"""cangjie-fos#71：本地真实材料 + DeepSeek Harness opt-in 运行器（假 dsh、合成材料，零真实模型）。"""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_adapters as ad
from cangjie_fos.services import dd_v1_semantic_retrieval_service as s

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_local_run as lr  # noqa: E402

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71_wp04"
META = json.loads((FX / "meta.json").read_text("utf-8"))
ITEMS = json.loads((FX / "raw_items.json").read_text("utf-8"))


@pytest.fixture()
def material(tmp_path):
    """把合成 fixture 拷到仓库外，模拟「本机真实材料目录」。"""
    root = tmp_path / "material"
    shutil.copytree(FX / "snapshot", root)
    (tmp_path / "meta.json").write_text(json.dumps(META, ensure_ascii=False), "utf-8")
    (tmp_path / "items.json").write_text(json.dumps(ITEMS, ensure_ascii=False), "utf-8")
    return tmp_path


def _good(pkt):
    rs = []
    for o in pkt["obligations"]:
        ev = pkt["evidence"][o["obligation_id"]]
        hint = s.rule_hint(o, ev)
        cands = [{"file_id": e["file_id"], "relative_path": e["relative_path"], "sha256": e["sha256"],
                  "locator": e["locator"], "entity": e["entity"], "period": e["period"],
                  "match_reason": "摘录写明主体年度"} for e in ev if e["file_id"] in hint["files"]]
        rs.append({"item_id": o["item_id"], "obligation_id": o["obligation_id"], "agent_id": "dsh",
                   "provider": "deepseek-harness", "model_id_or_unknown": "UNKNOWN",
                   "prompt_version": pkt["prompt_version"], "source_snapshot_id": pkt["source_snapshot_id"],
                   "candidate_files": cands, "proposed_verdict": hint["verdict"], "confidence_or_uncertain": 0.7,
                   "abstain_reason": None if cands else "无证据", "warnings": [], "elapsed": "UNKNOWN",
                   "token_usage_or_UNKNOWN": "UNKNOWN"})
    return {"results": rs}


def _fake_dsh(tmp_path, root, leak_env=None):
    """假 dsh：从 prompt 里的 PACKET 取包，按规则提示作答，套上 ```json 围栏；可选把环境变量打印到 stderr。"""
    fake = tmp_path / "dsh.py"
    fake.write_text(textwrap.dedent(f"""
        import sys, json, os
        sys.path.insert(0, {str(REPO / 'backend' / 'src')!r}); sys.path.insert(0, {str(Path(__file__).parent)!r})
        from test_dd_v1_local_run import _good
        assert sys.argv[1:3] == ["--profile", "headless"], sys.argv
        prompt = sys.argv[-1]
        pkt = json.loads(prompt.split("=== PACKET ===")[1].split("=== SCHEMA ===")[0])
        {"sys.stderr.write('key=' + os.environ.get(%r, '') + chr(10))" % leak_env if leak_env else "pass"}
        print("好的，结果如下：\\n```json\\n" + json.dumps(_good(pkt), ensure_ascii=False) + "\\n```")
    """), "utf-8")
    cfg = tmp_path / "dsh.json"
    cfg.write_text(json.dumps({"binary": [sys.executable, str(fake)]}), "utf-8")
    return cfg


def _run(material, *extra):
    return lr.main(["run", "--material-root", str(material / "material"), "--meta", str(material / "meta.json"),
                    "--items", str(material / "items.json"), "--out", str(material / "out"), *extra])


def test_dsh_default_is_still_blocked_stub(tmp_path):
    res = ad.DeepSeekHarnessAdapter().run({}, tmp_path, ad.Budget())
    assert res.status == "UNAVAILABLE" and "BLOCKED" in res.reason


def test_real_material_requires_explicit_flag(material, capsys):
    cfg = _fake_dsh(material, material)
    assert _run(material, "--allow-local-dsh", "--dsh-config", str(cfg)) == 3
    assert "allow-real-material" in capsys.readouterr().err


def test_dsh_requires_explicit_flag(material):
    with pytest.raises(SystemExit) as e:
        _run(material, "--allow-real-material")
    assert e.value.code == 3


def test_local_dsh_end_to_end_and_score(material, capsys):
    cfg = _fake_dsh(material, material)
    assert _run(material, "--allow-real-material", "--allow-local-dsh", "--dsh-config", str(cfg)) == 0
    rec = json.loads((material / "out" / "run-all" / "run_record.json").read_text("utf-8"))
    assert rec["adapter"]["role"] == "PRIMARY_LOCAL_DSH" and rec["adapter"]["status"] == "OK"
    assert rec["semantic_validation"]["mode"] == "AGENT_SUGGESTION"
    assert all(r["review_required"] and r["approved"] is False for r in rec["semantic_validation"]["accepted"])
    # Gold：放在材料/运行目录之外
    gold = material / "gold" / "gold.json"
    gold.parent.mkdir()
    gold.write_text(json.dumps([{"obligation_id": "R1-O1", "expected_verdict": "MATCH", "expected_files": ["G001", "G002"]},
                                {"obligation_id": "R4-O1", "expected_verdict": "MISSING", "expected_files": []}]), "utf-8")
    assert lr.main(["score", "--run-dir", str(material / "out"), "--gold", str(gold), "--out",
                    str(material / "score.json"), "--material-root", str(material / "material")]) == 0
    sc = json.loads((material / "score.json").read_text("utf-8"))
    assert sc["status"] == "LOW_CONFIDENCE" and sc["agent"]["correct"] == 2
    exported = (material / "score.json").read_text("utf-8") + (material / "score.csv").read_text("utf-8-sig")
    assert ".txt" not in exported and "合成样例" not in exported  # 回传文件不含路径和正文


def test_per_item_and_resume(material):
    cfg = _fake_dsh(material, material)
    args = ("--allow-real-material", "--allow-local-dsh", "--dsh-config", str(cfg), "--per-item")
    assert _run(material, *args) == 0
    dirs = sorted(p.name for p in (material / "out").iterdir() if p.is_dir())
    assert dirs == ["run-R1", "run-R2", "run-R3", "run-R4"]
    summary = json.loads((material / "out" / "run_summary.json").read_text("utf-8"))
    assert {x["group"] for x in summary} == {"R1", "R2", "R3", "R4"}
    assert _run(material, *args) == 3  # 不加 --resume 拒绝覆盖
    assert _run(material, *args, "--resume") in (0, 2)


def test_secret_is_redacted_from_logs(material, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-very-secret-123456")
    cfg = _fake_dsh(material, material, leak_env="DEEPSEEK_API_KEY")
    _run(material, "--allow-real-material", "--allow-local-dsh", "--dsh-config", str(cfg))
    blob = "".join(p.read_text("utf-8", errors="replace") for p in (material / "out").rglob("*") if p.is_file())
    assert "sk-test-very-secret-123456" not in blob and "<REDACTED:DEEPSEEK_API_KEY>" in blob


def test_dsh_config_rejects_secrets_and_unknown_fields(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"api_key": "x"}), "utf-8")
    with pytest.raises(ValueError, match="SECRETS"):
        ad.load_dsh_config(p)
    p.write_text(json.dumps({"bogus": 1}), "utf-8")
    with pytest.raises(ValueError, match="UNKNOWN"):
        ad.load_dsh_config(p)


def test_gold_inside_material_or_run_dir_refused(material):
    (material / "out").mkdir()
    g = material / "out" / "gold.json"
    g.write_text("[]", "utf-8")
    with pytest.raises(PermissionError, match="GOLD_INSIDE"):
        lr.main(["score", "--run-dir", str(material / "out"), "--gold", str(g), "--out", str(material / "s.json")])


def test_run_has_no_gold_argument():
    with pytest.raises(SystemExit):
        lr.main(["run", "--gold", "x", "--material-root", "a", "--meta", "b", "--items", "c", "--out", "d"])


def test_out_inside_material_refused(material):
    cfg = _fake_dsh(material, material)
    assert lr.main(["run", "--material-root", str(material / "material"), "--meta", str(material / "meta.json"),
                    "--items", str(material / "items.json"), "--out", str(material / "material" / "o"),
                    "--allow-real-material", "--allow-local-dsh", "--dsh-config", str(cfg)]) == 3


def test_network_paths_refused():
    with pytest.raises(s.Blocked):
        s.local_material_snapshot("https://x/y", [], allow_real=True)  # type: ignore[arg-type]


def test_binary_without_text_layer_gives_metadata_only(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF-1.4 \x00\xff binary")
    meta = [{"file_id": "P1", "relative_path": "a.pdf", "entity": "E", "period": "2024", "doc_type": "审计报告",
             "part": "正文", "version_status": "EFFECTIVE"}]
    ev = s.retrieve_minimal_evidence(root, meta, {"entity": "E", "doc_type": "审计报告", "period": "2024"})
    assert ev[0]["untrusted_excerpt"] == s.NO_TEXT and ev[0]["locator"] == "UNKNOWN"


def test_text_path_must_stay_in_text_root(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"x")
    meta = [{"file_id": "P1", "relative_path": "a.pdf", "entity": "E", "period": "2024", "doc_type": "审计报告",
             "text_path": "../secret.txt"}]
    with pytest.raises(PermissionError):
        s.retrieve_minimal_evidence(root, meta, {"entity": "E", "doc_type": "审计报告", "period": "2024"},
                                    text_root=tmp_path / "t")


def test_scaffold_and_split(material, capsys):
    out = material / "meta.draft.json"
    assert lr.main(["scaffold", "--material-root", str(material / "material"), "--out", str(out),
                    "--entity", "示例科技有限公司"]) == 0
    m = json.loads(out.read_text("utf-8"))
    assert len(m) == 8 and all(x["entity"] == "示例科技有限公司" for x in m)
    assert lr.main(["split", "--items", str(material / "items.json"), "--out", str(material / "obs.json")]) == 0
    assert len(json.loads((material / "obs.json").read_text("utf-8"))) == 4


def test_sha_is_cached_by_stat(tmp_path, monkeypatch):
    from cangjie_fos.services import dd_v1_agent_result_service as ar
    f = tmp_path / "big.bin"
    f.write_bytes(b"a" * 100)
    calls = []
    real = ar._sha256_stream
    monkeypatch.setattr(ar, "_sha256_stream", lambda p: calls.append(p) or real(p))
    ar.sha256_file(f); ar.sha256_file(f)
    assert len(calls) == 1
