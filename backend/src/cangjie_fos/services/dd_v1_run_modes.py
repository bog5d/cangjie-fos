"""三种运行模式（DD-V1 施工令 V3.0 · P1 / §6）。

★ ★ **为什么不是一个新框架**：本仓**已经有**一套「参与类别 ＋ 回执口径」的判定
  （``dd_v1_exam_service`` 里的 ``examinee.mode`` / ``participated`` /
  ``participated_scope``）。本模块**只做三件事**：

1. 把「**请求的模式**」显式化（RULE_ONLY / AGENT_REQUIRED / AUTO）；
2. 由既有字段**派生**「**实际执行路径**」（规则 / 真模型 / 模拟模型 / 降级 / 失败）；
3. 把「**这份成绩算什么**」定死（``RULE_BASELINE_SCORE`` / ``AI_SYSTEM_SCORE`` /
   ``NOT_SCORED``）—— ★ **规则链跑出来的分，绝不允许被当成 AI 的分**。

⇒ **不新建平行执行框架**：底层还是那套适配器 ＋ 那套参与类别判定。

────────── 三个模式（施工令 §6 原文口径） ──────────

``RULE_ONLY``
    规则基线测试。**只**用确定性规则完成识别/匹配/审核/组包。允许正常评分，
    但**成绩名称必须是** ``RULE_BASELINE_SCORE``；**不得宣称 AI 模型参与**。

``AGENT_REQUIRED``
    正式 AI 能力考试。**必须**真实调用指定 Agent。
    模型未参与 ⇒ ①考试状态 FAIL ②模型成绩 ``NOT_SCORED``
    ③**不允许**自动降级为规则考试并继续宣称 AI 成功 ④保留错误与诊断证据。
    模型参与但**模型身份无法核实** ⇒ 标记 ``MODEL_ID_UNKNOWN``，
    **不得**通过「模型身份」验收门禁。

``AUTO``
    日常生产或非正式测试。可按策略选 Agent 或规则链，但**必须记录**：
    请求的模式 / 实际执行模式 / 是否降级 / 降级原因 / 实际参与模型 / 结果来源。
    ⇒ AUTO 降级到规则后**可以**继续完成符合安全策略的规则工作，
      但**不得**把结果记为有效 AI 考试成绩。

────────── 命名（全部显式，不留歧义） ──────────

执行路径 ``EXEC_PATH``：
    ``REAL_MODEL``   真模型参与（身份核实过）
    ``MODEL_ID_UNKNOWN`` 真模型参与，但**身份核实不出来**
    ``MOCK_MODEL``   模拟/预置回执（**不是**真模型）
    ``RULE_ONLY``    纯规则
    ``DEGRADED``     请求了 Agent 但**降级**到规则
    ``FAILED``       AGENT_REQUIRED 且模型没参与 ⇒ **考试失败**

成绩名称 ``SCORE_NAME``：
    ``RULE_BASELINE_SCORE`` / ``AI_SYSTEM_SCORE`` / ``NOT_SCORED``
"""
from __future__ import annotations

from typing import Any

# ── 请求的模式 ───────────────────────────────────────────────────────────────
MODE_RULE_ONLY = "RULE_ONLY"
MODE_AGENT_REQUIRED = "AGENT_REQUIRED"
MODE_AUTO = "AUTO"
RUN_MODES = (MODE_RULE_ONLY, MODE_AGENT_REQUIRED, MODE_AUTO)

# ── 实际执行路径 ─────────────────────────────────────────────────────────────
EXEC_PATH_REAL_MODEL = "REAL_MODEL"
EXEC_PATH_MODEL_ID_UNKNOWN = "MODEL_ID_UNKNOWN"
EXEC_PATH_MOCK_MODEL = "MOCK_MODEL"
EXEC_PATH_RULE_ONLY = "RULE_ONLY"
EXEC_PATH_DEGRADED = "DEGRADED"
EXEC_PATH_FAILED = "FAILED"

