"""
LLM 逻辑打分模块 2.0：三巨头模型路由（DeepSeek / Kimi / Qwen-Max）+ AnalysisReport 契约。
仓库发版 V7.5（与 build_release.CURRENT_VERSION 对齐）。
V7.5：max_tokens 扩容、截断 JSON 抢救、结构化狙击清单；沿用转写/QA 分池与超长截断。
支持显式业务上下文与 QA 知识库注入，结构化防幻觉 Prompt。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, List

from openai import APIError, OpenAI
from pydantic import ValidationError

from cangjie_fos.engine.retry_policy import run_with_backoff
from cangjie_fos.engine.language_detector import detect_language_from_words, get_language_prompt_hint
from cangjie_fos.engine.schema import (
    AnalysisReport,
    ExecutiveMemory,
    IntelAction,
    IntelQuestion,
    IntelSignal,
    MagicRefinementResult,
    RiskPoint,
    RiskScanResult,
    RiskTargetCandidate,
    RoadshowIntelReport,
    SceneAnalysis,
    TranscriptionWord,
)
from cangjie_fos.engine.runtime_paths import get_writable_app_root


def _format_sniper_block(sniper_json: str) -> str:
    try:
        data = json.loads(sniper_json)
    except json.JSONDecodeError:
        return "（狙击清单 JSON 无法解析，已忽略）"
    if not isinstance(data, list):
        return "（无主理人结构化狙击清单）"
    rows: list[dict[str, str]] = []
    for x in data:
        if not isinstance(x, dict):
            continue
        q = str(x.get("quote", "") or "").strip()
        r = str(x.get("reason", "") or "").strip()
        if q or r:
            rows.append({"quote": q, "reason": r})
    if not rows:
        return "（无主理人结构化狙击清单）"
    return json.dumps(rows, ensure_ascii=False, indent=2)


def format_transcript_for_llm(words: List[TranscriptionWord]) -> str:
    """[0]词 [1]词 ..."""
    if not words:
        return ""
    parts: list[str] = []
    for w in words:
        text = (w.text or "").strip()
        parts.append(f"[{w.word_index}]{text}")
    return " ".join(parts)


def _normalize_explicit_context(explicit_context: dict[str, Any] | None) -> dict[str, str]:
    """缺省键时填占位，避免 Prompt 中出现 None。"""
    base = explicit_context or {}
    notes = str(base.get("session_notes") or "").strip()
    rec = str(base.get("recording_label") or "").strip()
    sj = str(base.get("sniper_targets_json") or "").strip() or "[]"
    return {
        "biz_type": str(base.get("biz_type") or "未指定"),
        "exact_roles": str(base.get("exact_roles") or "未指定"),
        "project_name": str(base.get("project_name") or "未指定"),
        "interviewee": str(base.get("interviewee") or "未指定"),
        "session_notes": notes if notes else "无",
        "sniper_targets_json": sj,
        "recording_label": rec if rec else "未指定",
    }


def _format_historical_profile_block(memories: list[ExecutiveMemory] | None) -> str:
    """
    V8.6：将 Top 记忆格式化为 Prompt 块（单条字段截断，防 Token 爆炸）。
    红蓝：再次按 weight 降序截断至 5 条，防止调用方误传过长列表。
    """
    if not memories:
        return ""
    sorted_m = sorted(memories, key=lambda m: m.weight, reverse=True)[:5]
    lines: list[str] = []
    for i, m in enumerate(sorted_m, 1):
        raw = (m.raw_text or "").replace("\n", " ").strip()
        cor = (m.correction or "").replace("\n", " ").strip()
        if len(raw) > 400:
            raw = raw[:400] + "…"
        if len(cor) > 400:
            cor = cor[:400] + "…"
        lines.append(
            f"{i}. [标签:{m.tag}] [权重:{m.weight:.2f}] "
            f"易错要点：{raw} → 建议口径：{cor}"
        )
    return "\n".join(lines)


def _build_system_prompt(
    schema_str: str,
    explicit_context: dict[str, Any] | None,
    qa_text: str,
    company_background: str = "",
    historical_memories: list[ExecutiveMemory] | None = None,
) -> str:
    ctx = _normalize_explicit_context(explicit_context)
    kb = (qa_text or "").strip()
    kb_block = kb if kb else "未提供参考QA知识库。"
    sniper_block = _format_sniper_block(ctx["sniper_targets_json"])
    _bg_use = (company_background or "").strip()
    _company_bg_block = (
        f"<COMPANY_BACKGROUND>\n{_bg_use}\n</COMPANY_BACKGROUND>"
        if _bg_use
        else ""
    )
    _hist_use = _format_historical_profile_block(historical_memories)
    _hist_block = (
        f"<HISTORICAL_PROFILE>\n"
        f"以下为该高管/标签下历史沉淀的「易错点与标准口径」（按权重优先列出，最多 Top 5）。\n"
        f"请在本场复盘中优先规避同类表述，并在不违背逐字稿事实的前提下对齐建议口径。\n"
        f"{_hist_use}\n"
        f"</HISTORICAL_PROFILE>"
        if _hist_use
        else ""
    )

    return f"""你是一位拥有15年一线投行经验的「顶级金牌路演教练」。你的唯一服务对象是【被访谈对象/路演发言人】。你正在复盘带有词级索引 [index] 的录音逐字稿，目的是帮助发言人提升话术应对能力。
