"""G8：真实模型参与门禁（**独立模块，不改既有评分语义**）。

★ 为什么要这个模块（来自独立 Reviewer 对 PR #9 的首轮 FAIL）：
  文档声称 G8 / 三种运行模式机读字段**已落地**，但冻结实现里**根本没有**：
  冻结证据仓的 `dd_v1_score_service.py` 里 `requested_mode` / `execution_path` /
  `identity_verified` / `NO_REAL_MODEL_RUN_AT_ALL` **一个都没有** ⇒ 文档在制造虚假 PASS。

★ 纪律：**先只加门、不改阈值、不改既有评分**（既有 `score_against_gold` /
  `score_with_classification` 的语义与输出**原样不动**；本模块只**读**考试产物，
  另外给出一个独立的判定结果，由调用方决定怎么用）。

★ 三件事必须**分开记**（不许塌缩成一个布尔）：
  - `requested_mode`：请求的模式（RULE_ONLY / AGENT_REQUIRED / AUTO）；
  - `execution_path`：**实际**走的路径（rule / agent / auto-degraded / unknown）；
  - `identity_verified`：模型身份**是否被 Agent 自己的元数据核实过**（True / False / UNKNOWN）。
  ⇒ 「跑出了回执」≠「这个模型 id 是谁说的、有没有被核实过」。

★ fail-closed 规则：
  1. `requested_mode == AGENT_REQUIRED` 且本场**没有任何真实模型调用** ⇒
     `NO_REAL_MODEL_RUN_AT_ALL`，AI 成绩必须 `NOT_SCORED`（不是 0，也不是规则分）。
  2. `requested_mode == AGENT_REQUIRED` 且实际路径**不是 agent**（降级/未知） ⇒
     `MODE_DOWNGRADED`（或 `NO_REAL_MODEL_RUN_AT_ALL`），AI 成绩 `NOT_SCORED`。
  3. `requested_mode == AGENT_REQUIRED` 且 `identity_verified is not True` ⇒
     `MODEL_IDENTITY_UNVERIFIED`，AI 成绩 `NOT_SCORED`。
  4. `requested_mode == AUTO` 且发生降级 ⇒ 不判 FAIL，但**必须**标记降级，
     且**降级后的结果不得记为 AI 成绩**（`ai_score` = `NOT_SCORED`）。
  5. `requested_mode == RULE_ONLY` ⇒ 不需要真实模型；但**必须**如实标 `execution_path`。

★ **不信任人工填写的布尔**：即使调用方传了 `participated=True`，
  只要产物里 `model_id_or_unknown` 仍是 `UNKNOWN`，`identity_verified` 就必须为 False
  （这正是 Reviewer 反例 B 要堵的塌缩）。

★ 能力边界（必须如实承认）：本门禁只能判断**产物里读得到的事实**
  （有没有真实 adapter 记录、模型 id 是否已核实、是否降级）；
  它**不能**证明「模型真的产生了那段内容」——那需要 adapter 侧的不可伪造证据，
  超出本模块范围。
"""
from __future__ import annotations

from typing import Any, Iterable

SCHEMA_VERSION = "dd_v1_participation_gate.v1"

#: 请求模式（三种，与 Skill 的三种运行模式同名）。
MODE_RULE_ONLY = "RULE_ONLY"
MODE_AGENT_REQUIRED = "AGENT_REQUIRED"
MODE_AUTO = "AUTO"
ALLOWED_REQUESTED_MODES = (MODE_RULE_ONLY, MODE_AGENT_REQUIRED, MODE_AUTO)

#: 实际执行路径。
PATH_RULE = "rule"
PATH_AGENT = "agent"
PATH_AUTO_DEGRADED = "auto-degraded"
PATH_UNKNOWN = "unknown"

#: 失败码（稳定字符串，供报告与回归测试断言）。
GATE_NO_REAL_MODEL_RUN = "NO_REAL_MODEL_RUN_AT_ALL"
GATE_MODE_DOWNGRADED = "MODE_DOWNGRADED"
GATE_MODEL_IDENTITY_UNVERIFIED = "MODEL_IDENTITY_UNVERIFIED"

#: AI 成绩在门禁未过时**必须**取的��（不是 0，也不是规则分）。
AI_NOT_SCORED = "NOT_SCORED"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"

_IDENTITY_UNKNOWN = "UNKNOWN"

#: ★ 身份字段的**权威来源要求**（`ai-auto-exam-gate` 规范 §2.2「模型身份必须走 Agent 自己的
#: 官方元数据」）：
#: 产物里的 `model_id_or_unknown` **必须**由 adapter 从 **Agent 自己的元数据**写入
#: （codex：自己的执行记录 rollout 里的 `turn_context.model`；pi：事件流里的
#: `message_end.message.model`；dsh：配置树的 `agent-default-model`）。
#: ⇒ 本门禁**只认产物里已核实的值**；拿不到 ⇒ `UNKNOWN` ⇒ **过不了身份门禁**
#: （这是设计，不是缺陷）。
#: ⇒ **禁止**用人工在报告/说明字段里手填身份来蒙混过关（⇒ 调用方自报的 True 不能覆盖产物）。
IDENTITY_SOURCE_REQUIREMENT = (
    "identity_verified 只认产物里由 adapter 从 Agent 自己元数据写入的 model_id_or_unknown；"
    "拿不到即 UNKNOWN ⇒ 过不了身份门禁（禁止人工手填身份蒙混）"
)


