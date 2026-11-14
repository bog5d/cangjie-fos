"""模型身份核实与「模型参与证明」（DD-V1 施工令 V3.0 · P2-1 / 7.1）。

★ ★ 三条纪律（缺一条这套机制就是装饰）：

1. **不猜**。模型身份只能来自 **Agent 自己的可信元数据**（它自己的事件流／它自己的配置树／
   它自己的执行记录）。拿不到就是 ``UNKNOWN``，**绝不**用「这个 Agent 一般用哪个模型」去填。
2. **来源必带**。每个身份都带 ``source``（从哪来的）；没有来源的身份**不采信**
   ⇒ 下游看到 ``source=UNKNOWN`` 即可判定「未核实」。
3. **必须绑定本次考试**。身份不是「这个 Agent 平时用什么」，而是「**这一次**跑这次考试时，
   用的是哪个模型」⇒ 必须能对上：工作目录 / 快照 ID / 运行记录 / 代码版本。

★ 为什么单独成模块（而不是塞进 adapter）：**身份判定是「证据问题」，不是「调用问题」**。
调用成功只说明「跑通了」，不说明「跑的是哪个模型」——把两者混在一起，
就会退回「``participated=true`` 一个布尔值说了算」的老漏洞。

★ 显式区分三件事（上一轮 8 轮独立复核反复点名的口径分叉）：

- ``participated``   ＝ 「这次真的跑出了回执」（**回执口径**）
- ``model_id``       ＝ 「跑的是哪个模型」（**身份口径**）
- ``model_verified`` ＝ 「身份**核实**过吗」（**来源口径**）

⇒ ``participated=true`` **不等于** ``model_verified=true``：
适配器自己说「我参与」可以是真的，但「我用的什么模型」仍可能 UNKNOWN。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 身份来源（source）────────────────────────────────────────────────────────
SOURCE_UNKNOWN = "UNKNOWN"
SOURCE_DSH_PROFILE = "DSH_PROFILE_CONFIG"          # dsh 自己的配置树（--dump-config）
SOURCE_AGENT_EVENT = "AGENT_EVENT"                  # Agent 自己吐的事件流里的 model 字段
SOURCE_CODEX_EXEC_RECORD = "CODEX_EXECUTION_RECORD"  # codex 自己的执行记录（rollout）

#: 身份**核实**过（来源可信 ＋ 绑定到本次考试）
VERIFIED = "VERIFIED"
#: 身份没核实出来（**不算错**，但也不许当成「已核实」用）
UNVERIFIED = "UNVERIFIED"

#: 模型身份字段的缺省值（**不是**「空」，是显式的 UNKNOWN ⇒ 防止下游把它当空串再当「有」）
MODEL_UNKNOWN = "UNKNOWN"
PROVIDER_UNKNOWN = "UNKNOWN"

#: 已知的**框架**（CLI 程序本身）与**服务商**（模型供应商）是两回事。
#: ★ 历史上把「pi 框架」与「MiniMax 服务商」混称 ⇒ 这里强制分开记。
FRAMEWORKS = {
    "codex-cli": "codex-cli",          # OpenAI Codex runtime
    "pi": "pi",                        # @earendil-works/pi-coding-agent（第三方框架）
    "deepseek-harness": "dsh",         # DeepSeek 官方 harness
    "manual-exchange": "operator",
    "prebaked-result": "operator-prebaked",
}


@dataclass(frozen=True)
class ModelIdentity:
    """一次调用的模型身份（**带来源**）。

    ★ ``verified`` 为 False 时，**任何门禁都不得**用它当「模型身份已核实」。
    """

    model_id: str = MODEL_UNKNOWN
    provider: str = PROVIDER_UNKNOWN
    source: str = SOURCE_UNKNOWN
    verified: bool = False
    #: 绑定到本次调用的证据（快照 id / 工作目录 / 执行记录路径 …）
    binding: dict[str, Any] = field(default_factory=dict)
    #: 为什么是 UNKNOWN（**留痕，不静默**）
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "source": self.source,
            "verified": bool(self.verified),
            "binding": dict(self.binding),
            "note": self.note,
        }

    @classmethod
    def unknown(cls, note: str, *, source: str = SOURCE_UNKNOWN,
                binding: dict[str, Any] | None = None) -> "ModelIdentity":
        return cls(MODEL_UNKNOWN, PROVIDER_UNKNOWN, source, False,
                   dict(binding or {}), note)


# ═══════════════════════════════════════════════════════════════════════════
# 一、dsh —— 身份来自 **它自己的配置树**
# ═══════════════════════════════════════════════════════════════════════════

_DSH_MODEL_ID = "agent-default-model"


def parse_dsh_profile_config(dump_text: str) -> dict[str, Any]:
    """从 ``dsh --profile <p> --dump-config`` 的输出里取 ``agent-default-model``。

    ★ **刻意不用 YAML 依赖**：dsh 的 dump 是一段稳定的列表结构
    （``- id: …`` / ``config:`` / 两空格缩进的 ``key: value``），
    行解析足够，**不给项目加新依赖**（SCP v3.8 §2：KISS / 显式优于隐式）。

    返回 ``{"provider": str, "model": str}``；取不到就是空 dict。
    """
    lines = str(dump_text or "").splitlines()
    out: dict[str, Any] = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r"^\s*-\s+id:\s*(\S+)\s*$", line)
        if not m or m.group(1) != _DSH_MODEL_ID:
            i += 1
            continue
        # 进入该 entry 的 config 段，直到下一个同级 `- id:`
        i += 1
        while i < n:
            ln = lines[i]
            if re.match(r"^\s*-\s+id:", ln):
                break
            kv = re.match(r"^\s{4,}([A-Za-z0-9_]+):\s*(.*?)\s*$", ln)
            if kv:
                out[kv.group(1)] = kv.group(2).strip().strip("'\"")
            i += 1
        break
    return out


def resolve_dsh_identity(profile: str = "headless", *, binary: str = "dsh",
                         timeout_s: float = 30.0,
                         expected_cwd: str | None = None) -> ModelIdentity:
    """核实 dsh 这次会用什么模型。

    来源：**dsh 自己的配置树**（``--dump-config`` 里 ``agent-default-model`` 的
    ``provider`` / ``model``）⇒ 这是 harness 的**官方**自述，不是我们猜的。
    """
    try:
        # ★★ MINOR-3 修复（独立 Reviewer 第 3 轮）：此前**不传 cwd**，
        #   而 binding["config_cwd"] 只是把 expected_cwd **原样写进去**（装饰性的），
        #   ⇒ 身份证明的是「profile `headless` 的默认模型」，**没有**指向本次调用所在目录。
        #   ⇒ 现在**在 expected_cwd 里**取配置（profile 的配置是**按目录解析**的）
        #   ⇒ binding 里的 config_cwd 是**这次真的取配置的目录**（不是抄来的）。
        proc = subprocess.run([binary, "--profile", profile, "--dump-config"],
                              capture_output=True, text=True, timeout=timeout_s,
                              cwd=expected_cwd or None)
    except (OSError, subprocess.SubprocessError) as exc:
        return ModelIdentity.unknown(f"DSH_DUMP_CONFIG_FAILED:{type(exc).__name__}")
    if proc.returncode != 0:
        return ModelIdentity.unknown(f"DSH_DUMP_CONFIG_EXIT_{proc.returncode}")
    cfg = parse_dsh_profile_config(proc.stdout)
    model = str(cfg.get("model") or "").strip()
    provider = str(cfg.get("provider") or "").strip()
    if not model:
        return ModelIdentity.unknown(
            "DSH_PROFILE_WITHOUT_AGENT_DEFAULT_MODEL（未找到 agent-default-model 段）",
            binding={"profile": profile})
    binding: dict[str, Any] = {"profile": profile, "config_key": _DSH_MODEL_ID}
    if expected_cwd:
        binding["config_cwd"] = str(expected_cwd)
        binding["config_cwd_source"] = "process_cwd_of_dump（★ 本次真的在**这个目录**里取的配置）"
        binding["binding_strength"] = "profile-config-resolved-at-cwd"
    return ModelIdentity(model, provider or PROVIDER_UNKNOWN, SOURCE_DSH_PROFILE,
                         True, binding,
                         "★ 来源：dsh 自己的配置树（--dump-config，**在该 profile 的解析目录**里取得）。"
                         "★ **能证明**：该 profile 在该目录下的**默认模型**是谁。"
                         "★ **不能证明**：本次请求没有被打到别的模型/回退 —— "
                         "dsh 没有提供逐请求的模型回执 ⇒ 这是它官方元数据能给出的**最强**证明"
                         "（对比 codex：执行记录里的 cwd 不符会 fail-closed 记 UNKNOWN）。")


# ═══════════════════════════════════════════════════════════════════════════
# 二、pi —— 身份来自 **它自己的事件流**
# ═══════════════════════════════════════════════════════════════════════════

def resolve_pi_identity(events_text: str) -> ModelIdentity:
    """从 pi 的 JSON 事件流里取模型身份。

    pi 的 ``message_end`` 事件自带 ``message.model`` 与 ``message.provider``
    ⇒ 这是 **Agent 自己** 报的，不是我们从「pi 一般用哪个模型」推的。
    """
    model = provider = ""
    for line in str(events_text or "").splitlines():
        line = line.strip()
        if not line or '"message_end"' not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(ev.get("type") or "") != "message_end":
            continue
        msg = ev.get("message") or {}
        model = str(msg.get("model") or model)
        provider = str(msg.get("provider") or provider)
    if not model:
        return ModelIdentity.unknown("PI_EVENTS_WITHOUT_MODEL_FIELD")
    return ModelIdentity(model, provider or PROVIDER_UNKNOWN, SOURCE_AGENT_EVENT, True,
                         {"event": "message_end"}, "★ 来源：pi 自己的 message_end 事件")


# ═══════════════════════════════════════════════════════════════════════════
# 三、codex —— 身份来自 **它自己的执行记录**
# ═══════════════════════════════════════════════════════════════════════════

def _codex_sessions_root(codex_home: str | Path | None = None) -> Path:
    home = Path(codex_home) if codex_home else Path(os.path.expanduser("~/.codex"))
    return home / "sessions"


def find_codex_rollout(thread_id: str, *, codex_home: str | Path | None = None,
                       sessions_root: Path | None = None) -> Path | None:
    """按 thread_id 找 codex 自己的执行记录（rollout jsonl）。

    ★ codex 的 rollout 文件名形如 ``rollout-<ts>-<thread_id>.jsonl``，
    而 ``thread_id`` 来自 ``codex exec --json`` 的 ``thread.started`` 事件
    ⇒ **同一次调用**两边对得上 ⇒ 身份可绑定到这次调用。
    """
    tid = str(thread_id or "").strip()
    if not tid:
        return None
    root = sessions_root or _codex_sessions_root(codex_home)
    if not root.is_dir():
        return None
    for p in root.rglob(f"rollout-*-{tid}.jsonl"):
        return p
    return None


def resolve_codex_identity(thread_id: str, *, expected_cwd: str | None = None,
                            codex_home: str | Path | None = None,
                            sessions_root: Path | None = None) -> ModelIdentity:
    """核实 codex 这次用的是哪个模型。

    来源：**codex 自己的执行记录**（rollout）里的 ``turn_context.payload.model``
    与 ``session_meta.payload.model_provider``。

    ★ **必须绑定**：``turn_context.payload.cwd`` 必须等于本次调用的工作目录，
    否则这份记录**可能属于别的运行** ⇒ 记 UNKNOWN（宁可不知道，也不要认错）。
    """
    path = find_codex_rollout(thread_id, codex_home=codex_home, sessions_root=sessions_root)
    if path is None:
        return ModelIdentity.unknown(
            "CODEX_EXECUTION_RECORD_NOT_FOUND（没落盘：codex exec 用了 --ephemeral，"
            "或会话存储不在预期位置）", binding={"thread_id": thread_id})
    model = provider = ""
    rollout_cwd = ""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pl = ev.get("payload") or {}
                if ev.get("type") == "session_meta":
                    provider = str(pl.get("model_provider") or provider)
                if ev.get("type") == "turn_context":
                    model = str(pl.get("model") or model)
                    rollout_cwd = str(pl.get("cwd") or rollout_cwd)
    except OSError as exc:
        return ModelIdentity.unknown(f"CODEX_EXECUTION_RECORD_UNREADABLE:{type(exc).__name__}")
    if not model:
        return ModelIdentity.unknown("CODEX_EXECUTION_RECORD_WITHOUT_MODEL",
                                     binding={"rollout": str(path)})
    binding: dict[str, Any] = {"thread_id": thread_id, "rollout": str(path),
                                "rollout_cwd": rollout_cwd}
    if expected_cwd:
        exp = str(Path(expected_cwd).resolve())
        got = str(Path(rollout_cwd).resolve()) if rollout_cwd else ""
        binding["expected_cwd"] = exp
        if got != exp:
            # ★ 记录在，但**不是这次**的 ⇒ 不采信（fail-closed）
            return ModelIdentity.unknown(
                f"CODEX_EXECUTION_RECORD_CWD_MISMATCH(record={got or 'UNKNOWN'} != exam={exp})",
                source=SOURCE_CODEX_EXEC_RECORD, binding=binding)
    return ModelIdentity(model, provider or PROVIDER_UNKNOWN, SOURCE_CODEX_EXEC_RECORD,
                         True, binding, "★ 来源：codex 自己的执行记录（rollout turn_context）")


# ═══════════════════════════════════════════════════════════════════════════
# 四、统一的「模型参与证明」（7.1 列的 6 项）
# ═══════════════════════════════════════════════════════════════════════════

#: 6 项必查（施工令 7.1）——键名即检查项，值为 True/False
PARTICIPATION_CHECKS = (
    "agent_started",          # 指定 Agent 确实启动
    "call_happened",          # 调用真实发生
    "result_parseable",       # 返回结果可解析
    "bound_to_exam",          # 结果对应当前考试
    "model_identity_verified",  # 模型身份可核实
    "evidence_bound_to_code",   # 证据与当前代码版本关联
)


def build_participation_evidence(*, adapter_result: dict[str, Any] | None,
                                  validation: dict[str, Any] | None,
                                  identity: ModelIdentity,
                                  expected_snapshot_id: str | None = None,
                                  code_version: str | None = None,
                                  run_id: str | None = None) -> dict[str, Any]:
    """产出**模型参与证明**块（机读）。

    ★ 六项**逐项**给结论，**不**塌缩成一个 ``participated`` 布尔值
    ⇒ 下游（门禁 G8）能看清「到底哪一项没过」，而不是只看到一句 false。
    """
    a = dict(adapter_result or {})
    v = dict(validation or {})
    status = str(a.get("status") or "")
    raw = str(a.get("raw_text") or "")
    exit_code = a.get("exit_code")

    agent_started = status == "OK" and exit_code is not None
    call_happened = agent_started and bool(raw)
    # 结果可解析：校验器认了至少一条结果（accepted > 0）才算「可解析」
    accepted = v.get("accepted")
    if not isinstance(accepted, int):
        accepted = len(v.get("accepted_results") or []) or len(v.get("results") or [])
    result_parseable = bool(call_happened) and int(accepted or 0) > 0

    snap = str(v.get("source_snapshot_id") or a.get("source_snapshot_id") or "")
    bound_to_exam = bool(expected_snapshot_id) and snap == str(expected_snapshot_id)
    if not expected_snapshot_id:
        # 没有期望值时**不**假装绑定成功
        bound_to_exam = False

    model_verified = bool(identity.verified) and identity.model_id != MODEL_UNKNOWN

    checks = {
        "agent_started": bool(agent_started),
        "call_happened": bool(call_happened),
        "result_parseable": bool(result_parseable),
        "bound_to_exam": bool(bound_to_exam),
        "model_identity_verified": bool(model_verified),
        "evidence_bound_to_code": bool(code_version),
    }
    all_pass = all(checks.values())
    return {
        "checks": checks,
        "checks_passed": sum(1 for v_ in checks.values() if v_),
        "checks_total": len(checks),
        "participated": bool(call_happened and result_parseable),
        "model_identity": identity.to_dict(),
        "run_id": run_id or "",
        "snapshot_id": snap,
        "code_version": code_version or "",
        "note": ("★ 六项**逐项**判定；`participated` 只表示「跑出了可解析的回执」，"
                 "**不等于**模型身份已核实（看 `model_identity.verified`）。"),
    }
