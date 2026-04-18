"""NPC 对话 LangGraph + Sqlite Checkpointer + 租户上下文注入（Phase 4）。"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated, Any, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from cangjie_fos.core.checkpointing import get_sqlite_checkpointer
from cangjie_fos.services.evolution_guidelines_loader import load_recent_guidelines_for_prompt
from cangjie_fos.services.institution_meeting import build_pre_meeting_institution_block
from cangjie_fos.services.tenant_context import build_episodic_memory_snippet_for_npc, build_tenant_context_block

logger = logging.getLogger(__name__)

_compiled: Any | None = None


class NpcGraphState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tenant_id: str
    user_name: str
    evolution_guidelines: str
    narrative: str


def _npc_display_name() -> str:
    return (os.getenv("CANGJIE_NPC_DISPLAY_NAME") or "豆豆").strip() or "豆豆"


def _base_system() -> str:
    n = _npc_display_name()
    return (
        f"你是「仓颉 FOS」里的融资陪练 NPC「{n}」。"
        "回答简短、可执行，偏一级市场语境；不要编造私密数据。"
        "若用户问「是否准备好见红杉」等，请结合下方「资料室清单」指出明显缺口。"
    )


def _last_user_text(state: NpcGraphState) -> str:
    msgs = list(state.get("messages") or [])
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            return (m.content or "").strip()
    return ""


def _infer_memory_tag_from_user_text(_text: str) -> str:
    """REFACTOR_PLAN 首版：恒为 default；第二版再做机构名→tag。"""
    return "default"


def _preload_evolution(state: NpcGraphState) -> dict[str, str]:
    tid = (state.get("tenant_id") or "").strip() or "unknown"
    blob = load_recent_guidelines_for_prompt(tenant_id=tid)
    return {"evolution_guidelines": blob}


def _inject_narrative(state: NpcGraphState) -> dict[str, str]:
    tid = (state.get("tenant_id") or "").strip() or "unknown"
    block = build_tenant_context_block(tenant_id=tid)
    evo = (state.get("evolution_guidelines") or "").strip()
    if evo:
        block = f"{block}\n\n[进化指南 Evolution Guidelines]\n{evo}"
    meeting = build_pre_meeting_institution_block(tenant_id=tid, user_text=_last_user_text(state))
    if meeting:
        block = f"{block}\n\n{meeting}"
    ut = _last_user_text(state)
    mem_tag = _infer_memory_tag_from_user_text(ut)
    epi = build_episodic_memory_snippet_for_npc(tenant_id=tid, tag=mem_tag, limit=5)
    if epi:
        block = f"{block}\n\n[错题本 Top-N 命中]\n{epi}"
    return {"narrative": block}


def _call_llm(state: NpcGraphState) -> dict[str, Sequence[BaseMessage]]:
    nar = (state.get("narrative") or "").strip()
    uname = (state.get("user_name") or "").strip()
    sys_head = _base_system()
    if uname:
        sys_head = f"{sys_head}\n\n当前对话指挥官：{uname}。"
    raw_msgs = list(state.get("messages") or [])
    if len(raw_msgs) > 48:
        raw_msgs = raw_msgs[-48:]

    ds_key = os.getenv("DEEPSEEK_API_KEY")
    oa_key = os.getenv("OPENAI_API_KEY")
    if not ds_key and not oa_key:
        last = raw_msgs[-1]
        human = last.content if isinstance(last, HumanMessage) else str(last)
        reply = (
            f"【离线 NPC】已收到：{human[:600]}\n\n{nar[:1200]}"
            "\n（配置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 后启用真模型。）"
        )
        return {"messages": [AIMessage(content=reply)]}

    api_messages: list[BaseMessage] = [
        SystemMessage(content=sys_head + "\n\n" + nar),
    ]
    for m in raw_msgs:
        api_messages.append(m)

    try:
        from openai import OpenAI

        if ds_key:
            client = OpenAI(api_key=ds_key, base_url="https://api.deepseek.com")
            model = os.getenv("CANGJIE_NPC_MODEL", "deepseek-chat")
        else:
            assert oa_key is not None
            client = OpenAI(api_key=oa_key)
            model = os.getenv("CANGJIE_NPC_MODEL", "gpt-4o-mini")
        plain = []
        for m in api_messages:
            if isinstance(m, SystemMessage):
                plain.append({"role": "system", "content": m.content})
            elif isinstance(m, HumanMessage):
                plain.append({"role": "user", "content": m.content})
            elif isinstance(m, AIMessage):
                plain.append({"role": "assistant", "content": m.content})
            else:
                plain.append({"role": "user", "content": str(m.content)})
        r = client.chat.completions.create(
            model=model,
            temperature=0.35,
            messages=plain,
            max_tokens=1200,
        )
        text = (r.choices[0].message.content or "").strip()
        return {"messages": [AIMessage(content=text)]}
    except Exception as e:  # noqa: BLE001
        logger.warning("npc_llm_failed: %s", e)
        return {"messages": [AIMessage(content=f"【模型暂不可用】{e!s}")]}


def _build_graph(checkpointer: Any) -> Any:
    g = StateGraph(NpcGraphState)
    g.add_node("preload", _preload_evolution)
    g.add_node("inject", _inject_narrative)
    g.add_node("agent", _call_llm)
    g.set_entry_point("preload")
    g.add_edge("preload", "inject")
    g.add_edge("inject", "agent")
    g.add_edge("agent", END)
    return g.compile(checkpointer=checkpointer)


def get_compiled_npc_graph() -> Any:
    global _compiled
    if _compiled is None:
        saver = get_sqlite_checkpointer()
        _compiled = _build_graph(saver)
    return _compiled


def reset_compiled_npc_graph_for_tests() -> None:
    """测试隔离：清空编译缓存。"""
    global _compiled
    _compiled = None


def invoke_npc_chat(
    *,
    tenant_id: str,
    user_message: str,
    thread_id: str | None,
    user_name: str | None = None,
) -> tuple[str, str, str]:
    """返回 (reply, trace_turn_id, thread_id)。"""
    tid = (thread_id or "").strip() or uuid.uuid4().hex
    app = get_compiled_npc_graph()
    cfg: dict[str, Any] = {"configurable": {"thread_id": tid}}
    turn = uuid.uuid4().hex
    out = app.invoke(
        {
            "messages": [HumanMessage(content=user_message)],
            "tenant_id": tenant_id,
            "user_name": (user_name or "").strip(),
        },
        cfg,
    )
    msgs = list(out.get("messages") or [])
    last_ai = ""
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            last_ai = m.content or ""
            break
    return last_ai, turn, tid


def export_thread_messages(*, thread_id: str) -> list[dict[str, str]]:
    """从 Checkpointer 导出可 JSON 化的消息列表。"""
    app = get_compiled_npc_graph()
    snap = app.get_state({"configurable": {"thread_id": thread_id}})
    vals = snap.values or {}
    raw = list(vals.get("messages") or [])
    out: list[dict[str, str]] = []
    for m in raw:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content or ""})
        elif isinstance(m, AIMessage):
            out.append({"role": "assistant", "content": m.content or ""})
        elif isinstance(m, SystemMessage):
            out.append({"role": "system", "content": m.content or ""})
        else:
            out.append({"role": "unknown", "content": str(getattr(m, "content", m))})
    return out
