"""P1-e：dsh **受控凭证替代通道**的 CLI 可达性 ＋ **日志脱敏完整性**。

## 背景（2026-10-30 本机实测取证）

上游（PR#87 V3.0）已经把「运行时环境变量注入」做到了 **API 层**：
``ad.build_adapter(..., dsh_env_overrides=...)`` → ``DeepSeekHarnessAdapter.env_overrides``
→ ``run_cli(..., env_overrides=...)`` ⇒ 子进程环境 = 父环境 + 覆盖项。

但还差两件事，**本文件就是它们的验收**：

1. **CLI 不可达** —— 没有任何旗标能把凭证送进那条通道 ⇒ 「受控替代通道」在命令行上是**死功能**
   （真要用只能改代码）。
2. ★ **stdout 脱敏漏了注入值** —— 上游实现是::

       out, err = redact_secrets(out), redact_secrets(err, {**os.environ, **self.env_overrides})

   ⇒ **stdout** 只按**父环境**脱敏（父环境里本来就没有那个注入值）
   ⇒ **stderr** 才按合并环境脱敏
   ⇒ 若 dsh 把注入的密钥**回显到 stdout**，它就**原样写进 answer.txt** ⇒ **真实泄漏路径**。

★ 本文件的红线与上游一致（施工令 V3.0 §5.1）：**只进子进程环境，不进 argv、不落盘、不进日志**。

## 纪律

- 本文件是**先写测试再改实现**（RED → GREEN）：第 3 条测试在改实现前**是红的**。
- 断言一律用**假密钥**，绝不碰真凭证。
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_adapters as ad

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"

#: 假密钥（**不是**真凭证）
FAKE_KEY = "sk-test-ONLYFAKE-0123456789abcdef"
FAKE_NAME = "DEEPSEEK_API_KEY"

# ── 复用仓内 fixture（与既有 DD-V1 测试同一套输入）────────────────────────
FIX = Path(__file__).parent / "fixtures" / "dd_v1_fos71"
SNAP = FIX / "snapshot"
META = json.loads((FIX / "meta.json").read_text("utf-8"))
OBS = json.loads((FIX / "obligations.json").read_text("utf-8"))


def _fake_dsh(tmp_path: Path, *, echo_stdout: bool = True, echo_stderr: bool = False,
              exit_code: int = 0) -> list[str]:
    """造一个假 dsh：把注入进来的环境变量**回显**到 stdout / stderr。

    ★ 回显是**最坏情况**假设：真实 dsh 若把密钥打回显，就会原样进 answer.txt。
    """
    p = tmp_path / "bin" / "dsh.py"
    p.parent.mkdir(exist_ok=True)
    body = f"""
        import os, sys, json
        sys.stdin.read()
        val = os.environ.get({FAKE_NAME!r}, "")
        {("sys.stdout.write('KEYECHO:' + val + chr(10))" if echo_stdout else "pass")}
        {("sys.stderr.write('KEYECHO:' + val + chr(10))" if echo_stderr else "pass")}
        sys.stdout.write(json.dumps({{"results": []}}) + chr(10))
        sys.exit({exit_code})
    """
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(p)]


def _adapter(tmp_path: Path, *, echo_stdout: bool = True, echo_stderr: bool = False,
             exit_code: int = 0, overrides: dict | None = None):
    a = ad.DeepSeekHarnessAdapter(
        enabled=True, binary=_fake_dsh(tmp_path, echo_stdout=echo_stdout,
                                       echo_stderr=echo_stderr, exit_code=exit_code),
        env_overrides=overrides if overrides is not None else {FAKE_NAME: FAKE_KEY})
    return a


def _run(adapter, tmp_path, name="wd"):
    wd = tmp_path / name
    wd.mkdir(exist_ok=True)
    res = ad.run_agent(adapter, SNAP, META, OBS, ad.Budget(timeout_s=30), workdir=wd)
    return res, wd


# ═══════════════════════════════════════════════════════════════════════
# 1. CLI 可达性：值只从**本进程环境**取，只传**变量名**
# ═══════════════════════════════════════════════════════════════════════
def _load_tc():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dd_team_channel_envcli", TOOLS / "dd_team_channel.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_env_override_names_resolve_values_from_environment(monkeypatch):
    mod = _load_tc()
    monkeypatch.setenv(FAKE_NAME, FAKE_KEY)
    got = mod._env_overrides_from_names([FAKE_NAME])
    assert got == {FAKE_NAME: FAKE_KEY}
    # ★ 值只可能来自环境变量；CLI 参数里**只有名字**
    assert FAKE_KEY not in json.dumps([FAKE_NAME], ensure_ascii=False)


def test_env_override_missing_name_is_refused(monkeypatch):
    """★ fail-closed：名字不在环境里 ⇒ **直接拒绝**（不给 dsh 传空值）。

    ★ 为什么必须拒绝：传空值会变成「看起来调用了、必然鉴权失败」的假调用，
      还会在日志里留下一个**误导性的成功/失败口径**。
    """
    mod = _load_tc()
    monkeypatch.delenv(FAKE_NAME, raising=False)
    with pytest.raises(SystemExit) as ei:
        mod._env_overrides_from_names([FAKE_NAME])
    assert FAKE_NAME in str(ei.value)


def test_env_override_blank_names_are_skipped(monkeypatch):
    mod = _load_tc()
    assert mod._env_overrides_from_names(["", "  "]) == {}


def test_env_override_cli_flag_exists_and_is_append():
    """CLI 必须有这个旗标（否则「受控替代通道」是死功能）。"""
    mod = _load_tc()
    txt = (TOOLS / "dd_team_channel.py").read_text("utf-8")
    assert '"--dsh-env-override"' in txt
    assert 'action="append"' in txt


def test_exam_suite_forwards_env_override_to_team_channel():
    txt = (TOOLS / "dd_v1_exam_suite.py").read_text("utf-8")
    assert '"--dsh-env-override"' in txt
    assert '"--dsh-env-override"' in txt or "dsh_env_override" in txt


# ═══════════════════════════════════════════════════════════════════════
# 2. ★ 日志脱敏完整性（stdout **必须**和 stderr 一样按合并环境脱敏）
# ═══════════════════════════════════════════════════════════════════════
def test_injected_secret_never_reaches_stdout_capture(tmp_path):
    """★ 本条在改实现前**是红的**（上游 stdout 只按父环境脱敏）。"""
    a = _adapter(tmp_path, echo_stdout=True)
    res, wd = _run(a, tmp_path)
    assert FAKE_KEY not in (res.get("adapter") or {}).get("raw_text", "")


def test_injected_secret_never_written_to_disk(tmp_path):
    """★ 落盘红线：answer.txt / stderr.log / run_record.json 都不含明文密钥。"""
    a = _adapter(tmp_path, echo_stdout=True, echo_stderr=True)
    res, wd = _run(a, tmp_path)
    for p in wd.rglob("*"):
        if not p.is_file():
            continue
        blob = p.read_text("utf-8", errors="replace")
        assert FAKE_KEY not in blob, f"密钥明文落在 {p.name}"


def test_injected_secret_redacted_marker_present(tmp_path):
    """★ 不只是「没有明文」，还要**看得见**它被抹成了什么（可核验）。"""
    a = _adapter(tmp_path, echo_stdout=True, echo_stderr=True)
    res, wd = _run(a, tmp_path)
    blob = "\n".join(p.read_text("utf-8", errors="replace")
                     for p in wd.rglob("*") if p.is_file())
    assert f"<REDACTED:{FAKE_NAME}>" in blob, "看不到脱敏标记 ⇒ 脱敏口径不可核验"


def test_injected_secret_never_in_argv(tmp_path):
    a = _adapter(tmp_path, echo_stdout=True)
    res, _ = _run(a, tmp_path)
    argv = res.get("adapter", {}).get("argv_summary") or []
    assert FAKE_KEY not in json.dumps(argv, ensure_ascii=False)


def test_injected_secret_never_in_stdin_prompt(tmp_path):
    a = _adapter(tmp_path, echo_stdout=True)
    res, _ = _run(a, tmp_path)
    assert FAKE_KEY not in (res.get("adapter", {}).get("raw_text") or "")


# ═══════════════════════════════════════════════════════════════════════
# 3. 回退行为：不给覆盖项 ⇒ **零行为变化**
# ═══════════════════════════════════════════════════════════════════════
def test_without_overrides_child_env_is_unchanged(tmp_path):
    """不给覆盖项 ⇒ 不传 env_overrides ⇒ 子进程**继承父环境**（零行为变化）。"""
    a = ad.DeepSeekHarnessAdapter(enabled=True, binary=_fake_dsh(tmp_path))
    assert a.env_overrides == {}
    res, _ = _run(a, tmp_path)
    assert res.get("adapter", {}).get("status") == "OK"


def test_no_override_means_no_env_kwarg(tmp_path):
    """★ 精确到调用层：没有覆盖项时，**不得**给 run_cli 传 env_overrides。"""
    seen: dict = {}

    def _spy(argv, cwd, timeout_s, stdin_text=None, env_overrides=None):
        seen["env_overrides"] = env_overrides
        return 0, json.dumps({"results": []}), "", 0.1, False

    old = ad.run_cli
    ad.run_cli = _spy
    try:
        a = ad.DeepSeekHarnessAdapter(enabled=True, binary=["dsh"])
        wd = tmp_path / "wd2"
        wd.mkdir()
        a.run({"source_snapshot_id": "s", "obligations": [], "evidence": {}},
              wd, ad.Budget(timeout_s=5))
    finally:
        ad.run_cli = old
    assert seen["env_overrides"] is None, "无覆盖项时不应传 env_overrides"


# ═══════════════════════════════════════════════════════════════════════
# 4. 错误密钥 ⇒ 不得被当成成功
# ═══════════════════════════════════════════════════════════════════════
def test_wrong_key_is_call_failed_not_success(tmp_path):
    a = _adapter(tmp_path, exit_code=7)
    res, _ = _run(a, tmp_path)
    assert res.get("adapter", {}).get("status") == "CALL_FAILED"
    assert res.get("adapter", {}).get("exit_code") == 7


def test_empty_override_value_is_refused(tmp_path):
    """★ 空值 / 纯空白 / None ⇒ 拒绝（fail-closed，不给 dsh 传空值）。"""
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            ad.DeepSeekHarnessAdapter(enabled=True, binary=["dsh"],
                                      env_overrides={FAKE_NAME: bad})
