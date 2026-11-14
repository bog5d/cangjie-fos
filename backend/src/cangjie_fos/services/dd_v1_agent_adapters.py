"""DD-V1 Agent Adapter（cangjie-fos#71 WP03，R2）。

任务包 → 外部 Agent CLI（隔离临时目录、stdin=/dev/null、硬超时、杀掉整个进程组）→ 原始文本
→ ``dd_v1_agent_result_service.validate_agent_output``（确定性硬校验）。

- 供应商名和 CLI 参数**只出现在本模块**；Kernel（agent_result_service）不认识任何供应商。
- Adapter 不写结果、不改规则：输出永远只是 suggestion，必须经过校验器。
- 失败状态显式化：OK / TIMEOUT / CALL_FAILED / UNAVAILABLE / PENDING_MANUAL；
  非 OK 一律以 ``call_error`` 交给校验器降级 RULE_ONLY（R5）。
- DeepSeek Harness：#71 考生3，目前 UNAVAILABLE（dsh 已停用，董事长未裁决 OQ-1）。
  本 Adapter 是**桩**：不发起任何调用，直接返回 UNAVAILABLE/BLOCKED，绝不改走直连 API。
- MiniMax：辅助路径（AUX，scored=false），不是考生。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from cangjie_fos.services import dd_v1_agent_identity as ident
from cangjie_fos.services import dd_v1_agent_result_service as ar

SCHEMA_PATH = Path(ar.__file__).with_name("dd_v1_agent_result.v1.schema.json")

OK, TIMEOUT, CALL_FAILED, UNAVAILABLE, PENDING_MANUAL, BUDGET_EXCEEDED = (
    "OK", "TIMEOUT", "CALL_FAILED", "UNAVAILABLE", "PENDING_MANUAL", "BUDGET_EXCEEDED")
RETRYABLE = (TIMEOUT, CALL_FAILED)
# 人工交换允许在 workdir 里预先存在的文件（复核 N2）；其余 Adapter 要求 workdir 为空
MANUAL_ALLOWED = {"packet.json", "schema.json", "PROMPT.txt", "reply.json", "reply.provenance.json", "run_record.json"}


@dataclass
class AdapterResult:
    adapter_id: str
    vendor: str
    role: str  # EXAMINEE_2 / AUX / MANUAL / EXAMINEE_3
    status: str
    raw_text: str | None = None
    exit_code: int | None = None
    elapsed_s: float | None = None
    model_id_or_unknown: str = "UNKNOWN"
    token_usage_or_UNKNOWN: Any = "UNKNOWN"
    reason: str | None = None
    workdir: str | None = None
    argv_summary: list[str] = field(default_factory=list)
    cost_usd_or_UNKNOWN: Any = "UNKNOWN"
    provenance: dict[str, Any] = field(default_factory=dict)
    # ★★ **框架 ≠ 服务商**（施工令 V3.0 §5.2：不得把 pi 框架与 MiniMax 服务商混为一谈）
    framework: str = ""
    # ★★ **模型身份的来源与核实状态**（施工令 V3.0 §7.1）
    #   `model_id_or_unknown` 是**模型 id**；下面两个字段说明「这个 id 从哪来、核实过没有」。
    #   ★ `model_identity_verified=False` ⇒ **不得**用它通过「模型身份」门禁。
    model_identity_source: str = "UNKNOWN"
    model_identity_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Budget:
    """预算（复核 N3）＋ **分 Agent 超时预算**（施工令 V3.0 §P5）。

    - timeout_s：单次调用硬超时，超时杀进程组。
    - max_calls：最多调用次数（含重试）；只有 TIMEOUT / CALL_FAILED 会重试。
    - max_cost_usd：允许的实际费用上限。默认 0 = 不允许任何付费调用（订阅内 cost=0 或 UNKNOWN 放行，
      但 UNKNOWN 会在 run record 标出）。已知 cost > 上限 → BUDGET_EXCEEDED，丢弃输出并降级。
    - retry_backoff_s：重试之间的退避秒数（0 = 不退避，测试用）。
    - max_total_s：**整场调用**的墙钟上限 ⇒ 杜绝「无限等待」（重试 × 超时也可能变很长）。
    """

    timeout_s: float = 180.0
    max_calls: int = 1
    max_cost_usd: float = 0.0
    require_known_cost: bool = False  # 付费 Adapter 置 True：费用 UNKNOWN 视为超预算
    #: ★ 单次超时是**调用方显式给的**吗？
    #: ★ 默认 **True**（直接 ``Budget(timeout_s=…)`` 构造 ⇒ 调用方明确指定了 ⇒ **不参与**缩放）；
    #:   只有 :func:`budget_for_framework` 走**框架预算表**取默认值时才是 False ⇒ 才参与按规模缩放。
    #:   （操作员显式配置优先；``--agent-timeout`` 亦然。）
    timeout_explicit: bool = True
    retry_backoff_s: float = 2.0
    max_total_s: float = 900.0


# ═══════════════════════════════════════════════════════════════════════════
# 分 Agent 超时预算（施工令 V3.0 §P5：**不许机械地把所有超时统一设成 420 秒**）
# ═══════════════════════════════════════════════════════════════════════════
#
# ★ 数值**来自真实运行数据**（本机 .audit/exam-plane 下的真实调用），不是拍脑袋：
#   deepseek-harness：23.77s / 26.59s / **104.90s**（冷启动那次）⇒ 上限取最慢实测的 ~2.9 倍
#   pi              ：**38.19s**                                     ⇒ ~3.1 倍
#   codex-cli       ：**25.22s**（热）／冷启动曾达 ~118s              ⇒ ~2.5 倍
# ⇒ 每个 Agent 的超时**不同**；统一 420s 会让 dsh/codex 慢查询浪费 10 分钟，
#   统一 60s 又会把 codex 冷启动**合法**的慢调用误杀成 TIMEOUT。
AGENT_TIMEOUT_BUDGETS: dict[str, float] = {
    "deepseek-harness": 300.0,
    "pi": 120.0,
    "codex-cli": 300.0,
    "manual": 60.0,
}
#: 未知框架的兜底（**不参与**真实调用的适配器不会被走到这里）
DEFAULT_TIMEOUT_S = 180.0
#: 重试退避（秒）——固定值，**不抖动** ⇒ 考试可复现
RETRY_BACKOFF_S = 2.0
#: **同一进程内同时在飞的 Agent 调用上限 = 1**（施工令 §P5「并发」）
#:   理由（不是随口设的）：
#:     1) AI 成绩已被实测**不可复现**（同卷同模型两次差 19.17 分，见报告 V3 §P3）；
#:        并发再叠加供应商限流，只会让方差更大、归因更难；
#:     2) 并发调用会撞供应商限流 ⇒ 制造本可避免的 TIMEOUT ⇒ 污染「模型能否参与」的结论；
#:     3) 考场是**一次一卷**的串行语义 ⇒ 并发没有吞吐收益。
MAX_CONCURRENT_AGENT_CALLS = 1
#: 同一进程内串行化 Agent 调用（见上）
_AGENT_CALL_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_AGENT_CALLS)


def budget_for_framework(framework: str, *, max_calls: int = 2,
                         max_cost_usd: float = 0.0, require_known_cost: bool = False,
                         timeout_s: float | None = None,
                         retry_backoff_s: float = RETRY_BACKOFF_S,
                         max_total_s: float | None = None) -> Budget:
    """按**框架**给出预算（分 Agent 超时预算的唯一入口）。

    - ``timeout_s`` 显式给出时**覆盖**表里的默认（操作员显式配置优先）。
    - ``max_calls`` 默认 2：TIMEOUT / CALL_FAILED 会重试 1 次（失败恢复）。
    """
    key = (framework or "").strip().lower()
    explicit = timeout_s is not None
    t = AGENT_TIMEOUT_BUDGETS.get(key, DEFAULT_TIMEOUT_S) if timeout_s is None else float(timeout_s)
    if t <= 0:
        raise ValueError(f"BAD_TIMEOUT_S:{t}")
    if max_calls < 1:
        raise ValueError(f"BAD_MAX_CALLS:{max_calls}")
    return Budget(timeout_s=t, max_calls=max_calls, max_cost_usd=max_cost_usd,
                  require_known_cost=require_known_cost, retry_backoff_s=retry_backoff_s,
                  timeout_explicit=bool(explicit),
                  max_total_s=(t * max_calls + retry_backoff_s * max(0, max_calls - 1)
                               if max_total_s is None else float(max_total_s)))


# ── ★★ 按**任务规模**缩放单次超时（施工令 V3.0 §P5） ─────────────────────────
#
# **为什么要有这一层（实测事故，不是理论推演）**
#
# 分 Agent 超时预算表（``AGENT_TIMEOUT_BUDGETS``）是**按框架**给的**固定值**
# （pi=120s / dsh=300s / codex=300s），**与任务规模无关**。
# 但单次调用的耗时**随题目/义务条数增长** ⇒ 固定预算对大卷**结构性不够**：
#
#   本机实测（2026-10-31，真实模型调用，合成考场）：
#     pi · A 卷（3 义务，prompt 13.5KB）→ 22.97s   ⇒ 120s 预算够
#     pi · B 卷（10 义务，prompt 55KB） → 85.74s   ⇒ 120s 预算够（余量仅 1.4 倍）
#     pi · C 卷（**54 义务**，prompt 325KB）→ **120.45s 打满超时** ⇒ 跑不完，回执缺失
#     pi · C 卷（同一卷，超时放宽到 900s）→ **141.01s 跑完**，AI_SYSTEM_SCORE=100.0
#
# ⇒ **只差 21 秒**。⇒ 固定 120s 把「模型本来能考完」误判成「模型没参与」
#   （考试状态 FAIL、AI 成绩 NOT_SCORED）——**这是护栏在正确地报假绿，
#   但根因在预算，不在模型**。
#
# ★ 缩放**不能**变成「无限等待」：有**硬上限**（``TASK_SIZE_TIMEOUT_CAP_S``），
#   且总墙钟上限 ``max_total_s`` 随缩放后的单次超时一起走（重试也不会无限拖）。
# ★ **操作员显式给的超时优先**（``--agent-timeout``）⇒ 不参与缩放。

#: 每条义务的**增量耗时**（秒）。按上表实测取整并留约 2 倍余量。
TASK_SIZE_PER_OBLIGATION_S: dict[str, float] = {
    "pi": 5.0,
    "deepseek-harness": 5.0,
    "codex-cli": 5.0,
}
#: 未在表内的框架用的**保守缺省**。
TASK_SIZE_PER_OBLIGATION_DEFAULT_S = 5.0
#: 规模缩放里的**固定开销**（秒）：进程启动 + 上下文准备 + 回执收尾。
TASK_SIZE_FIXED_S = 20.0
#: ★ **硬上限**：任何规模都不许超过它 ⇒ 「不会导致无限等待」这条纪律的落地处。
TASK_SIZE_TIMEOUT_CAP_S = 600.0


def scaled_timeout_s(base_timeout_s: float, n_obligations: int, framework: str = "") -> float:
    """按**义务条数**给出该次调用的单次超时（秒）。

    口径：``max(框架基础预算, 固定开销 + 每义务增量 × 义务条数)``，再被**硬上限**截断。

    ★ 单调性：义务条数越多 ⇒ 超时**只增不减** ⇒ 小卷的行为**完全不变**
      （实测 A/B 两卷都仍取基础预算 120s）。
    """
    key = (framework or "").strip().lower()
    per = TASK_SIZE_PER_OBLIGATION_S.get(key, TASK_SIZE_PER_OBLIGATION_DEFAULT_S)
    n = max(0, int(n_obligations or 0))
    needed = TASK_SIZE_FIXED_S + per * n
    return min(TASK_SIZE_TIMEOUT_CAP_S, max(float(base_timeout_s), needed))


def scale_budget_for_task(budget: Budget, n_obligations: int, framework: str = "") -> Budget:
    """按任务规模缩放**单次超时**（并同步总墙钟上限）。

    ★ 操作员**显式**给的超时（``--agent-timeout``）**不缩放**。
    ★ 总墙钟上限跟着缩放后的单次超时走（否则第一次调用就被上限砍掉 ⇒ 等于没缩放）。
    """
    if budget.timeout_explicit:
        return budget
    t = scaled_timeout_s(budget.timeout_s, n_obligations, framework)
    if t == budget.timeout_s:
        return budget
    max_total = (t * budget.max_calls
                 + budget.retry_backoff_s * max(0, budget.max_calls - 1))
    return dataclasses.replace(budget, timeout_s=t, max_total_s=max_total)


def adapter_framework(adapter: Any) -> str:
    """取适配器的框架名（用于查分 Agent 超时预算）。

    ★ **框架 ≠ 服务商**：这里取的是 ``framework``（pi/codex-cli/deepseek-harness），
      **不是** ``vendor``（minimax-cn/openai/deepseek-official）。
    """
    fw = getattr(adapter, "framework", "") or ""
    if fw:
        return str(fw)
    return str(getattr(adapter, "adapter_id", "") or "")


def prepare_workdir(packet: dict[str, Any], base: Path | None = None) -> Path:
    """隔离工作目录：只放 packet.json + schema.json，不含仓库、不含原始材料、不含 Gold。"""
    d = Path(tempfile.mkdtemp(prefix="fos71-agent-", dir=str(base) if base else None))
    (d / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), "utf-8")
    shutil.copy(SCHEMA_PATH, d / "schema.json")
    return d


def _kill_tree(p: subprocess.Popen) -> None:
    if os.name == "nt":  # Windows：taskkill /T 杀整棵进程树
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, check=False)
        return
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_cli(argv: list[str], cwd: Path, timeout_s: float,
            stdin_text: str | None = None,
            env_overrides: dict[str, str] | None = None) -> tuple[int | None, str, str, float, bool]:
    """跑一个 CLI：stdin=/dev/null（防止等待输入挂起）或给定文本后立即 EOF，新进程组，超时杀整组。

    返回 (exit_code|None, stdout, stderr, elapsed_s, timed_out)。

    ★ ``env_overrides``：**运行时环境变量注入**（施工令 V3.0 §5.1）
      —— 凭证只进**子进程环境**，**不进 argv、不落盘、不进日志**。
      这是「dsh 自己那份凭证又过期了」时的**受控替代通道**：
      值由调用方从**已授权的凭证管理**里取，适配器只负责**注入**，不负责读取、不负责记录。
      ★ 子进程环境 = 父环境 + 覆盖项（**不是**只用覆盖项）⇒ Agent 仍能用它自己的登录态。
    """
    t0 = time.monotonic()
    child_env: dict[str, str] | None = None
    if env_overrides:
        child_env = {**os.environ, **env_overrides}
    try:
        p = subprocess.Popen(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            env=child_env,
            **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}),
        )
    except OSError as e:  # CLI 不存在 / 不可执行 → CALL_FAILED，而不是让调用方崩溃
        return 127, "", f"SPAWN_FAILED:{type(e).__name__}:{e}", 0.0, False
    try:
        out, err = p.communicate(input=stdin_text, timeout=timeout_s)
        return p.returncode, out, err, round(time.monotonic() - t0, 2), False
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        out, err = p.communicate()
        return None, out or "", err or "", round(time.monotonic() - t0, 2), True


# ═══════════════════════════════════════════════════════════════════════════
# 模型身份核实（施工令 V3.0 §7.1）—— 三个 Agent 各自的**官方**元数据来源
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_codex_identity(thread_id: str, workdir: Path) -> Any:
    """codex 的模型身份 = 它**自己的执行记录**（rollout）里的 ``turn_context.model``。

    ★ 拿不到就是 UNKNOWN（**不猜**）—— 典型情形：用了 ``--ephemeral``（不落盘），
      或会话存储不在预期位置。
    """
    return ident.resolve_codex_identity(thread_id, expected_cwd=str(workdir))


def _resolve_pi_identity(events_text: str) -> Any:
    """pi 的模型身份 = 它**自己的事件流**里 ``message_end.message.model``。"""
    return ident.resolve_pi_identity(events_text)


def _resolve_dsh_identity(profile: str, binary: str, workdir: Path) -> Any:
    """dsh 的模型身份 = 它**自己的配置树**（``--dump-config`` 的 ``agent-default-model``）。"""
    return ident.resolve_dsh_identity(profile, binary=binary, expected_cwd=str(workdir))


# ═══════════════════════════════════════════════════════════════════════════
# 错误分类（施工令 V3.0 §P5）—— stderr ⇒ **稳定错误码**
# ═══════════════════════════════════════════════════════════════════════════

#: 稳定错误码 ⇒ 人话解释（**不含**任何密钥值）
ERROR_CODES: dict[str, str] = {
    "DSH_AUTH_INVALID": "dsh 的 API key 被服务端判 invalid（**凭证问题**，不是网络问题）",
    "DSH_PROXY_UNSUPPORTED": "dsh 遇到 SOCKS 代理（dsh 只支持 http/https 代理）⇒ 它会直连",
    "DSH_TIMEOUT": "dsh 调用超时（预算不够或服务端无响应）",
    "CODEX_AUTH_FAILED": "codex 认证失败（登录态缺失/过期/被拒）",
    "CODEX_NOT_FOUND": "codex 可执行文件不在 PATH",
    "PI_AUTH_FAILED": "pi 认证失败（provider 凭证缺失/过期）",
    "PI_NOT_FOUND": "pi 可执行文件不在 PATH",
    "SPAWN_FAILED": "进程起不来（可执行文件不存在/不可执行）",
    "TIMEOUT": "调用超时（已杀进程组）",
    "CALL_FAILED": "调用失败（退出码非 0）",
}


def classify_agent_error(adapter_id: str, status: str, stderr: str,
                         exit_code: int | None = None) -> str:
    """把「一次失败的调用」归到一个**稳定错误码**（不看自由文本）。

    ★ 为什么要分类：上一轮那次真实故障（``****9bb5 is invalid``）被塞进
      ``reason=EXIT_1:dsh: AUTH: ...`` ⇒ 下游只能靠**正则**认它 ⇒ 极易漏判。
    ⇒ 现在**同一个错误永远映射到同一个码** ⇒ 门禁与告警可以直接按码判。
    """
    err = str(stderr or "")
    low = err.lower()
    if status == TIMEOUT:
        return "TIMEOUT"
    if "spawn_failed" in low:
        return "SPAWN_FAILED"
    if "authentication fails" in low or "api key" in low and "invalid" in low:
        return "DSH_AUTH_INVALID" if adapter_id == "deepseek-harness" else "PI_AUTH_FAILED"
    if "401" in low and "unauthorized" in low:
        return "CODEX_AUTH_FAILED" if adapter_id == "codex-cli" else "PI_AUTH_FAILED"
    if "socks proxy" in low or "not supported" in low and "proxy" in low:
        return "DSH_PROXY_UNSUPPORTED"
    if "not found" in low and ("no such file" in low or "cannot find" in low):
        return "CODEX_NOT_FOUND" if adapter_id == "codex-cli" else "PI_NOT_FOUND"
    return "CALL_FAILED" if status == CALL_FAILED else str(status or "UNKNOWN")


def _prompt_for(packet: dict[str, Any], agent_id: str, provider: str, inline: bool) -> str:
    head = (f"按 packet 的 instructions 完成任务，只输出符合输出 Schema 的 JSON。agent_id 填 \"{agent_id}\"，"
            f"provider 填 \"{provider}\"，model_id_or_unknown 填你确知的模型标识否则 \"UNKNOWN\"，"
            "prompt_version 与 source_snapshot_id 原样照抄 packet，elapsed 与 token_usage_or_UNKNOWN 填 \"UNKNOWN\"。"
            "不要修改任何文件。")
    if not inline:
        return "读取当前目录的 packet.json。" + head
    return (head + "不要调用工具。不要输出 markdown。\n\n=== PACKET ===\n"
            + json.dumps(packet, ensure_ascii=False, indent=2)
            + "\n=== SCHEMA ===\n" + SCHEMA_PATH.read_text("utf-8"))


def _fail(res: AdapterResult, code: int | None, err: str, timed_out: bool) -> AdapterResult:
    res.exit_code = code
    if timed_out:
        res.status, res.reason = TIMEOUT, "TIMEOUT"
    else:
        # ★ **稳定错误码**（施工令 V3.0 §P5）：同一个错误永远映射到同一个码
        #   ⇒ 下游/门禁/告警可以**按码判**（`reason` 的第一个 `:` 之前那段），不必对自由文本做正则。
        # ★ 原始 stderr **仍然保留**在 reason 尾部 **且**完整落在 stderr.log 里（留证）。
        #   ⇒ 既有「第 1 轮复核」那条「reason 必须带原文」的断言继续成立。
        # ★ 嵌进 reason 前先脱敏（万一 stderr 里出现了注入进来的密钥）。
        safe = redact_secrets(str(err or "")).strip()[-200:]
        code_name = classify_agent_error(res.adapter_id, CALL_FAILED, err, code)
        res.status, res.reason = CALL_FAILED, f"{code_name}:EXIT_{code}:{safe}"
        res.provenance = {**res.provenance, "error_code": code_name,
                          "error_explain": ERROR_CODES.get(code_name, "")}
    return res


#: ★ codex 的 ``--output-schema`` 走 OpenAI structured outputs 的**严格模式**：
#:   每个 object 的 ``required`` 必须**覆盖每一个** property。
#:   ⇒ DD-V1 的**可选**字段（``proposed_doc_type`` / ``rejected_alternatives``）
#:     会让 codex 直接 **400 invalid_json_schema**（本轮实测）。
#:   ⇒ 这里把它们改成「**必填、但可为 null**」⇒ **语义不变**（null ≡ 未提供：
#:     下游读的是 ``str(r.get("proposed_doc_type") or "")`` ⇒ null 与缺省同义）。
def _widen_to_nullable(node: Any) -> None:
    """把一个 schema 节点的类型/枚举放宽到「可为 null」（**原地**修改）。"""
    if not isinstance(node, dict):
        return
    t = node.get("type")
    if isinstance(t, str):
        node["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        node["type"] = [*t, "null"]
    if isinstance(node.get("enum"), list) and None not in node["enum"]:
        node["enum"] = [*node["enum"], None]
    for v in node.values():
        if isinstance(v, dict):
            _widen_to_nullable(v)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    _widen_to_nullable(it)


def strict_output_schema(base: dict[str, Any] | None = None) -> dict[str, Any]:
    """产出**严格**输出 schema（给 codex 的 ``--output-schema`` 用）。

    规则：每个 object 的 ``required`` ＝ 它的**全部** property；
    原本**可选**的字段额外允许 ``null``。
    ★ 只影响**给 Agent 的输出契约**；DD-V1 自己的硬校验器（``validate_agent_output``）
      **一个字没改** ⇒ 放行标准仍然是 DD-V1 的判据。
    """
    raw = json.loads(json.dumps(base if base is not None
                                else json.loads(SCHEMA_PATH.read_text("utf-8"))))

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for it in node:
                _walk(it)
            return
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict) and props:
            original = set(node.get("required") or [])
            for key, sub in props.items():
                if key not in original:
                    _widen_to_nullable(sub)
            node["required"] = sorted(props.keys())
        for _key, sub in list(node.items()):
            if _key == "enum":
                continue
            _walk(sub)

    _walk(raw)
    return raw


class CodexAdapter:
    adapter_id, vendor, role = "codex-cli", "openai-codex", "EXAMINEE_2"
    # ★ 参与类别由**实现类**决定（不是自填字符串）⇒ 见模块末尾 ADAPTER_PARTICIPATION_CLASSES
    participation_class = "HARNESS_MODEL"
    framework = "codex-cli"

    def __init__(self, binary: str | list[str] = "codex", *, model: str | None = None,
                 persist_session: bool = False):
        self.binary = [binary] if isinstance(binary, str) else list(binary)
        #: 显式钉住模型（codex 官方选择机制 ``-m/--model``）⇒ 钉了且跑通 ⇒ 请求发的是这个模型
        self.model = model
        #: ★ **落盘执行记录**（默认 False = 仓库默认行为不变）
        #   codex 的 ``--ephemeral`` 明确「不落盘」⇒ **没有执行记录 ⇒ 模型身份无从核实**
        #   ⇒ 打开后 codex 会写 rollout（``turn_context.payload.model``），身份才可绑定到本次调用。
        self.persist_session = bool(persist_session)

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
        res.framework = self.framework
        for stale in ("out.json", "events.jsonl", "stderr.log"):  # 复核 N2：绝不读残留答卷
            (workdir / stale).unlink(missing_ok=True)
        # ★★ codex 的输出 schema 必须换**严格变体**（否则 400 invalid_json_schema）
        (workdir / "schema.json").write_text(
            json.dumps(strict_output_schema(), ensure_ascii=False, indent=2), "utf-8")
        argv = [*self.binary, "exec"]
        if not self.persist_session:
            argv.append("--ephemeral")
        if self.model:
            argv += ["--model", self.model]
        argv += ["--skip-git-repo-check", "-C", str(workdir),
                 "-s", "read-only", "--output-schema", "schema.json", "-o", "out.json", "--json",
                 _prompt_for(packet, self.adapter_id, self.vendor, inline=False)]
        res.argv_summary = argv[:-1] + ["<prompt>"]
        code, out, err, el, to = run_cli(argv, workdir, budget.timeout_s)
        res.elapsed_s = el
        res.cost_usd_or_UNKNOWN = "UNKNOWN(ChatGPT subscription)"
        (workdir / "events.jsonl").write_text(out, "utf-8")
        (workdir / "stderr.log").write_text(err, "utf-8")
        if to or code != 0:
            return _fail(res, code, err, to)
        res.exit_code = 0
        thread_id = ""
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
                res.token_usage_or_UNKNOWN = ev["usage"]
            if ev.get("type") == "thread.started":
                thread_id = str(ev.get("thread_id") or "")
        o = workdir / "out.json"
        res.raw_text = o.read_text("utf-8") if o.exists() else None
        # ★★ **模型身份核实**（施工令 V3.0 §7.1）：只用 codex **自己的执行记录**
        identity = _resolve_codex_identity(thread_id, workdir)
        res.model_id_or_unknown = identity.model_id
        res.model_identity_source = identity.source
        res.model_identity_verified = bool(identity.verified)
        res.provenance = {**res.provenance, "model_identity": identity.to_dict(),
                          "thread_id": thread_id}
        return res


class PiAdapter:
    """pi 框架（``@earendil-works/pi-coding-agent``）。

    ★★ **框架 ≠ 服务商**（施工令 V3.0 §5.2）：
      ``pi`` 是第三方 **Agent 框架**；``minimax-cn`` 只是它配置里的一个 **provider**。
      ⇒ 本类 ``framework="pi"``、``vendor="minimax-cn"``（**可换**）——
      两者**分开记**，避免把「用 pi 框架」说成「用 MiniMax 模型」。

    ★ 保留 ``MiniMaxPiAdapter`` 别名（向后兼容）—— 它**指的就是同一个类对象**
      ⇒ ``ADAPTER_PARTICIPATION_CLASSES`` 的**精确类型**判定不受影响。
    """

    adapter_id, vendor, role = "pi", "minimax-cn", "AUX"
    participation_class = "HARNESS_MODEL"
    framework = "pi"

    def __init__(self, binary: str | list[str] = "pi", model: str | None = None,
                 provider: str = "minimax-cn"):
        self.binary = [binary] if isinstance(binary, str) else list(binary)
        self.model = model
        self.provider = provider

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
        res.framework = self.framework
        for stale in ("events.compact.jsonl", "stderr.log"):
            (workdir / stale).unlink(missing_ok=True)
        argv = [*self.binary, "-p", "--provider", self.provider, "--no-session", "--no-tools", "--mode", "json"]
        if self.model:
            argv += ["--model", self.model]
        argv.append(_prompt_for(packet, self.adapter_id, self.vendor, inline=True))
        res.argv_summary = argv[:-1] + ["<prompt>"]
        code, out, err, el, to = run_cli(argv, workdir, budget.timeout_s)
        res.elapsed_s = el
        (workdir / "stderr.log").write_text(err, "utf-8")
        compact = []
        last = None
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "message_update":
                compact.append(line)
            if ev.get("type") == "message_end" and ev.get("message", {}).get("role") == "assistant":
                last = ev["message"]
        (workdir / "events.compact.jsonl").write_text("\n".join(compact), "utf-8")
        if to or code != 0:
            return _fail(res, code, err, to)
        res.exit_code = 0
        if last:
            res.raw_text = "".join(c.get("text", "") for c in last.get("content", []) if c.get("type") == "text")
            res.model_id_or_unknown = last.get("model") or "UNKNOWN"
            res.token_usage_or_UNKNOWN = last.get("usage", "UNKNOWN")
            cost = (last.get("usage") or {}).get("cost", {}) if isinstance(last.get("usage"), dict) else {}
            if isinstance(cost, dict) and isinstance(cost.get("total"), (int, float)):
                res.cost_usd_or_UNKNOWN = cost["total"]
        # ★★ **模型身份核实**：pi 自己的事件流里带 model ⇒ **权威**
        identity = _resolve_pi_identity(out)
        if identity.verified:
            res.model_id_or_unknown = identity.model_id
        res.model_identity_source = identity.source
        res.model_identity_verified = bool(identity.verified)
        res.provenance = {**res.provenance, "model_identity": identity.to_dict(),
                          "framework": self.framework, "provider": self.provider}
        return res


#: ★ 向后兼容别名（**同一个类对象** ⇒ 参与类别判定不受影响）
MiniMaxPiAdapter = PiAdapter


class PrebakedResultAdapter:
    """**预置回执**适配器：把一份已经写好的模型回执 JSON 当作本次调用结果。

    ★ **它不是 Harness 运行**：回执是**别人贴进来的**（文件）⇒ 身份不可自证。
    ⇒ 因此它的 ``adapter_id`` **不在** ``bridge_service.KNOWN_HARNESS_ADAPTERS`` 里
      ⇒ 参与类别恒为 ``PREBAKED_RESULT`` ⇒ **不得**计为「模型参与」的凭据。
    ★ 存在的意义：让「模型判过的结果」能**被真实消费**（驱动选材），
      同时在成绩单上把「这是贴进来的回执」如实标出来。
    """

    adapter_id, vendor, role = "prebaked-result", "operator-prebaked", "MANUAL"
    # ★ 预置回执 = **人工预置**，不是模型参与 ⇒ 类别 `PREBAKED_RESULT`
    participation_class = "PREBAKED_RESULT"

    def __init__(self, result_path: str | Path):
        self.result_path = Path(result_path)

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK,
                            workdir=str(workdir))
        if not self.result_path.is_file():
            res.status, res.reason = CALL_FAILED, f"RESULT_FILE_NOT_FOUND:{self.result_path}"
            return res
        data = self.result_path.read_bytes()
        res.raw_text = data.decode("utf-8")
        res.exit_code = 0
        res.provenance = {
            "reply_sha256": hashlib.sha256(data).hexdigest(),
            "reply_source": "PREBAKED_FILE",
            "declared_by": "UNKNOWN",
            "independent_examinee_answer": False,
            "note": "★ 预置回执：不是本机 Harness 运行 ⇒ 不构成「模型参与」的凭据",
        }
        res.model_id_or_unknown = "UNKNOWN"
        return res


def build_adapter(spec: str, *, result_path: str | Path | None = None,
                  dsh_enabled: bool = False, dsh_env_overrides: dict[str, str] | None = None,
                  codex_model: str | None = None, codex_persist_session: bool = False,
                  pi_model: str | None = None, pi_provider: str = "minimax-cn") -> Any:
    """按名字建适配器（**薄入口**：CLI 只认这几个名字，不自己拼 argv）。

    - ``codex``  → 本机 ``codex`` CLI（材料不出本机）
    - ``pi``     → 本机 ``pi`` CLI（**框架** pi；``pi_provider`` 是服务商，默认 minimax-cn）
    - ``dsh``    → 本机 ``dsh``（DeepSeek Harness；**要不要开由操作员自己决定**）
    - ``manual`` → 人工交换（贴回执）
    - ``prebaked``／给了 ``result_path`` → 预置回执（**不是 Harness 运行**）

    ★ ``dsh_env_overrides``：**运行时注入**的凭证（只进子进程环境，不落盘/不进 argv/不进日志）。
    ★ ``codex_persist_session``：落盘 codex 执行记录 ⇒ **模型身份才可核实**（否则 UNKNOWN）。
    """
    s = str(spec or "").strip().lower()
    if s in ("", "none", "rule_only", "rule-only"):
        return None
    if s in ("prebaked", "file", "result"):
        if not result_path:
            raise ValueError("PREBAKED_NEEDS_RESULT_PATH")
        return PrebakedResultAdapter(result_path)
    if result_path:
        # 给了回执文件 ⇒ 走「预置回执」（不回落到真 Harness 运行）
        return PrebakedResultAdapter(result_path)
    if s in ("codex", "codex-cli"):
        return CodexAdapter(model=codex_model, persist_session=codex_persist_session)
    if s in ("pi", "minimax-pi"):
        return PiAdapter(model=pi_model, provider=pi_provider)
    if s in ("dsh", "deepseek", "deepseek-harness"):
        return DeepSeekHarnessAdapter(enabled=bool(dsh_enabled), env_overrides=dsh_env_overrides)
    if s in ("manual", "manual-exchange"):
        return ManualExchangeAdapter()
    raise ValueError(f"UNKNOWN_AGENT:{spec}")


class ManualExchangeAdapter:
    """人工交换（#71 R2 第一 PoC）：导出 packet+schema，操作者把模型回复贴成 reply.json。"""
    adapter_id, vendor, role = "manual-exchange", "operator", "MANUAL"
    participation_class = "HARNESS_MANUAL"

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
        (workdir / "PROMPT.txt").write_text(_prompt_for(packet, "manual", "operator", inline=True), "utf-8")
        reply = workdir / "reply.json"
        if not reply.exists():
            res.status, res.reason = PENDING_MANUAL, f"PASTE_MODEL_REPLY_TO:{reply}"
            res.provenance = {"independent_examinee_answer": False}
            return res
        data = reply.read_bytes()
        res.raw_text = data.decode("utf-8")
        # 复核 N1：回贴必须自带来源；没写来源就记 UNDECLARED。人工回贴永远不算独立考生答卷。
        prov_file = workdir / "reply.provenance.json"
        declared = json.loads(prov_file.read_text("utf-8")) if prov_file.exists() else {}
        res.provenance = {
            "reply_sha256": hashlib.sha256(data).hexdigest(),
            "reply_source": declared.get("reply_source", "UNDECLARED_OPERATOR_PASTE"),
            "declared_by": declared.get("declared_by", "UNKNOWN"),
            "independent_examinee_answer": False,
        }
        res.model_id_or_unknown = declared.get("model_id_or_unknown", "UNKNOWN")
        return res