# ── 成绩名称 ─────────────────────────────────────────────────────────────────
SCORE_NAME_RULE_BASELINE = "RULE_BASELINE_SCORE"
SCORE_NAME_AI_SYSTEM = "AI_SYSTEM_SCORE"
SCORE_NAME_NOT_SCORED = "NOT_SCORED"

#: 模型身份不可核实时的标记（施工令 §6 AGENT_REQUIRED 明文）
MODEL_ID_UNKNOWN = "MODEL_ID_UNKNOWN"

#: 模拟模型（预置回执）的参与类别 —— **不是**真模型
MOCK_PROVENANCE_CLASSES = ("PREBAKED_RESULT",)


def normalize_mode(mode: str | None) -> str:
    """把用户写的模式名归一到三个合法值（**不认识 ⇒ 报错**，不静默兜底）。"""
    m = str(mode or "").strip().upper().replace("-", "_")
    if not m:
        return MODE_RULE_ONLY
    if m in ("RULE_ONLY", "RULE", "NONE"):
        return MODE_RULE_ONLY
    if m in ("AGENT_REQUIRED", "AGENT", "REQUIRED"):
        return MODE_AGENT_REQUIRED
    if m == "AUTO":
        return MODE_AUTO
    raise ValueError(f"UNKNOWN_RUN_MODE:{mode}")


def derive_execution_path(*, requested_mode: str | None,
                          examinee_mode: str | None,
                          participated: bool,
                          provenance_class: str | None = None,
                          model_identity_verified: bool = False,
                          degrade_reason: str | None = None) -> str:
    """由**既有**参与判定派生「实际执行路径」。

    ★ 输入全部来自既有字段（``examinee.mode`` / ``participated`` / 参与类别）
      ⇒ **不新建平行判定**，避免「两套参与口径打架」。
    """
    req = normalize_mode(requested_mode)
    em = str(examinee_mode or "UNKNOWN")
    pclass = str(provenance_class or "")
    real_participated = bool(participated) and em == "HARNESS_MODEL"

    if req == MODE_AGENT_REQUIRED:
        if not real_participated:
            # ★ AGENT_REQUIRED 且模型没参与 ⇒ **失败**（**不是**降级）
            return EXEC_PATH_FAILED
        return EXEC_PATH_REAL_MODEL if model_identity_verified else EXEC_PATH_MODEL_ID_UNKNOWN

    if req == MODE_AUTO:
        if real_participated:
            return EXEC_PATH_REAL_MODEL if model_identity_verified else EXEC_PATH_MODEL_ID_UNKNOWN
        if pclass in MOCK_PROVENANCE_CLASSES and participated:
            return EXEC_PATH_MOCK_MODEL
        # AUTO 降级到规则 ⇒ 如实记 DEGRADED（**不冒充 AI**）
        return EXEC_PATH_DEGRADED if degrade_reason or em == "RULE_ONLY" else EXEC_PATH_RULE_ONLY

    # RULE_ONLY
    if pclass in MOCK_PROVENANCE_CLASSES and participated:
        return EXEC_PATH_MOCK_MODEL
    return EXEC_PATH_RULE_ONLY