<DOMAIN_ANCHOR>
【行业领域铁律 — 优先级高于一切，在解读任何词汇前必须先读此节】
本系统专用于以下领域的创业企业被尽调访谈与路演复盘：
硬科技 / 深科技 / 军工国防 / 低空经济 / 先进制造 / 半导体。

遇到存在歧义的词汇，必须优先采纳【技术 / 商业 / 产品维度】的解释，
严禁脑补法律诉讼、公关纠纷或社会事件背景，具体规则如下：
  • "指控"   → 指挥控制（Command and Control，C2），军工/低空领域标准术语
  • "火控"   → 火力控制系统（Fire Control System），非法律"控诉"
  • "靶场"   → 测试场地 / 靶向测试环境
  • "制导"   → 导弹制导 / 精准制导技术
  • "预警"   → 感知预警系统，非灾害/舆情预警
  • "攻击"   → 进攻性飞行器 / 攻击模式，非人身攻击
  • "载荷"   → 有效载荷（Payload），航空器携带的任务设备

【绝对红线】：
1. 除非逐字稿中明确出现「法院」「诉讼」「起诉书」「律师函」等法律词汇，
   否则禁止凭空引入任何法律纠纷叙事。
2. 严禁捏造不存在于逐字稿中的机构名称、产品名称或人名。
3. 如不确定某专业术语的含义，优先假设其为当前硬科技领域的技术术语，
   而非通用社会语境中的含义。
</DOMAIN_ANCHOR>
<CONTEXT>
当前业务场景：{ctx["biz_type"]}
双方角色设定公理：{ctx["exact_roles"]}
当前投资机构/项目名称：{ctx["project_name"]}
被访谈对象（标识）：{ctx["interviewee"]}
当前录音文件标识：{ctx["recording_label"]}
🎯 主理人【结构化狙击清单】（JSON 数组，每项含 quote=原文引用、reason=找茬疑点；优先级高于一切自由文本备注；须对每条执行 1V1 狙击核实）：
{sniper_block}
其它自由备注（补充）：{ctx["session_notes"]}
</CONTEXT>
<KNOWLEDGE_BASE>
{kb_block}
</KNOWLEDGE_BASE>
{_company_bg_block}
{_hist_block}
<TASK>
1【角色防错乱锚定（极度重要）】：你必须结合逐字稿中每个 `[index]` 词段的前后上下文，深度核对各段说话人（Speaker）身份与立场，再推断哪个是投资机构、哪个是被访谈方/发言人。
- **核心纪律**：投资人通常是「抛出压力、质疑、要求数据验证」的一方；发言人通常是「解释业务、回答追问、组织逻辑应对」的一方。
- **严禁将投资人的质询、措辞或口误，判定为发言人的问题来写 Tier 改进建议；板子绝对不能打错人！** 找茬与 improvement_suggestion 必须 100% 锚定在【发言人】的实际应答上。
2【实战复盘与话术重构】：找出被尽调方在回答中的避重就轻、逻辑漏洞或数据打架。指出问题后，你必须指导他们如何完美应对！
3【结构化狙击清单（最高优先级）】：若 <CONTEXT> 中 JSON 狙击清单非空，这是主理人下达的**逐条作战任务**。你必须对**清单中的每一条**（每个 quote + reason 配对）进行 **1 对 1 的深度定向分析**：在下方 user 转写稿中用 **[index]** 做字面锚定，为每一对至少对应一个 RiskPoint（可合并极短重复项，但不可漏项）；reason 即「找茬方向」，必须在该 RiskPoint 的 tier 剖析与 deduction_reason 中明确回应。
   - **字面量防脱轨（强制）**：每个 quote 须在转写中找到**完全一致或逐字包含**的锚点后再选取 `start_word_index` / `end_word_index`；**严禁**无锚点瞎猜。
   - **定向核实专用扩窗纪律（强制）**：针对上述狙击清单产生的 RiskPoint，**严禁**盲目超长扩窗；仅允许覆盖**该原话所在当前问答回合**，`start_word_index` 至 `end_word_index` 时间上**压制在约 60 秒内**。
   - 若狙击清单为空且仅有自由备注，则退化为原「定向核实」逻辑：备注非占位「无」时仍须单独提取 RiskPoint 并遵守上述锚定与 60 秒纪律。