def _is_real_agent_record(rec: dict[str, Any]) -> bool:
    """判断一条 run record 是否代表**真实 adapter 调用**（而不是规则链产物）。

    判据（只读产物，不接受人工布尔）：
      - 有 `adapter` 段且 `adapter.status == "OK"`；
      - `adapter.raw_text` 非空（真有回执）。
    """
    adapter = rec.get("adapter") or {}
    if not isinstance(adapter, dict):
        return False
    if str(adapter.get("status") or "").upper() != "OK":
        return False
    raw = adapter.get("raw_text")
    return bool(raw and str(raw).strip())


def _degrade_reason(rec: dict[str, Any]) -> str | None:
    """取降级原因（规范 §2.1 要求「必须记录…降级原因」⇒ 不许只记一个布尔）。"""
    validation = rec.get("validation") or {}
    if not isinstance(validation, dict):
        return None
    reason = validation.get("degrade_reason")
    if reason:
        return str(reason)
    if validation.get("uncovered_obligations"):
        uncovered = validation.get("uncovered_obligations")
        try:
            n = len(uncovered)
        except TypeError:
            n = 0
        return "UNCOVERED_OBLIGATIONS:%d" % n
    return None


def _degraded(rec: dict[str, Any]) -> bool:
    return _degrade_reason(rec) is not None


def _model_ids(run_records: Iterable[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for rec in run_records or []:
        validation = rec.get("validation") or {}
        if not isinstance(validation, dict):
            continue
        for bucket in ("accepted", "rejected"):
            for item in validation.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                mid = item.get("model_id_or_unknown")
                ids.append(str(mid) if mid else _IDENTITY_UNKNOWN)
    return ids


def evaluate_participation_gate(run_records: list[dict[str, Any]] | None, *,
                                requested_mode: str = MODE_RULE_ONLY,
                                identity_verified: bool | None = None) -> dict[str, Any]:
    """G8 判定：读**考试产物**，给出模型参与与否的机读结论。

    :param run_records: 本场考试的 run records（只读，不改）
    :param requested_mode: 请求的模式
    :param identity_verified: 调用方**自报**的身份核实结论。
        ★ 它**不能**把身份核实变成 True（只允许把 True 降级为 False）⇒
        防止「人工填一个 participated=True 就蒙混过关」。
    :returns: 机读判定结果
    """
    if requested_mode not in ALLOWED_REQUESTED_MODES:
        raise ValueError("requested_mode 非法：%r（允许：%s）"
                         % (requested_mode, ", ".join(ALLOWED_REQUESTED_MODES)))

    records = [r for r in (run_records or []) if isinstance(r, dict)]
    real_agent_records = [r for r in records if _is_real_agent_record(r)]
    degrade_reasons = [r for r in (_degrade_reason(x) for x in records) if r]
    degraded = bool(degrade_reasons)
    model_ids = _model_ids(records)

    # —— 三个字段分开记 ——
    if not records:
        execution_path = PATH_RULE if requested_mode == MODE_RULE_ONLY else PATH_UNKNOWN
    elif real_agent_records:
        execution_path = PATH_AGENT
    elif requested_mode == MODE_RULE_ONLY:
        execution_path = PATH_RULE
    else:
        execution_path = PATH_UNKNOWN

    ids_unverified = [m for m in model_ids if m.strip().upper() in (_IDENTITY_UNKNOWN, "", "NONE")]
    if identity_verified is True and not ids_unverified and model_ids:
        identity_state: Any = True
    elif ids_unverified or not model_ids:
        identity_state = False if model_ids else _IDENTITY_UNKNOWN
    else:
        identity_state = bool(identity_verified) if identity_verified is not None else False
    # ★ 自报的 True 不能覆盖产物里的 UNKNOWN（上面的分支已保证：ids_unverified ⇒ False）

    failures: list[str] = []
    if requested_mode == MODE_AGENT_REQUIRED:
        if not real_agent_records:
            failures.append(GATE_NO_REAL_MODEL_RUN)
        elif execution_path != PATH_AGENT:
            failures.append(GATE_MODE_DOWNGRADED)
        if real_agent_records and identity_state is not True:
            failures.append(GATE_MODEL_IDENTITY_UNVERIFIED)
    elif requested_mode == MODE_AUTO:
        if degraded or execution_path in (PATH_UNKNOWN,):
            failures.append(GATE_MODE_DOWNGRADED)

    verdict = VERDICT_FAIL if failures else VERDICT_PASS
    ai_score = AI_NOT_SCORED if (requested_mode != MODE_RULE_ONLY and
                                 (failures or execution_path != PATH_AGENT)) else None

    return {
        "schema_version": SCHEMA_VERSION,
        "requested_mode": requested_mode,
        "execution_path": execution_path,
        "identity_verified": identity_state,
        "verdict": verdict,
        "failures": failures,
        "ai_score": ai_score,
        "degraded": degraded,
        "degrade_reason": degrade_reasons,   # ★ 规范 §2.1：必须记录**降级原因**，不许只有布尔
        "evidence": {
            "n_run_records": len(records),
            "n_real_agent_records": len(real_agent_records),
            "model_ids_seen": sorted(set(model_ids)),
            "model_ids_unverified": sorted(set(ids_unverified)),
            "note": "identity_verified 只反映**产物里读得到的事实**；"
                    "调用方自报的 True 不能覆盖产物里的 UNKNOWN。",
            "identity_source_requirement": IDENTITY_SOURCE_REQUIREMENT,
        },
    }
