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

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Budget:
    """预算（复核 N3）。

    - timeout_s：单次调用硬超时，超时杀进程组。
    - max_calls：最多调用次数（含重试）；只有 TIMEOUT / CALL_FAILED 会重试。
    - max_cost_usd：允许的实际费用上限。默认 0 = 不允许任何付费调用（订阅内 cost=0 或 UNKNOWN 放行，
      但 UNKNOWN 会在 run record 标出）。已知 cost > 上限 → BUDGET_EXCEEDED，丢弃输出并降级。
    """
    timeout_s: float = 180.0
    max_calls: int = 1
    max_cost_usd: float = 0.0
    require_known_cost: bool = False  # 付费 Adapter 置 True：费用 UNKNOWN 视为超预算


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
            stdin_text: str | None = None) -> tuple[int | None, str, str, float, bool]:
    """跑一个 CLI：stdin=/dev/null（防止等待输入挂起）或给定文本后立即 EOF，新进程组，超时杀整组。

    返回 (exit_code|None, stdout, stderr, elapsed_s, timed_out)。
    """
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
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
        res.status, res.reason = CALL_FAILED, f"EXIT_{code}:{err.strip()[-200:]}"
    return res


class CodexAdapter:
    adapter_id, vendor, role = "codex-cli", "openai-codex", "EXAMINEE_2"
    # ★ 参与类别由**实现类**决定（不是自填字符串）⇒ 见模块末尾 ADAPTER_PARTICIPATION_CLASSES
    participation_class = "HARNESS_MODEL"

    def __init__(self, binary: str | list[str] = "codex"):
        self.binary = [binary] if isinstance(binary, str) else list(binary)

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
        for stale in ("out.json", "events.jsonl", "stderr.log"):  # 复核 N2：绝不读残留答卷
            (workdir / stale).unlink(missing_ok=True)
        argv = [*self.binary, "exec", "--ephemeral", "--skip-git-repo-check", "-C", str(workdir),
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
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
                res.token_usage_or_UNKNOWN = ev["usage"]
        o = workdir / "out.json"
        res.raw_text = o.read_text("utf-8") if o.exists() else None
        return res


class MiniMaxPiAdapter:
    """AUX（scored=false, ranked=false）。董事长批准替补前不计入考生3。"""
    adapter_id, vendor, role = "pi", "minimax-cn", "AUX"
    participation_class = "HARNESS_MODEL"

    def __init__(self, binary: str | list[str] = "pi", model: str | None = None):
        self.binary = [binary] if isinstance(binary, str) else list(binary)
        self.model = model

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
        for stale in ("events.compact.jsonl", "stderr.log"):
            (workdir / stale).unlink(missing_ok=True)
        argv = [*self.binary, "-p", "--provider", "minimax-cn", "--no-session", "--no-tools", "--mode", "json"]
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
        return res


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
                  dsh_enabled: bool = False) -> Any:
    """按名字建适配器（**薄入口**：CLI 只认这几个名字，不自己拼 argv）。

    - ``codex``  → 本机 ``codex`` CLI（材料不出本机）
    - ``pi``     → 本机 ``pi`` CLI
    - ``dsh``    → 本机 ``dsh``（DeepSeek Harness；**要不要开由操作员自己决定**）
    - ``manual`` → 人工交换（贴回执）
    - ``prebaked``／给了 ``result_path`` → 预置回执（**不是 Harness 运行**）
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
        return CodexAdapter()
    if s in ("pi", "minimax-pi"):
        return MiniMaxPiAdapter()
    if s in ("dsh", "deepseek", "deepseek-harness"):
        return DeepSeekHarnessAdapter(enabled=bool(dsh_enabled))
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


def load_dsh_config(path: Path | None) -> dict[str, Any]:
    """dsh 本地配置（JSON）：binary / profile / extra_args / mode。不允许在配置里写密钥。

    mode="stdin"（默认）：任务包经标准输入传给 `dsh ... -`，命令行里没有任何材料文字——
    Windows 上 .cmd 经 cmd.exe 启动时不会被解释（无注入、无 8191 长度限制），dsh 也不需要读文件权限。
    mode="file"：让 dsh 自己读 workdir/PROMPT.txt（需要 dsh 有读文件能力，不推荐）。
    """
    cfg: dict[str, Any] = {"binary": "dsh", "profile": "headless", "extra_args": [], "mode": "stdin"}
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

    def __init__(self, enabled: bool = False, binary: str | list[str] = "dsh", profile: str = "headless",
                 mode: str = "stdin", role: str = "EXAMINEE_3", extra_args: list[str] | None = None):
        if mode not in ("stdin", "file"):
            raise ValueError(f"BAD_MODE:{mode}")
        self.enabled, self.profile, self.mode, self.role = enabled, profile, mode, role
        self.binary = [binary] if isinstance(binary, str) else list(binary)
        self.extra_args = list(extra_args or [])

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, enabled: bool, role: str = "PRIMARY_LOCAL_DSH") -> "DeepSeekHarnessAdapter":
        return cls(enabled=enabled, binary=cfg["binary"], profile=cfg["profile"], mode=cfg["mode"],
                   role=role, extra_args=cfg["extra_args"])

    def run(self, packet: dict[str, Any], workdir: Path, budget: Budget) -> AdapterResult:
        res = AdapterResult(self.adapter_id, self.vendor, self.role, status=OK, workdir=str(workdir))
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
        code, out, err, el, to = run_cli(argv, workdir, budget.timeout_s, stdin_text=stdin_text)
        res.elapsed_s = el
        out, err = redact_secrets(out), redact_secrets(err)
        (workdir / "answer.txt").write_text(out, "utf-8")
        (workdir / "stderr.log").write_text(err, "utf-8")
        if to or code != 0:
            return _fail(res, code, err, to)
        res.exit_code = 0
        res.raw_text = extract_json_text(out)
        res.cost_usd_or_UNKNOWN = "UNKNOWN(operator dsh account)"
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
    res: AdapterResult = adapter.run(packet, wd, budget)
    attempts.append({"n": 1, "status": res.status, "exit_code": res.exit_code, "elapsed_s": res.elapsed_s})
    while res.status in RETRYABLE and len(attempts) < budget.max_calls:  # 复核 N3：max_calls 真正生效
        res = adapter.run(packet, wd, budget)
        attempts.append({"n": len(attempts) + 1, "status": res.status, "exit_code": res.exit_code,
                         "elapsed_s": res.elapsed_s})
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
        "budget": asdict(budget), "calls_used": len(attempts), "attempts": attempts,
        "adapter": res.to_dict(), "validation": rep.to_dict(),
    }
    (wd / "run_record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


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

UNKNOWN_ADAPTER = "UNKNOWN_ADAPTER"

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
