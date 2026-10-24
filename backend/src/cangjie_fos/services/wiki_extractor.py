"""LLM 驱动的知识实体提炼引擎（Karpathy LLM Wiki 模式）。

对每份新文档（路演转写、尽调邮件、会议纪要），在摄入时（ingest-time）
而非查询时（query-time）提炼知识，写入 wiki_entities/wiki_links。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

# 合法实体类型集合
ENTITY_TYPES: frozenset[str] = frozenset(
    {"institution", "technology", "risk", "person", "concept", "event"}
)

_MIN_TEXT_LEN = 20  # 低于此字符数直接跳过，不调 LLM

_SYSTEM_PROMPT = """
你是一个专门从融资相关文档中提取结构化知识的 AI 助手。

当你收到一段文本（路演对话转写、会议纪要、尽调邮件等），你需要：

1. 识别所有重要实体，类型只能是：
   - institution（投资机构/VC/基金）
   - technology（核心技术/产品/创新）
   - risk（风险项/担忧/待解决问题）
   - person（关键人员）
   - concept（业务概念/市场/策略）
   - event（重要事件/里程碑）

2. 对每个实体，提炼：
   - new_facts: 本文档新发现的事实列表（字符串数组，若无则 []）
   - current_status: 该实体的当前状态（一句话，若不明确则 ""）
   - timeline_event: 本文档涉及的时间线事件（{date, event}，若无明确时间则 null）

3. 识别实体间的关系（relationship 只能是以下之一）：
   concerned_about / interested_in / requires / related_to / mentions

只提取文档中有明确依据的信息。不推断、不臆测。

严格返回如下 JSON 格式（不要包含任何 markdown 代码块标记）：
{
  "entities": [
    {
      "name": "规范化实体名称",
      "type": "institution|technology|risk|person|concept|event",
      "new_facts": ["事实1", "事实2"],
      "current_status": "当前状态",
      "timeline_event": {"date": "YYYY-MM-DD", "event": "事件描述"} 或 null
    }
  ],
  "relationships": [
    {
      "source": "实体A名称",
      "target": "实体B名称",
      "relationship": "concerned_about|interested_in|requires|related_to|mentions",
      "context": "一句话说明依据"
    }
  ]
}
""".strip()


def _make_client(model_key: str = "deepseek") -> tuple[OpenAI, str]:
    """创建 OpenAI 兼容客户端，使用 ROUTER 配置（不硬编码 key）。"""
    from cangjie_fos.engine.coach.llm_judge import ROUTER  # 延迟导入避免循环
    cfg = ROUTER.get(model_key, ROUTER["deepseek"])
    client = OpenAI(
        api_key=os.environ.get(cfg["api_key_env"], "placeholder"),
        base_url=cfg["base_url"],
    )
    return client, cfg["model"]


def parse_extraction_response(raw: str) -> dict[str, Any]:
    """解析 LLM 返回的 JSON 字符串，过滤非法实体类型，补全缺失字段。

    永不抛异常——任何解析失败都返回 {"entities": [], "relationships": []}。
    """
    raw = raw.strip()
    # 去掉可能的 markdown 代码块
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else ""

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("wiki_extractor: LLM 返回无法解析的 JSON，跳过。raw=%r", raw[:100])
        return {"entities": [], "relationships": []}

    if not isinstance(data, dict):
        return {"entities": [], "relationships": []}

    cleaned_entities: list[dict[str, Any]] = []
    for e in data.get("entities", []):
        if not isinstance(e, dict):
            continue
        entity_type = e.get("type", "")
        if entity_type not in ENTITY_TYPES:
            logger.debug("wiki_extractor: 跳过未知实体类型 %r (name=%r)", entity_type, e.get("name"))
            continue
        cleaned_entities.append({
            "name": str(e.get("name") or "").strip(),
            "type": entity_type,
            "new_facts": list(e.get("new_facts") or []),
            "current_status": str(e.get("current_status") or ""),
            "timeline_event": e.get("timeline_event") or None,
        })

    cleaned_entities = [e for e in cleaned_entities if e["name"]]

    cleaned_rels: list[dict[str, Any]] = []
    valid_rels = frozenset(
        {"concerned_about", "interested_in", "requires", "related_to", "mentions"}
    )
    for r in data.get("relationships", []):
        if not isinstance(r, dict):
            continue
        if r.get("relationship") not in valid_rels:
            continue
        cleaned_rels.append({
            "source": str(r.get("source") or ""),
            "target": str(r.get("target") or ""),
            "relationship": r["relationship"],
            "context": str(r.get("context") or ""),
        })

    return {"entities": cleaned_entities, "relationships": cleaned_rels}


def extract_entities_from_text(
    text: str,
    source_type: str,
    model_key: str = "deepseek",
) -> dict[str, Any]:
    """调用 LLM 从文本中提炼实体和关系。

    Args:
        text: 待提炼的原始文本（路演转写、会议纪要等）
        source_type: 文档类型标识（pitch_recording / manual_note / due_diligence）
        model_key: LLM 路由键，默认 deepseek

    Returns:
        {"entities": [...], "relationships": [...]}
        出错时返回 {"entities": [], "relationships": []}
    """
    if len(text) < _MIN_TEXT_LEN:
        logger.debug("wiki_extractor: 文本过短（%d 字符），跳过提炼", len(text))
        return {"entities": [], "relationships": []}

    client, model = _make_client(model_key)

    user_message = f"文档类型：{source_type}\n\n{text[:8000]}"  # 截断避免超 token

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        raw_content = response.choices[0].message.content or ""
        return parse_extraction_response(raw_content)
    except Exception as exc:
        logger.error("wiki_extractor: LLM 调用失败 model=%s exc=%s", model, exc)
        return {"entities": [], "relationships": []}
