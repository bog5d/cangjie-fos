# P0 / P1 重构图纸与实施方案（REFACTOR_PLAN）

**状态：** 设计文档，**待你书面点头前禁止合入任何业务代码。**  
**范围：** 仅覆盖审计报告中的 **P0（双真相源 / 假漏斗）** 与 **P1（评估图状态与记忆纳入 FOS）**。  
**基线：** 以当前仓库「全量 `pytest` 绿」为门禁（实施阶段需保持；下文写明易炸点）。

---

## 0. 总原则（主程裁决）

1. **不复制** `memory_engine.py` / `llm_judge.py` 中的防噪与提炼实现到 FOS——**以调用 Coach 已导出函数为唯一合法路径**，避免两套阈值漂移。  
2. **不改写** Pitch_Coach LangGraph 节点内部逻辑（P0/P1 阶段）；FOS 只做 **路由、适配、编排、契约对齐**。  
3. 任何跨进程/跨包写入必须 **幂等、可观测、失败降级**（不拖垮 HTTP 主路径）。

---

## P0 — 机构数据同步：谁为主？改哪些文件？数据流？

### P0.A 主数据（System of Record）裁决

| 域 | 裁决 | 理由 |
|----|------|------|
| **HTTP API / War Room 漏斗 / 前端机构卡片 / `institution_intel_extract` 写入** | **`cangjie_fos.services.institution_store`（SQLite：`data/institutions.sqlite`）** 为 **唯一主数据** | Phase 6 已全链路绑定；回退到 `institutions.json` 会推翻已有 API 与测试矩阵。 |
| **Coach `institution_registry`（`MEMORY_ROOT/institutions.json`）** | 定位为 **从数据 / 别名与归一投影**（可选强同步） | 承载旧版 `register` / `resolve` / `fuzzy_match` 与 VC 词典；**供仍读该文件的 Coach 侧脚本或未来图内节点使用**，避免旧工具链断裂。 |

**不是**「以 Coach 为主把 FOS SQLite 改成读 JSON」——那将否定 Phase 6 产品契约；**也不是**「完全抛弃 Coach registry」——在过渡期内用 **单向投影** 消化双轨。

### P0.B 拟新建文件

| 路径 | 职责 |
|------|------|
| `backend/src/cangjie_fos/adapters/__init__.py` | 包初始化（可为空）。 |
| `backend/src/cangjie_fos/adapters/institution_coach_sync.py` | **单一函数**（命名建议）：`project_institution_to_coach_registry(*, name: str, tenant_id: str \| None) -> None`：内部 `ensure_pitch_coach_import_path()` 后 `from institution_registry import register`（或 `resolve`），将 FOS 落盘的 **规范机构名** 投影到 Coach；**吞异常打日志**，不影响 FOS 主事务。 |

（若你希望命名更语义化，可改为 `sync_fos_institution_name_to_pitch_coach`，但全仓只保留 **一个入口**，禁止在多处散落 `import institution_registry`。）

### P0.C 拟修改文件与调用点

| 文件 | 修改要点 |
|------|----------|
| `backend/src/cangjie_fos/services/institution_intel_extract.py` | 在 `extract_and_persist_institution_intel` 内 **`upsert_institution(...)` 成功提交后**（同一事务语义：SQLite `commit` 之后）调用 `adapters.institution_coach_sync.project_institution_to_coach_registry(name=..., tenant_id=...)`。 |
| `backend/src/cangjie_fos/api/routes/pipeline.py` | **无需改契约**；若增加「手动创建机构」POST，同样在 `create_institution` 成功后 **可选** 调用同一 sync（与 intel 路径共用）。 |
| `backend/src/cangjie_fos/api/routes/war_room.py` | **废弃 Mock**：将 `from cangjie_fos.services.war_room_mock import build_funnel_mock` 替换为 `from cangjie_fos.services.pipeline_funnel import build_funnel_from_institutions`，`get_funnel_mock` 实现体内改为 `return build_funnel_from_institutions(tenant_id=tenant_id)`。 |
| `backend/src/cangjie_fos/services/war_room_mock.py` | **保留文件**供极少数单测需要「纯假数据」时引用，但 **默认 HTTP 路径不再引用**；或在文档中标记 `@deprecated`。 |

### P0.D 数据流（文字时序）

