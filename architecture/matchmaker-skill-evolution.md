# MatcherSkill 架构设计与进化路线

> 文档版本：V5.1（2026-05-04）  
> 对应代码：`backend/src/cangjie_fos/engine/matchmaker.py`  
> 状态：已实现并上线

---

## 一、为什么需要 Skill 协议

FOS 当前的匹配器（MatchMaker）使用 BM25 关键词统计，能找到词频重叠的文件，但有三个根本性缺陷：

| 缺陷 | 表现 | 根因 |
|------|------|------|
| 不理解机构偏好 | 同样是"财务模型"，红杉和IDG实际需要的格式、颗粒度不同 | 无历史记忆 |
| 不从错误中学习 | 每次匹配都从头开始，上次选了哪些文件对下次没有影响 | 无反馈闭环 |
| 无法升级实现 | BM25 和 LLM 是完全不同的接口，换算法需要重写调用方 | 无标准接口 |

`MatcherSkill` Protocol 解决第三个问题，让系统具备**无缝升级能力**；`match_outcomes` 表解决第一和第二个问题，让匹配**越用越准**。

---

## 二、当前架构（V5.1）

```
POST /api/v1/assets/match
        │
        ▼
  parse_requirements_from_text()   ← LLM 或启发式
        │
        ▼
  db_institution_match_profile()   ← 查 match_outcomes 表，获取机构历史偏好
        │                            （新机构：返回空画像，退化为纯 BM25）
        ▼
  get_default_matcher()            ← 工厂函数，返回 BM25MatcherSkill 实例
        │
        ▼
  BM25MatcherSkill.match()
        ├── Step 1: BM25 评分（tags×3.0, filename×2.0, summary×1.5）
        └── Step 2.5: _apply_institution_boost()  ← 偏好文件 ×1.3 加权
        │
        ▼
  db_match_session_create()        ← 持久化会话


POST /api/v1/assets/match/{id}/confirm
        │
        ▼
  db_match_session_update(status="confirmed")
        │
        ▼
  db_match_outcome_batch_save()    ← 写入学习记忆（飞轮转一圈）
```

---

## 三、核心数据结构

### 3.1 MatcherSkill Protocol

```python
class MatcherSkill(Protocol):
    def match(
        self,
        requirements: list[RequirementItem],
        assets: list[dict],
        institution: str = "",
        institution_profile: dict | None = None,
        top_n: int = 5,
    ) -> list[MatchResult]: ...
```

**调用方永远只调这一个接口**。底层实现（BM25 → LLM）可随时替换，不改调用方代码。

### 3.2 institution_profile 画像结构

```python
{
    "institution": "红杉资本",
    "total_sessions": 5,            # 历史匹配次数
    "total_selected": 23,           # 累计选中文件数
    "avg_selected_per_session": 4.6,
    "preferred_paths": [            # 被选中 ≥1 次的文件，按频率降序
        "财务/2025Q4财务模型.xlsx",
        "BP/商业计划书v3.pdf",
        ...
    ],
    "preferred_tags": [],           # 预留（调用方可从 assets 表二次 join 填充）
    "last_contact": 1714000000.0,
}
```

### 3.3 match_outcomes 表（学习飞轮原始数据）

```sql
CREATE TABLE match_outcomes (
    id           TEXT PRIMARY KEY,    -- session_id::asset_path
    session_id   TEXT NOT NULL,       -- 关联 match_sessions
    institution  TEXT NOT NULL,       -- 机构名称
    asset_path   TEXT NOT NULL,       -- relative_path（唯一键）
    asset_name   TEXT NOT NULL,       -- filename（展示用）
    was_selected INTEGER NOT NULL,    -- 1=被人工选中, 0=候选但放弃
    created_at   REAL NOT NULL
);
```

---

## 四、学习飞轮工作原理

```
第1次匹配（红杉资本）
  需求：财务报表、BP
  BM25 推荐：[财务模型.xlsx ✅, 旧版BP.pdf ✅, 审计报告.pdf ×]
  人工 confirm：财务模型.xlsx + 旧版BP.pdf
  → match_outcomes 写入：财务模型.xlsx(selected=1), 旧版BP.pdf(selected=1), 审计报告.pdf(selected=0)

第2次匹配（红杉资本）
  历史画像：preferred_paths=["财务模型.xlsx", "旧版BP.pdf"]
  BM25 + 偏好加权：财务模型.xlsx 得分 ×1.3 → 更靠前
  人工 confirm 需调整更少 → 效率提升

第N次匹配
  preferred_paths 积累 → 画像越来越精准 → 匹配结果越来越符合该机构口味
```

每次人工决策都是对系统的一次"投票"，系统把这份判断存下来，下次自动复用。

---

## 五、进化路线图

### 当前：BM25 + 历史偏好加权（V5.1）

- ✅ 零额外依赖（纯标准库）
- ✅ 零延迟（同步执行）
- ✅ 开始积累历史数据
- ⚠️ 不理解语义（"审计报告"和"财务报表"关键词不重叠时无法匹配）

**触发升级条件**：单机构历史匹配次数 ≥ 10，或用户明确觉得匹配质量"还不够好"。

---

### 下一步：BM25 召回 + LLM 精排（V5.2）

**原理**：BM25 负责廉价召回 Top-20，LLM 负责从中精选 Top-5 并说理由。

```python
class LLMRerankerSkill:
    """BM25 召回 Top-20 → LLM 精排 Top-N，附带选择理由。"""

    def match(self, requirements, assets, institution="",
              institution_profile=None, top_n=5) -> list[MatchResult]:
        # Step 1: BM25 召回候选池（top_n * 4）
        bm25 = BM25MatcherSkill()
        candidates = bm25.match(requirements, assets, top_n=top_n * 4)

        # Step 2: LLM 精排（一次调用，所有需求打包）
        return self._llm_rerank(requirements, candidates, institution_profile, top_n)
```