SECRET_NAME_RE = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def redact_secrets(text: str, env: dict[str, str] | None = None) -> str:
    """把环境变量里看起来是密钥的值从日志文本中抹掉（用户自己的 key 永不落盘）。"""
    env = os.environ if env is None else env
    for k, v in env.items():
        if v and len(v) >= 8 and any(t in k.upper() for t in SECRET_NAME_RE):
            text = text.replace(v, f"<REDACTED:{k}>")
    return text


def redact_injected(text: str, env_overrides: dict[str, str] | None = None) -> str:
    """把**注入进去的**值无条件抹掉（**不看变量名**）。

    ★ 为什么不能只靠 :func:`redact_secrets`：它只抹「名字里含
      KEY/TOKEN/SECRET/PASSWORD」的变量 ⇒ 注入通道里的变量名若不含这些词，
      值就会**原样**留在 stdout/stderr 里 ⇒ 落进 ``answer.txt``（**真实泄漏路径**）。
    ★ 注入通道里的值是**操作员显式声明**要保密的 ⇒ **无条件**抹。
    """
    for k, v in (env_overrides or {}).items():
        if v and len(str(v)) >= 8:
            text = text.replace(str(v), f"<REDACTED:{k}>")
    return text


def load_dsh_config(path: Path | None) -> dict[str, Any]:
    """dsh 本地配置（JSON）：binary / profile / extra_args / mode。不允许在配置里写密钥。

    mode="stdin"（默认）：任务包经标准输入传给 `dsh ... -`，命令行里没有任何材料文字——
    Windows 上 .cmd 经 cmd.exe 启动时不会被解释（无注入、无 8191 长度限制），dsh 也不需要读文件权限。
    mode="file"：让 dsh 自己读 workdir/PROMPT.txt（需要 dsh 有读文件能力，不推荐）。
    """
    cfg: dict[str, Any] = {"binary": "dsh", "profile": "headless", "extra_args": [], "mode": "stdin",
                            "env_from": []}
    if path:
        user = json.loads(Path(path).read_text("utf-8-sig"))
        bad = [k for k in user if any(t in k.upper() for t in SECRET_NAME_RE)]
        if bad:
            raise ValueError(f"DSH_CONFIG_MUST_NOT_CONTAIN_SECRETS:{bad}（密钥放在你自己的环境变量里）")
        unknown = set(user) - set(cfg)
        if unknown:
            raise ValueError(f"DSH_CONFIG_UNKNOWN_FIELDS:{sorted(unknown)}")
        cfg.update(user)
    if cfg["mode"] not in ("stdin", "file"):
        raise ValueError(f"DSH_CONFIG_BAD_MODE:{cfg['mode']}")
    # ★ `env_from` **只允许环境变量名**（不允许写字面量）⇒ 配置里**不可能**藏密钥
    for name in (cfg.get("env_from") or []):
        if not re.match(r"^[A-Z][A-Z0-9_]*$", str(name)):
            raise ValueError(f"DSH_ENV_FROM_BAD_NAME:{name}")
    cfg["env_from"] = [str(n) for n in (cfg.get("env_from") or [])]
    return cfg