```
[路演评估完成] 
  → institution_intel_extract.extract_and_persist_institution_intel
       → institution_store.upsert_institution（SQLite 主写）
       → adapters.institution_coach_sync.project_institution_to_coach_registry（JSON 投影，失败仅日志）

[前端 /api/war-room/funnel 或 /api/dashboard/status]
  → pipeline_funnel.build_funnel_from_institutions
       → institution_store.count_by_stage（读 SQLite）
```

**反向数据流（Coach → FOS）本阶段不做**：避免首次实施引入双向合并冲突；若日后需要，单独开 **P0′ 里程碑** 并加「冲突解决策略」设计评审。

### P0.E 与 Coach 评估图的关系（澄清）

- **实施前检查清单（人工 + grep）：** 在 `AI_Pitch_Coach/src/agent_nodes.py`、`agent_workflow.py` 中检索 `institution_registry` **是否被评估图引用**。  
  - **若评估图完全不读 registry**：P0 的 Coach 投影仅为 **兼容旧脚本/外设**，可为 **feature flag**（如 `CANGJIE_SYNC_INSTITUTION_TO_COACH=0/1`）。  
  - **若存在引用**：`CANGJIE_SYNC_INSTITUTION_TO_COACH` 默认 **1**，并在实施说明中写明。

---

## P0 — 废弃 Mock 漏斗：前端契约是否变化？

### 结论

- **`GET /api/dashboard/status`**：响应体仍为 `DashboardStatusResponse`，其中 `funnel: WarRoomFunnelResponse` —— **Phase 6 起已是 `build_funnel_from_institutions`，本项无契约变化**（仅继续保证与 `war_room` 路由一致）。  
- **`GET /api/war-room/funnel`**：响应模型 **`WarRoomFunnelResponse` 不变**；仅数据源由 `build_funnel_mock` 换为 `build_funnel_from_institutions`。  
  - **前端 TypeScript**：`frontend/src/types/funnel.ts` 字段结构 **不变**；**无需改组件 props 形状**。  
  - **语义变化**：`headline`、`stages[].subtitle` 文案从「Mock 话术」变为「Pipeline 实盘」——属 **展示层语义**，非 JSON Schema 破坏。

### 需同步的文档/测试（非业务逻辑，属契约维护）

| 位置 | 动作 |
|------|------|
| `backend/tests/test_phase2_integration.py::test_war_room_funnel_mock_contract` | **重命名/改断言**：不再断言「Mock」字样；改为断言 `tenant_id` 一致、`stages` 长度为 5、`momentum_score` 在 0–100。 |
| `docs/FOS_LEGACY_AUDIT_REPORT.md` | 更新「`/api/war-room/funnel` 仍为 Mock」一句为 **已对齐**。 |

---

## P1 — 统一记忆入口：纠错落盘如何接到 `memory_engine`？

### P1.A 复用哪些 Coach 函数（白名单）

| Coach 符号 | 路径 | 用途 |
|------------|------|------|
| `memory_diff_noise_gate_passes(original, refined)` | `AI_Pitch_Coach/src/memory_engine.py` | **防噪门**（与 `capture_and_distill_diff` 内部一致）；**禁止在 FOS 重实现阈值**。 |
| `capture_and_distill_diff(original, refined, company_id, tag, *, risk_type="", store_dir=None)` | 同上 | **静默收割主入口**：内部已调用 `memory_diff_noise_gate_passes`，不通过则 `None`；通过则 `distill_executive_memory_from_diff` 并 `append_executive_memory`。 |
| `resolve_memory_company_id(tenant_id)` | `AI_Pitch_Coach/src/agent_tenant.py` | **tenant_id → company_id**；与评估图 `retrieve_memory` 对齐。 |

### P1.B 拟新建文件

| 路径 | 职责 |
|------|------|
| `backend/src/cangjie_fos/adapters/coach_memory_bridge.py` | **单一函数**（建议名）：`try_capture_diff_to_executive_memory(*, tenant_id: str, ai_text: str, user_text: str, tag: str, risk_type: str = "") -> ExecutiveMemory \| None`：内部 `ensure_pitch_coach_import_path()` → `from memory_engine import capture_and_distill_diff` + `from agent_tenant import resolve_memory_company_id`；`company_id = resolve_memory_company_id(tenant_id)`，若为 `None` 则 **直接返回 None**（与图内「无效 tenant 跳过 IO」一致）。返回值类型使用 Coach `schema.ExecutiveMemory`（实施时 `from schema import ExecutiveMemory` 在 import path 已注入后）。 |