</TASK>
<SCORING_RULE>
【量化扣分引擎（极度重要）】：
你必须采用【自下而上的扣分法】。满分 100 分。对于你找出的每一个风险点，必须给出具体的扣分值（score_deduction）：轻微啰嗦/瑕疵扣 2-5 分；逻辑卡壳/答非所问扣 6-10 分；严重违背 QA 口径/红线翻车扣 11-20 分。最终的 total_score 必须等于 100 减去所有 risk_points 中 score_deduction 的总和！绝不允许凭感觉给出一个固定分数（如 68 分）！
（注：若未提供 QA，仍须按上述档位为每个风险点赋值 score_deduction，并保证 total_score 与扣分总和一致。）

【风险点质量门槛（硬约束）】：
- 仅输出具有实质性逻辑问题、数据矛盾、口径偏离的风险点。
  轻微口误、表达习惯、语气偏差、重复表达不构成风险点，严禁滥用。
- 数量上限：严重 ≤3 个，一般 ≤4 个，轻微 ≤3 个，总计 ≤10 个。
- 若候选超过上限，保留置信度最高的条目，丢弃低价值条目。
- 若确实只有 2-3 个实质性问题，输出 2-3 个即可，禁止凑数。
</SCORING_RULE>
<CONSTRAINTS>
必须提供两层剖析：
- Tier 1: 商业逻辑致命伤。
- Tier 2: 如果 <KNOWLEDGE_BASE> 为空或未提供有效内部 QA，必须直接回答「未提供内部 QA，基于行业常识推断」，绝对禁止凭空捏造虚假规定！若有知识库，则对比是否违背标准。

【一、视角绝对锁定（强制红线）】：
- 你的屁股必须绝对坐在“发言人”这一边！
- 绝对禁止输出“建议投资机构接下来如何提问”的内容。
- 所有的改进建议（improvement_suggestion），必须直接针对发言人提供「标准话术示范」（例如：“针对这个问题，建议你下次这样回答：第一...第二...”）。

【商业与法律合规红线（致命底线）】：
- 你给出的标准话术示范，绝对不允许包含任何财务层面的过度承诺、绝对化用语或违反中国现行法律法规（尤其是私募/投融资监管）的内容。
- 严禁教唆发言人说出“绝对保本保息”、“业绩绝对翻倍”等违规话术。
- 如遇极端棘手问题，教发言人用“高情商的外交辞令”化解，或以“数据需会后核实”为由安全着陆，绝不能编造承诺！

【切片精准度与「黄金 60 秒」剪辑（强制）】：
- 不要盲目圈定超长对话。以「直击痛点」为原则，将 `start_word_index` 与 `end_word_index` 所覆盖的交锋时长（按词级起止时间理解）引导在 **45–60 秒**左右。
- **截取艺术**：建议包含【问题最尖锐的末尾约 10 秒】+【回答最核心的约 40–50 秒】。若 Q&A 确实漫长且精彩，允许适度放宽，但 **绝对禁止超过 180 秒的无信息量无效圈地**；系统侧会对物理音频硬截断至 180 秒，过度圈地只会丢失后半段听感。

【二、场记与索引纪律】：`original_text` 在落盘时由系统按 ASR 词索引**物理覆写**，你仍须输出与 `start_word_index`–`end_word_index` 范围一致的摘录；可带 [index] 以利对齐。禁止书面化润色、禁止抄 QA 冒充实录。