def extract_json_text(text: str) -> str | None:
    """从 CLI 的最终回答里取出 JSON 对象（容忍 ```json 围栏和前后说明文字）。取不到返回 None。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    lo, hi = t.find("{"), t.rfind("}")
    return t[lo:hi + 1] if lo != -1 and hi > lo else None


class DeepSeekHarnessAdapter:
    """DeepSeek Harness（dsh）。

    默认（enabled=False）：桩，UNAVAILABLE，不起任何进程、不联网——仓库默认行为不变。
    本地 opt-in（enabled=True，只能由操作员在自己的机器上用 `--allow-local-dsh` 显式打开）：
    在隔离 workdir 里跑 ``dsh --profile <profile> headless <prompt>``（stdin=/dev/null，硬超时），
    最终回答取 stdout。本代码不上传、不外发任何东西；dsh 自己如何调用模型由操作员的 dsh 配置决定。
    """
    adapter_id, vendor = "deepseek-harness", "deepseek-harness"
    participation_class = "HARNESS_MODEL"
    framework = "deepseek-harness"

    def __init__(self, enabled: bool = False, binary: str | list[str] = "dsh", profile: str = "headless",
                 mode: str = "stdin", role: str = "EXAMINEE_3", extra_args: list[str] | None = None,
                 env_overrides: dict[str, str] | None = None):
        if mode not in ("stdin", "file"):
            raise ValueError(f"BAD_MODE:{mode}")
        self.enabled, self.profile, self.mode, self.role = enabled, profile, mode, role
        self.binary = [binary] if isinstance(binary, str) else list(binary)
        self.extra_args = list(extra_args or [])
        # ★★ **运行时凭证注入**（施工令 V3.0 §5.1）
        #   值只进**子进程环境**：不进 argv、不落盘、不进日志、不进 run_record。
        #   ⇒ dsh 自己那份凭证又过期时，可用**已授权**的替代凭证通道跑通，**不必**改 dsh 的磁盘配置。
        self.env_overrides = dict(env_overrides or {})
        # ★ fail-closed：空值 / 纯空白 / None 一律拒绝
        #   （传空值 = 「看起来调用了、必然鉴权失败」的**假调用**）
        for _k, _v in self.env_overrides.items():
            if _v is None or not str(_v).strip():
                raise ValueError(f"DSH_ENV_OVERRIDE_EMPTY:{_k}")

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, enabled: bool, role: str = "PRIMARY_LOCAL_DSH",
                    env_overrides: dict[str, str] | None = None) -> "DeepSeekHarnessAdapter":
        # ★ ``env_from`` 只允许**环境变量名**（不允许写字面量）⇒ 配置里**不可能**藏密钥
        env_ov = dict(env_overrides or {})
        for name in (cfg.get("env_from") or []):
            val = os.environ.get(str(name))
            if not val:
                raise ValueError(f"DSH_ENV_FROM_NOT_SET:{name}")
            env_ov[str(name)] = val
        return cls(enabled=enabled, binary=cfg["binary"], profile=cfg["profile"], mode=cfg["mode"],
                   role=role, extra_args=cfg["extra_args"], env_overrides=env_ov)

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
        res.framework = "deepseek-harness"
        if not self.enabled:
            res.status = UNAVAILABLE
            res.reason = ("BLOCKED:dsh not enabled in this environment (repo default). "
                          "Operator may opt in locally with --allow-local-dsh; no purchase, no API fallback")
            return res
        for stale in ("answer.txt", "stderr.log", "PROMPT.txt"):
            (workdir / stale).unlink(missing_ok=True)
        prompt = _prompt_for(packet, self.adapter_id, self.vendor, inline=True)
        # 命令行里只放固定的 ASCII 参数；材料文字绝不进 argv（#78 复核 High-1：cmd.exe 注入 / 8191 限制）
        if self.mode == "stdin":
            argv, stdin_text = [*self.binary, "--profile", self.profile, *self.extra_args, "-"], prompt
        else:
            (workdir / "PROMPT.txt").write_text(prompt, "utf-8")
            argv = [*self.binary, "--profile", self.profile, *self.extra_args,
                    "Read PROMPT.txt in the current directory and follow it exactly. Output only JSON."]
            stdin_text = None
        res.argv_summary = list(argv)
        # ★ 只在**真的有注入**时才多传一个 kwarg ⇒ 没有注入时，调用形状与旧版**逐字一致**
        #   （既有测试里的 spy/桩仍能接住）。
        _cli_kwargs: dict[str, Any] = {"stdin_text": stdin_text}
        if self.env_overrides:
            _cli_kwargs["env_overrides"] = self.env_overrides
        code, out, err, el, to = run_cli(argv, workdir, budget.timeout_s, **_cli_kwargs)
        res.elapsed_s = el
        # ★ 抹掉**注入进去的**密钥（连同父环境里的同名变量）⇒ 日志里不会出现明文
        # ★★ **stdout 也要按合并环境脱敏**：原实现只对 stderr 用合并环境
        #   ⇒ dsh 把注入的凭证**回显到 stdout** 时，它会**原样落进 answer.txt**
        #   ⇒ 那是**真实泄漏路径**（本 PR 的实测复现：answer.txt 里出现明文 key）。
        _merge_env = {**os.environ, **self.env_overrides}
        out = redact_secrets(redact_injected(out, self.env_overrides), _merge_env)
        err = redact_secrets(redact_injected(err, self.env_overrides), _merge_env)
        (workdir / "answer.txt").write_text(out, "utf-8")
        (workdir / "stderr.log").write_text(err, "utf-8")
        if to or code != 0:
            return _fail(res, code, err, to)
        res.exit_code = 0
        res.raw_text = extract_json_text(out)
        res.cost_usd_or_UNKNOWN = "UNKNOWN(operator dsh account)"
        # ★★ **模型身份核实**：dsh 自己的配置树（``--dump-config``）⇒ **权威**
        identity = _resolve_dsh_identity(self.profile, self.binary[0], workdir)
        res.model_id_or_unknown = identity.model_id
        res.model_identity_source = identity.source
        res.model_identity_verified = bool(identity.verified)
        res.provenance = {**res.provenance, "model_identity": identity.to_dict()}
        return res


ADAPTERS: dict[str, Callable[[], Any]] = {
    "codex": CodexAdapter, "minimax-pi": MiniMaxPiAdapter,
    "manual": ManualExchangeAdapter, "deepseek-harness": DeepSeekHarnessAdapter,
}


def run_agent(adapter: Any, snapshot_dir: Path, meta: list[dict[str, str]],
              obligations: list[dict[str, str]], budget: Budget | None = None,
              workdir: Path | None = None, packet: dict[str, Any] | None = None,
              non_effective_files: frozenset[str] = frozenset()) -> dict[str, Any]:
    """一次完整的 Agent 调用：建包 → 隔离目录 → Adapter → 校验/降级。返回可留证的 run record。

    packet：调用方已建好的任务包（WP04 语义包：最小证据而不是整份文件摘录）；不传则用 WP01 的默认包。
    """
    budget = budget if budget is not None else Budget()
    if budget.max_calls < 1:
        raise ValueError("budget.max_calls must be >= 1")
    if budget.max_cost_usd < 0:
        raise ValueError("budget.max_cost_usd must be >= 0")
    packet = packet if packet is not None else ar.build_task_packet(snapshot_dir, meta, obligations)
    # ★★ **按任务规模缩放单次超时**（施工令 P5；这里 packet 已就位 ⇒ 规模**已知**）。
    #   小卷行为**完全不变**（实测 A/B 两卷仍取基础预算）；大卷（42 题）不再被固定预算砍断。
    #   ★ 显式给的超时（``--agent-timeout``）不参与缩放（操作员配置优先）。
    budget = scale_budget_for_task(
        budget,
        n_obligations=len(packet.get("obligations") or []) or len(obligations or []),
        framework=adapter_framework(adapter),
    )
    # 必须是绝对路径：CLI 以 cwd=wd 启动，相对路径的 -C 会被二次拼接（WP03 Mac 实测 codex exit 1）
    wd = (workdir or prepare_workdir(packet)).resolve()
    if workdir:
        wd.mkdir(parents=True, exist_ok=True)
        present = {p.name for p in wd.iterdir()}
        allowed = MANUAL_ALLOWED if isinstance(adapter, ManualExchangeAdapter) else set()
        if present - allowed:  # 复核 N2：非空目录直接拒绝，防止读到残留 out.json 或混入其他资料
            raise ValueError(f"WORKDIR_NOT_EMPTY:{sorted(present - allowed)}")
        (wd / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), "utf-8")
        shutil.copy(SCHEMA_PATH, wd / "schema.json")
    attempts: list[dict[str, Any]] = []
    t_start = time.monotonic()

    def _one_call() -> AdapterResult:
        # ★ **并发护栏**：同一进程内同时在飞的 Agent 调用 ≤ 1（见 MAX_CONCURRENT_AGENT_CALLS 注释）
        with _AGENT_CALL_SEMAPHORE:
            return adapter.run(packet, wd, budget)

    def _attempt_row(n: int, r: AdapterResult) -> dict[str, Any]:
        return {"n": n, "status": r.status, "exit_code": r.exit_code, "elapsed_s": r.elapsed_s,
                "cost_usd_or_UNKNOWN": r.cost_usd_or_UNKNOWN,
                "token_usage_or_UNKNOWN": r.token_usage_or_UNKNOWN,
                "error_code": (r.reason or "").split(":", 1)[0] or None,
                "wall_elapsed_s": round(time.monotonic() - t_start, 2)}

    res: AdapterResult = _one_call()
    attempts.append(_attempt_row(1, res))
    n = 1
    while res.status in RETRYABLE and len(attempts) < budget.max_calls:
        # 失败恢复：退避后再试；**总墙钟**触顶就不再试（杜绝无限等待）
        if budget.retry_backoff_s > 0:
            time.sleep(budget.retry_backoff_s)
        if (time.monotonic() - t_start) + budget.timeout_s > budget.max_total_s:
            attempts.append({"n": n + 1, "status": "SKIPPED_MAX_TOTAL_BUDGET",
                             "exit_code": None, "elapsed_s": None,
                             "wall_elapsed_s": round(time.monotonic() - t_start, 2)})
            break
        n += 1
        res = _one_call()
        attempts.append(_attempt_row(n, res))
    cost = res.cost_usd_or_UNKNOWN
    known = isinstance(cost, (int, float)) and not isinstance(cost, bool)
    if known and cost > budget.max_cost_usd:
        res.status, res.reason, res.raw_text = BUDGET_EXCEEDED, f"COST_{cost}>{budget.max_cost_usd}", None
    elif not known and budget.require_known_cost and res.status == OK:  # #76 复核低：付费 Adapter 时 UNKNOWN 直接拒（fail closed）
        res.status, res.reason, res.raw_text = BUDGET_EXCEEDED, "COST_UNKNOWN_BUT_REQUIRED", None
    call_error = None if res.status == OK else f"{res.status}:{res.reason}"
    rep = ar.validate_agent_output(res.raw_text, snapshot_dir, meta, obligations, call_error=call_error,
                                   non_effective_files=non_effective_files)
    record = {
        "schema_version": ar.SCHEMA_VERSION, "prompt_version": packet.get("prompt_version", ar.PROMPT_VERSION),
        "source_snapshot_id": packet["source_snapshot_id"],
        "budget": asdict(budget),
        "calls_used": sum(1 for a in attempts if a.get("status") != "SKIPPED_MAX_TOTAL_BUDGET"),
        "attempts": attempts,
        # ★ 成本/耗时账（P5）：一次调用一个总账 + 逐次明细（可复算）
        "perf": {"total_elapsed_s": round(time.monotonic() - t_start, 2),
                 "cost_usd_or_UNKNOWN": res.cost_usd_or_UNKNOWN,
                 "token_usage_or_UNKNOWN": res.token_usage_or_UNKNOWN,
                 "attempts_cost": [a.get("cost_usd_or_UNKNOWN") for a in attempts],
                 "max_total_s": budget.max_total_s, "budget_exhausted":
                     len(attempts) >= budget.max_calls
                     or any(a.get("status") == "SKIPPED_MAX_TOTAL_BUDGET" for a in attempts)},
        "adapter": res.to_dict(), "validation": rep.to_dict(),
    }
    (wd / "run_record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


#: ★ ★ `UNKNOWN_ADAPTER` **必须定义在这之前**（第 6 轮独立复核的 F16：import 地雷）
#:   —— 推导式里 `or UNKNOWN_ADAPTER` 只在**类没写该属性**时求值；
#:   那天 5 个类都写了 ⇒ 短路 ⇒ 右操作数**从未求值** ⇒ 地雷没炸；
#:   一旦加了第 6 个适配器类忘了写 ⇒ **NameError at import** ⇒ 整个 backend 起不来。
UNKNOWN_ADAPTER = "UNKNOWN_ADAPTER"

# ══════════════════════════════════════════════════════════════════════
# ★ 参与类别**注册表**（权威来源 = **适配器实现类**，不是任何自填字符串）
# ══════════════════════════════════════════════════════════════════════
#: 实现类 → 参与类别。**精确类型匹配**（不是 isinstance）：
#:   ⇒ 自造一个 ``class _Spoof: adapter_id = "codex-cli"`` **拿不到** ``HARNESS_MODEL``；
#:   ⇒ 连子类也不认（宁可不认，也不要认错）。
#: ★ 由**类属性**生成（类属性是**唯一来源** ⇒ 不会出现「没人读的自填字段」）
ADAPTER_PARTICIPATION_CLASSES: dict[type, str] = {
    cls: str(getattr(cls, "participation_class", "") or UNKNOWN_ADAPTER)
    for cls in (CodexAdapter, MiniMaxPiAdapter, DeepSeekHarnessAdapter,
                ManualExchangeAdapter, PrebakedResultAdapter)
}


#: ★ **id 级声明表**（只是**旁证**；权威判定在 :func:`participation_class_of`）
#:   —— 放在实现侧，是因为「这个 id 对应哪一类」是**适配器实现**的知识。
KNOWN_ADAPTER_ID_CLASSES: dict[str, str] = {
    "codex-cli": "HARNESS_MODEL",
    "deepseek-harness": "HARNESS_MODEL",
    "pi": "HARNESS_MODEL",
    "manual-exchange": "HARNESS_MANUAL",
    "prebaked-result": "PREBAKED_RESULT",
}


#: ★ 参与类别的**合法取值**（答卷层只认这几个；其余一律 UNDECLARED）
PARTICIPATION_CATEGORIES = ("HARNESS_MODEL", "HARNESS_MANUAL", "PREBAKED_RESULT",
                             "UNKNOWN_ADAPTER", "RULE_ONLY",
                             "MODEL_SELECTION_WITHOUT_RECEIPT")


def participated_flag(adapter_result: dict[str, Any] | None) -> bool:
    """适配器**真的跑出了回执**吗？（第 6 轮独立复核的 F1，已修）

    ★ ★ **为什么要这一层**：参与**类别**只说明「适配器实现是哪一个」，
      **不说明**「它这次真的跑成功了」——
      二进制不在 PATH（exit 127）／人工还没贴回执（``PENDING_MANUAL``）／
      贴进来的文件不存在（``RESULT_FILE_NOT_FOUND``）⇒ **都没跑出回执**。
      ⇒ 若只看类别 ⇒ 答卷与成绩单会自称「有本机 Harness 参与」⇒ **假凭据**。
      ⇒ 正解：**类别 ＋ 跑出回执** 两个条件都满足，才算「这次有模型参与」。
    """
    a = adapter_result or {}
    if str(a.get("status") or "") != OK:
        return False
    raw = str(a.get("raw_text") or "")
    if not raw:
        return False
    return True


def declared_class_of(adapter_id: str) -> str:
    """适配器 **id** → id 级**声明**类别（**旁证，不构成参与主张**）。"""
    return KNOWN_ADAPTER_ID_CLASSES.get(str(adapter_id or "").strip(), UNKNOWN_ADAPTER)


def participation_class_of(adapter: Any) -> str:
    """适配器**对象** → 参与类别（权威判定，按实现类）。

    ★ 这是「模型参与」这件事在**判词层**的判定入口：
      **不看** ``adapter_id``、**不看** ``vendor``、**不看**任何自填字符串
      ⇒ 自填字符串**不可能**把一个非 Harness 适配器变成 ``HARNESS_MODEL``。
    ★ 认不出 ⇒ ``UNKNOWN_ADAPTER``（不猜、不放行）。
    ★ ★ **边界要说清（不是安全边界）**：**进程内**的代码理论上能替换实现
      （monkeypatch ``CodexAdapter.run``、改 ``__class__`` …）⇒ 本判定挡的是
      **「自填字段/自造替身冒充」**这一类，**挡不住**「进程内改实现」。
      ⇒ 真正不可伪造的那一段是**下游只认盖章**（`provenance_source=ADAPTER_IMPLEMENTATION`，
        由实现侧产生并随回执落盘）⇒ 伪造要连**盖章**一起造（那就不是「自填」了）。
    """
    if adapter is None:
        return UNKNOWN_ADAPTER
    cls = ADAPTER_PARTICIPATION_CLASSES.get(type(adapter))
    if cls:
        return cls
    # ★ 子类也不认：宁可判 UNKNOWN，也不要把「长得像」当成「就是」
    return UNKNOWN_ADAPTER