### P1.C 拟修改文件与插入点

| 文件 | 函数 | 修改要点 |
|------|------|----------|
| `backend/src/cangjie_fos/schemas/evolution.py` | `TextDiffFeedbackRequest` | **新增可选字段** `memory_tag: str \| None = Field(None, description="映射 Executive Memory 桶；缺省由服务端推断")`（**Pydantic 默认向后兼容**：旧客户端不传不炸）。 |
| `backend/src/cangjie_fos/api/routes/feedback.py` | `submit_text_diff` | 在 `store.persist_text_diff(body)` **成功返回后**、`reflection.enqueue_reflection(...)` **之前或之后**（建议 **之后**，避免反思队列依赖记忆 UUID）调用 `coach_memory_bridge.try_capture_diff_to_executive_memory(tenant_id=body.tenant_id, ai_text=body.ai_text, user_text=body.user_text, tag=_resolve_tag(body), risk_type="")`；**不**因 Coach 失败回滚 Evolution JSON（审计与反思仍独立）。 |
| `backend/src/cangjie_fos/services/evolution_store.py` | `persist_text_diff` | **可选**：在 `record` 中增加 `coach_memory_captured: bool \| None` 字段（若你希望 API 可观测）；**属 schema 扩展**，需同步 `EvolutionRecord`。 |

### P1.D `tag` 与防噪门策略（不写新阈值）

1. **第一版（最小风险）**：`tag = (body.memory_tag or "").strip() or "default"`，与 `capture_and_distill_diff` 默认行为一致。  
2. **第二版（增强）**：在 `coach_memory_bridge` 内增加 `_infer_tag_from_trace(body.trace_id)` 仅作 **建议**，仍允许客户端覆盖；**不**在 FOS 复制 `memory_engine` 内 `_MEMORY_NOISE_RATIO_THRESHOLD` 常量。

**防噪与距离阈值**：**全部**留在 `capture_and_distill_diff` → `memory_diff_noise_gate_passes` → `distill_executive_memory_from_diff` 链上；FOS **只传 original/refined 字符串**。

### P1.E 数据流（纠错）

```
POST /api/v1/feedback/text-diff
  → evolution_store.EvolutionJsonStore.persist_text_diff（现有 JSON 审计链，保留）
  → adapters.coach_memory_bridge.try_capture_diff_to_executive_memory
       → agent_tenant.resolve_memory_company_id(tenant_id)
       → memory_engine.capture_and_distill_diff(ai_text, user_text, company_id, tag)
            → memory_diff_noise_gate_passes
            → llm_judge.distill_executive_memory_from_diff（Coach 内）
            → memory_engine.append_executive_memory
  → reflection_service.enqueue_reflection（保持现有）
```

---

## P1 — NPC 记忆注入：如何改写 `npc_chat_graph.py`？

### P1.A 目标行为

- 在 **NPC 上下文拼装** 阶段，除现有 `build_tenant_context_block` / `evolution_guidelines` / `build_pre_meeting_institution_block` 外，增加与评估图 **同构** 的 episodic 片段：**`load_top_executive_memories_for_prompt(company_id, tag, limit=...)`**。

### P1.B 建议的代码结构（文件与函数）

| 文件 | 函数 | 动作 |
|------|------|------|
| `backend/src/cangjie_fos/services/tenant_context.py` | **新建** `build_episodic_memory_snippet_for_npc(*, tenant_id: str, tag: str, limit: int = 5) -> str` | 内部：`ensure_pitch_coach_import_path()` → `from agent_tenant import resolve_memory_company_id` → `cid = resolve_memory_company_id(tenant_id)`；若 `cid` 为 `None` 返回空串；否则 `from memory_engine import load_top_executive_memories_for_prompt`，格式化与现 `build_executive_memory_digest` **类似**但 **只含 Top-N**（控制 token）。 |
| `backend/src/cangjie_fos/services/npc_chat_graph.py` | `_last_user_text`（已存在） | **复用**：从中解析 `tag` 的第一版策略：`_infer_memory_tag_from_user_text(text: str) -> str` **同文件私有函数**——可恒为 `"default"`，或从「被问到的机构名」用 **FOS** `institution_store.find_matching_names` 取首个 `name` 作为 tag（**与 Coach tag 文件命名规则对齐**：需保证 `agent_tenant`/`memory` 使用的 tag 字符集与 `_safe_fs_segment` 一致；若含非法字符则降级 `"default"`）。 |
| `backend/src/cangjie_fos/services/npc_chat_graph.py` | `_inject_narrative` | 在拼完 `evolution_guidelines` 与 `build_pre_meeting_institution_block` 之后，追加：`epi = build_episodic_memory_snippet_for_npc(tenant_id=tid, tag=_infer_memory_tag_from_user_text(_last_user_text(state)))`；若非空则 `block = f"{block}\n\n[错题本 Top-N 命中]\n{epi}"`。 |