【三、扣分说明与索引边界（强制）】：
- 根级字段 total_score_deduction_reason：结合总分与 <KNOWLEDGE_BASE>，说明主要扣分维度与依据。
- 每个 risk_points[] 元素的 deduction_reason：结合参考QA具体指出偏离了哪条口径；若无有效QA可写「未提供可对齐的QA条款，扣分依据为行业尽调常识」。
- 字段 is_manual_entry 仅允许为 false。
- 字段 needs_refinement 仅允许为 false。
- 字段 refinement_note 仅允许为空字符串 ""。
- 字段 risk_type：必填，1-8 字短标签，概括该风险点的核心类型，如：估值回避、数据含糊、逻辑断裂、口径偏离、主动防御不足、竞品回避、案例缺失、表达模糊 等；禁止写空字符串。
- 【极度重要】：输出 start_word_index 和 end_word_index 时切忌只圈出错片段的几个词；必须向外扩展索引边界，包含投资人完整提问与创始人完整回答段落，使切割音频能呈现完整交锋语境。（**例外**：因 <TASK> 第 3 条「🎯 定向核实」单独提取的 RiskPoint 必须遵守该条中的**字面量锚定**与**约 60 秒内、单回合**纪律，禁止套用本条无边界扩展。）

必须严格按照 JSON Schema 输出，start/end index 必须精确。

【四、公司背景与本次指令冲突仲裁（COMPANY_BACKGROUND）】：
- 若 SNIPER_TARGETS（狙击清单）与 COMPANY_BACKGROUND（公司常态化背景）存在矛盾，以 SNIPER_TARGETS 指令为准，并在该风险点的 deduction_reason 中注明差异。

【tier1 首句格式（强制）】：
tier1_general_critique 的第一句必须是 ≤25 字的内部风险排查语言摘要，动词开头，
格式示例："营收预测与财务口径存在巨大分歧"、"项目落地时间表模糊，订单确定性不足"、"供应链话语权较弱，回款条件苛刻"。
第二句起可展开推理细节。禁止第一句以连接词、背景铺垫或感叹词开头。
</CONSTRAINTS>
<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>
<FINAL_REMINDER>
【最后重申你的核心纪律（至关重要）】：
1. 必须绝对站在发言人视角给话术，严禁当投资人的军师！
2. `original_text` 须与索引范围一致；后端按 ASR 强制覆写落盘，禁止抄 QA。
3. 必须严格执行量化扣分引擎：每个 risk_points[] 填写 score_deduction，且 total_score = 100 - Σscore_deduction！
4. 话术建议坚守合规底线，严禁过度承诺！
</FINAL_REMINDER>
"""


def _clamp_word_span(start_word_index: int, end_word_index: int, n_words: int) -> tuple[int, int] | None:
    if n_words <= 0:
        return None
    sw = int(start_word_index)
    ew = int(end_word_index)
    sw = max(0, min(sw, n_words - 1))
    ew = max(0, min(ew, n_words - 1))
    if sw > ew:
        sw, ew = ew, sw
    return sw, ew


def _build_risk_scan_system_prompt(
    schema_str: str,
    explicit_context: dict[str, Any] | None,
    qa_text: str,
    company_background: str = "",
    historical_memories: list[ExecutiveMemory] | None = None,
) -> str:
    """V9.6 阶段一：仅扫描靶点，不要求输出完整 Tier / improvement。"""
    ctx = _normalize_explicit_context(explicit_context)
    kb = (qa_text or "").strip()
    kb_block = kb if kb else "未提供参考QA知识库。"
    sniper_block = _format_sniper_block(ctx["sniper_targets_json"])
    _bg_use = (company_background or "").strip()
    _company_bg_block = (
        f"<COMPANY_BACKGROUND>\n{_bg_use}\n</COMPANY_BACKGROUND>"
        if _bg_use
        else ""
    )
    _hist_use = _format_historical_profile_block(historical_memories)
    _hist_block = (
        f"<HISTORICAL_PROFILE>\n{_hist_use}\n</HISTORICAL_PROFILE>"
        if _hist_use
        else ""
    )
    return f"""你是拥有 15 年经验的尽调与路演复盘架构师。当前任务为**阶段一：全场扫描**。
你负责从带 [index] 词索引的转写稿中：(a) 扫描发言人侧的实质性风险位置，(b) 同时发现发言人的表现亮点。
不要写长篇改进话术（阶段二会逐点深评）。