**何时启用**：在 `get_default_matcher()` 中按配置切换：

```python
def get_default_matcher() -> MatcherSkill:
    if os.environ.get("MATCHER_MODE") == "llm":
        return LLMRerankerSkill()
    return BM25MatcherSkill()   # 默认
```

**调用方代码不变**，只改工厂函数。

---

### 终态：全自动主动匹配（V6.0）

路演结束后，系统自动：
1. 分析路演录音中暴露的弱点（LangGraph 评估节点）
2. 根据弱点生成补材料需求
3. 预匹配目标机构的历史偏好画像
4. 生成"主动推荐清单"推送给主理人
5. 主理人只需确认，一键发出

---

## 六、boost_factor 调参建议

| 历史匹配次数 | 推荐 boost_factor | 说明 |
|-------------|------------------|------|
| 0-3 次 | 1.0（不加权） | 数据太少，偏好不可信 |
| 4-10 次 | 1.2 | 轻微偏好，保留探索空间 |
| 10-30 次 | 1.3（当前默认） | 偏好稳定，信任历史 |
| 30+ 次 | 1.5 | 机构偏好高度稳定，大力加权 |

可在 `db_institution_match_profile()` 返回值中加入 `recommended_boost` 字段，由调用方传给 `_apply_institution_boost()`。

---

## 七、关键文件速查

| 职责 | 文件 |
|------|------|
| 匹配引擎（Protocol + 实现） | `backend/src/cangjie_fos/engine/matchmaker.py` |
| 学习记忆 CRUD | `backend/src/cangjie_fos/services/pitch_job_db.py`（`db_match_outcome_batch_save`, `db_institution_match_profile`） |
| API 路由（匹配 + confirm） | `backend/src/cangjie_fos/api/routes/assets.py`（`post_match_route`, `post_match_confirm_route`） |
| 匹配器测试 | `backend/tests/test_matchmaker.py` |
| 数据表 DDL | `pitch_job_db.py` 中 `_DDL` 变量（`match_outcomes` 表） |

---

## 八、测试覆盖

```
tests/test_matchmaker.py（15 个用例）
  ├── 启发式解析基本功能
  ├── BM25 匹配评分（tags/filename/summary 权重）
  ├── match_sessions CRUD
  ├── API 路由（match/confirm/get）
  ├── MatcherSkill 协议合规性
  ├── BM25MatcherSkill.match() 接口验证
  ├── institution_profile 历史偏好加权（boost tag + score 提升）
  ├── match_outcomes 批量写入 + 画像聚合
  ├── 空机构画像不报错
  └── confirm API 端到端（写 outcomes → profile 可查）
```

---

## 九、Wiki 知识展示层（V5.2 知识注入点）

> 更新日期：2026-05-05

### 架构定位

Wiki 不是独立页面，而是在 6 个行动点自动浮现的上下文知识。

```
行动点                  知识来源                    组件
─────────────────────────────────────────────────────────────
匹配前（填机构名）      db_institution_briefing()   InstitutionBriefingCard
匹配结果每一行         candidate_to_dict().reason   ResultRow（reason 小字）
匹配完成后             session.gap_hints            GapAlertBanner
机构档案详情            db_institution_briefing()   WikiPreview
资产行 📊 按钮         db_asset_wiki_summary()      AssetWikiPanel
晨报横幅               nightly_suggestions 表       DigestBanner
```

### 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/institutions/{name}/briefing` | GET | 机构简报 + 缺口检测 |
| `/api/v1/assets/wiki/{path:path}` | GET | 资产选用历史摘要 |
| `/api/v1/digest/pending` | GET | 未读晨报建议 |
| `/api/v1/digest/{id}/consume` | POST | 标记晨报已读 |

### 缺口检测算法

查询机构历史已确认 session 的 `results` JSON，提取 `color` 为 `gray`/`red` 的
`requirement.description`，去重后最多返回 5 条。代表"素材库已知短板"。

### candidate reason 字段

`candidate_to_dict()` 根据 `matched_fields` 内容生成人类可读说明：

| matched_fields 值 | reason 片段 |
|-------------------|-------------|
| `"tags"` | 标签命中 |
| `"filename"` | 文件名匹配 |
| `"summary"` | 摘要相关 |
| `"[机构历史偏好↑]"` | 机构历史首选 |
| 无以上字段 | 综合相关 |

### 数据流

```
每次 confirm → match_outcomes 写入
               ↓
    db_institution_briefing() 从 match_sessions 聚合缺口
    db_asset_wiki_summary()   从 match_outcomes 聚合选用历史
               ↓
    前端注入点自动展示（无需用户主动查询）
```

### 测试覆盖（V5.2 新增）

```
tests/test_wiki_display.py（11 个用例，371 → 382 passed）
  ├── db_institution_briefing 无历史时返回空
  ├── db_institution_briefing 从 confirmed session 检测 gray/red 缺口
  ├── db_institution_briefing 同一缺口多次出现只记录一次
  ├── db_asset_wiki_summary 无历史时返回零值
  ├── db_asset_wiki_summary 有 match_outcomes 时正确聚合
  ├── candidate_to_dict 包含 reason 字段
  ├── reason 包含"机构历史首选"（当 preferred_paths 命中时）
  ├── GET /briefing API（无历史返回 has_history=False）
  ├── GET /assets/wiki/{path} API（返回正确结构）
  ├── GET /digest/pending API（返回 suggestions 列表）
  └── POST /assets/match API（返回值含 gap_hints 字段）
```