### P1.C 与 `list_all_executive_memories_for_company` 的关系

- **保留** `build_executive_memory_digest`（长列表摘要）用于 **非 NPC** 或后续 Admin；**NPC 主路径** 改为 **Top-N** 与评估图一致，避免 **双份全长记忆** 撑爆上下文。  
- 实施顺序建议：**先加 `build_episodic_memory_snippet_for_npc` + `_inject_narrative` 注入**，再视 token 压测决定是否 **削弱** `build_tenant_context_block` 内原 digest 篇幅（第二步需你二次点头）。

---

## 防爆雷：最易挂测试的点与防御策略

### 高风险区

| 风险 | 说明 | 防御 |
|------|------|------|
| **`GET /api/war-room/funnel` 断言依赖「Mock」文案** | `test_phase2_integration.py` 等 | 按上文 **改断言为结构契约**；不依赖 `headline` 固定字符串。 |
| **`submit_text_diff` 行为扩展** | Phase 3/4/5 集成测试可能 mock `EvolutionJsonStore` 而未预料 Coach import | 在 `coach_memory_bridge` 内 **try/except** 包裹全部 Coach 调用；**默认测试环境** `resolve_memory_company_id` 返回 `None` 时 **零副作用**（与现测一致）。 |
| **`ensure_pitch_coach_import_path` 在 CI 缺失目录** | 部分环境无 `AI_Pitch_Coach` | 已有路径探测；新增测试用 **`@pytest.mark.skipif`** 或 **monkeypatch** `capture_and_distill_diff` 为 noop **仅限**单测文件 `test_coach_memory_bridge_contract.py`（新建），不污染生产代码。 |
| **SQLite / JSON 文件锁** | Windows 上并发写 | `institution_coach_sync` **串行**、短事务；避免在请求线程内做大 JSON 重写。 |
| **NPC 图状态体积** | checkpoint 变大 | `build_episodic_memory_snippet_for_npc` **硬限制** `limit=5` + 每条 `raw_text`/`correction` **截断**（与现 `build_executive_memory_digest` 一致的量级）。 |

### 门禁（实施阶段执行，本文档不执行）

1. **全量** `pytest`（backend）前后对比 **0 失败**。  
2. 新增 **契约测试**（建议文件 `backend/tests/test_p0_war_room_funnel_parity.py`）：同一 `tenant_id` 下 `/api/war-room/funnel` 与 `build_dashboard_status(...).funnel.model_dump()` 中 funnel 字段 **深度相等**（或至少 `headline`/`stages[].key`/`counts` 派生一致）。  
3. 新增 **`test_feedback_text_diff_invokes_capture`**：`monkeypatch` `coach_memory_bridge.try_capture_diff_to_executive_memory` 为 spy，断言 **persist 之后被调用一次**。

---

## 实施顺序（建议合并顺序，仍等你点头后开工）

1. **P0 war_room 路由对齐**（最小 diff，先绿）。  
2. **P0 institution_coach_sync + intel 后置调用**（feature flag 默认关 → 开）。  
3. **P1 coach_memory_bridge + feedback 接入**（schema 扩展 + bridge）。  
4. **P1 NPC `tenant_context` + `npc_chat_graph._inject_narrative`**（tag 策略先 `default` 再增强）。  
5. 文档与审计报告 **勘误段落** + 全量 pytest。

---

## 需要你确认的三点（回复即可）

1. **Coach `institution_registry` 投影**：是否同意 **默认开启** `CANGJIE_SYNC_INSTITUTION_TO_COACH=1`（仅写、不读回 FOS）？  
2. **`TextDiffFeedbackRequest.memory_tag`**：是否同意 **可选字段** 首版上线？  
3. **NPC tag 推断**：首版是否接受 **恒为 `default`**，第二版再做「机构名 → tag」？

---

**文档结束。** 路径：`docs/REFACTOR_PLAN.md`。