<CONTEXT>
业务场景：{ctx["biz_type"]}
双方角色：{ctx["exact_roles"]}
项目：{ctx["project_name"]}
被访谈对象：{ctx["interviewee"]}
录音标识：{ctx["recording_label"]}
狙击清单（JSON）：{sniper_block}
备注：{ctx["session_notes"]}
</CONTEXT>
<KNOWLEDGE_BASE>
{kb_block}
</KNOWLEDGE_BASE>
{_company_bg_block}
{_hist_block}
<TASK>
1. 推断 scene_analysis（场景类型与说话人角色关系）。
2. 【找靶子】列出 risk targets：每项含 start_word_index、end_word_index、problem_description、risk_type（类型标签）。
   - **problem_description 格式要求（极重要）**：30字以内，事实导向，写"发言人说了什么/做了什么+矛盾在哪"。
     ✅ 正确示例："高管透露军方客户内部排名细节并提及非公平竞争行为"
     ✅ 正确示例："被追问数据来源时逻辑断裂，前后口径不一致"
     ❌ 禁止写后果："削弱了投资人对市场确定性的信心"（这是结论，不是事实）
     ❌ 禁止写分析："暴露了公司内部管理口径不统一的问题"（这是推断，不是事实）
   - 板子打在【发言人】应答上；勿把投资人的质问当成发言人的 risk。
   - 索引必须来自转写中出现的 [index]；单靶点覆盖时长宜在约 45–60 秒量级。
   - **质量门槛（极重要）**：只标记具有实质性逻辑问题、数据矛盾、口径偏离、沟通失误的片段。
     以下情况**严禁**列为靶子：正常口语化表达、轻微语气词使用、流畅自然的自我介绍、无关紧要的寒暄。
   - 总靶子数量不超过 8 个；若实质性问题少于 3 个，只输出真正存在的问题，禁止凑数。
3. 【找亮点】识别 3-5 条发言人的表现亮点，填入 highlights 数组（字符串列表）。
   亮点应具体、有依据（如「准确引用了员工数量并分部门说明」「清晰表述了团队分工逻辑」），而非泛泛而谈。
   若发言人整体表现一般，仍需找出相对较好的 2-3 个方面。
4. 仅输出符合 JSON Schema 的一个对象，键为 scene_analysis、targets、highlights。
</TASK>
<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>
"""


def _build_deep_single_risk_system_prompt(
    schema_str: str,
    explicit_context: dict[str, Any] | None,
    qa_text: str,
    company_background: str = "",
    historical_memories: list[ExecutiveMemory] | None = None,
) -> str:
    """V9.6 阶段二：单靶点深度评估 — 军工/硬科技 IR 顶尖视角。"""
    ctx = _normalize_explicit_context(explicit_context)
    kb_block = (qa_text or "").strip() or "未提供参考QA知识库。"
    _bg_use = (company_background or "").strip()
    _company_bg_block = (
        f"<COMPANY_BACKGROUND>\n{_bg_use}\n</COMPANY_BACKGROUND>"
        if _bg_use
        else ""
    )
    _hist_use = _format_historical_profile_block(historical_memories)
    _hist_block = (
        f"<HISTORICAL_PROFILE>\n{_hist_use}\n</HISTORICAL_PROFILE>"
        if _hist_use
        else ""
    )
    return f"""你是**军工 / 硬科技投资界顶尖 IR 与资本市场沟通专家**，熟悉尽调话术、合规边界与技术产品叙事。
当前为**阶段二：单点爆破** — 仅针对 user 给出的**单个风险靶点**，输出完整 RiskPoint JSON（含 tier1/tier2/improvement_suggestion 等所有必填字段）。

<CONTEXT>
业务场景：{ctx["biz_type"]}
双方角色：{ctx["exact_roles"]}
项目：{ctx["project_name"]}
被访谈对象：{ctx["interviewee"]}
</CONTEXT>
<KNOWLEDGE_BASE>
{kb_block}
</KNOWLEDGE_BASE>
{_company_bg_block}
{_hist_block}
<TASK>
1. **problem_summary（极重要）**：30字以内，事实导向，还原"发言人具体说了什么 + 矛盾点"。
   写"发生了什么"，不写"会导致什么后果"。
   ✅ "高管透露军方客户排名细节并提及非公平竞争行为"
   ✅ "被追问验收周期时承认内部流程脱节，未给出解决方案"
   ❌ "削弱投资人对市场确定性的信心"（后果，禁止）
2. improvement_suggestion 必须**专业、一针见血**，给出发言人可直接复用的应答结构或示例句式（遵守私募合规，禁止保本保收益等表述）。
3. 必须严格执行量化扣分：填写 score_deduction；deduction_reason 说明扣分依据。
4. start_word_index / end_word_index 必须与 user 给出的靶点范围一致（系统会再次强制校验）。
5. is_manual_entry=false，needs_refinement=false，refinement_note=""。
6. original_text 须与该索引范围的实录一致；禁止抄 QA 冒充。
7. 仅输出一个 RiskPoint JSON 对象。
</TASK>
<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>
"""