def score_name_for(execution_path: str) -> str:
    """执行路径 ⇒ **成绩名称**（三选一，没有第四种）。

    ★ 这是「规则基线与 AI 成绩分离」的**唯一权威入口**：
      成绩单里的一切分数都必须能说清「这是规则基线分，还是 AI 系统分」。

    映射（逐条对应施工令 §6）：

    - ``REAL_MODEL`` / ``MODEL_ID_UNKNOWN`` ⇒ ``AI_SYSTEM_SCORE``
      （两者**模型确实参与了**；后者只是**身份核实不出来** ⇒ 仍算 AI 分，
       但**过不了**「模型身份」门禁 —— 这是两件事，不能混）
    - ``RULE_ONLY`` / ``DEGRADED`` ⇒ ``RULE_BASELINE_SCORE``
      （§6 模式一：RULE_ONLY 的成绩名称**必须**是它；
       AUTO 降级后做的**仍然是规则工作** ⇒ 同样归规则基线列）
    - ``MOCK_MODEL`` / ``FAILED`` ⇒ ``NOT_SCORED``
      （模拟回执既不是规则基线也不是有效 AI 分；AGENT_REQUIRED 失败则压根没有 AI 成绩）
    """
    p = str(execution_path or "")
    if p in (EXEC_PATH_REAL_MODEL, EXEC_PATH_MODEL_ID_UNKNOWN):
        return SCORE_NAME_AI_SYSTEM
    if p in (EXEC_PATH_RULE_ONLY, EXEC_PATH_DEGRADED):
        return SCORE_NAME_RULE_BASELINE
    return SCORE_NAME_NOT_SCORED


def is_ai_score_valid(execution_path: str) -> bool:
    """这份成绩**能不能**被当作「AI 成绩」用？"""
    return score_name_for(execution_path) == SCORE_NAME_AI_SYSTEM


def is_model_identity_acceptable(execution_path: str) -> bool:
    """模型**身份**能不能过「模型身份」验收门禁？

    ★ ``MODEL_ID_UNKNOWN`` ⇒ 模型确实参与了，但**身份核实不出来**
      ⇒ 施工令 §6 明文：**不得**通过模型身份门禁。
    """
    return str(execution_path or "") == EXEC_PATH_REAL_MODEL


def split_scores(total_score: float | None, *, execution_path: str,
                 rule_baseline_score: float | None = None) -> dict[str, Any]:
    """把一个总分**劈成两列**：规则基线分 与 AI 系统分。

    ★ 施工令 §8 要求的对比口径：
      - ``rule_baseline_score`` ＝ 规则链跑出来的分
      - ``ai_system_score``     ＝ 真模型参与时的分；**模型缺席 ⇒ NOT_SCORED**
      - ``delta``               ＝ 两列差值（**观察值，不是因果归因**）
    ★ ★ **差值不等于模型带来的因果贡献** —— 两次运行的环境/时序都可能不同
      ⇒ 这里只给数，**不给因果结论**。
    """
    name = score_name_for(execution_path)
    ai_value: float | None = None
    rb_value: float | None = rule_baseline_score
    if name == SCORE_NAME_AI_SYSTEM:
        ai_value = total_score
    elif name == SCORE_NAME_RULE_BASELINE:
        # 本次就是规则基线运行 ⇒ 本列取本次分（外部传入的基线分优先）
        rb_value = rule_baseline_score if rule_baseline_score is not None else total_score
    else:
        ai_value = None
        rb_value = rule_baseline_score
    delta = None
    if isinstance(ai_value, (int, float)) and isinstance(rb_value, (int, float)):
        delta = round(float(ai_value) - float(rb_value), 2)
    return {
        "score_name": name,
        "rule_baseline_score": rb_value,
        "ai_system_score": ai_value,
        "ai_system_score_status": "SCORED" if ai_value is not None else SCORE_NAME_NOT_SCORED,
        "model_identity_acceptable": is_model_identity_acceptable(execution_path),
        "delta": delta,
        "delta_is_causal": False,
        "delta_note": ("★ 差值**只是观察值**：两次运行（规则基线 / 模型参与）"
                       "不是受控对照实验，**不能**当作「模型带来的因果贡献」。"
                       "要做归因须走错误分类与消融测试。"),
    }


def exam_status_for(execution_path: str, base_status: str) -> str:
    """执行路径 ⇒ 考试状态。

    ★ AGENT_REQUIRED 且模型没参与 ⇒ **FAIL**（覆盖底层的 SCORED / LOW_CONFIDENCE / …）
    ⇒ 施工令 §6：「考试状态 FAIL；模型成绩 NOT_SCORED」。
    """
    if str(execution_path) == EXEC_PATH_FAILED:
        return "FAIL"
    return str(base_status or "")
