# DD-V1 持久状态（受版本管理的权威位置）

> 本文件是 DD-V1 的**唯一权威状态**。
> 上一轮事故教训：状态曾只放在临时 session 工作区，目录被删除后全部丢失，
> 而 `check_consistency.py` 还活着、却被守卫的对象没了。故状态必须入仓。

```text
PROJECT_COMPLETE = false
CURRENT_WP       = WP-R0（环境恢复 / 现状审计 / 目标与验收冻结）
STATUS           = WP-R0 审计进行中
PERSISTENT_ROOT  = /Users/mac/dd-v1-workspace
REPO             = bog5d/cangjie-fos @ master a7a7e24 (2026-10-16)
CURRENT_BRANCH   = master（尚未开施工分支）
ISSUE_OF_RECORD  = cangjie-fos#71
LAST_UPDATE      = 2026-10-19
```

## 环境恢复记录（2026-10-19）

| 项 | 事实 |
|---|---|
| 会话工作区 | `/Users/mac/.minimax/sessions/.../workspace` **已被删除**，shell 工具一度不可用 |
| 恢复方式 | 用 write 工具重建目录树 → shell 恢复 → 另建持久工作区 |
| 持久工作区 | `/Users/mac/dd-v1-workspace`（cangjie-fos / cangjie-gm / grill-to-spec） |
| 他人工作区 | `/Users/mac/cangjie-fos` 存在，**有 17 个未跟踪文件（5–7 月遗留，最近修改停在 2026-07-09，无 dd_v1 相关）→ 未触碰、未删除、未覆盖** |
| 状态文件 | 本轮起写入仓库 `docs/dd-v1-fos71/`，不再放临时目录 |

## 上一轮丢失的内容（不可恢复，标 UNKNOWN）

以下文件曾只存在于临时 session 工作区，随目录删除而丢失，**未进版本控制**：

- `GOAL_CONTRACT.json`（GCCSEG L2 合同：分母、双账本、硬门槛）
- `STATE.md`（WP0–WP7 验收台账）
- `EVIDENCE_WP01.md` ~ `EVIDENCE_WP07.md`
- `REUSE_MATRIX.md`、`WP0_REPORT.md`、`WP6_BLOCKERS.md`

**影响**：历史执行细节无法逐字恢复。但**代码全部在 GitHub**，
且 #71 的 WP00–WP04 证据（`docs/dd-v1-fos71/`）是版本化的，权威性高于我丢失的文件。
**不伪造**：以下历史状态标 UNKNOWN，不凭记忆重写。

| 项 | 状态 |
|---|---|
| WP0–WP7 的技术验收结论 | **PARTIALLY_RECOVERABLE** — #66/#68 合并记录与 #71 WP00–WP04 证据可查 |
| WP0–WP7 的执行方自测条数 | **UNKNOWN**（数字随文件丢失，不凭记忆补写） |
| 双账本分母与 outcome 权重 | **UNKNOWN** — 原 `GOAL_CONTRACT.json` 已失；#71 WP02 的 Goal Contract 仍在仓库，以其为准 |

## 授权边界（本执行窗口不得自行越界）

- ❌ 不得充值 / 恢复 dsh 额度（**花钱，OQ-1 选项 a，需董事长批准**）
- ❌ 不得把真实敏感材料送外部模型（OQ-3 未授权）
- ❌ 不得自动外发、不得删除原始资产、不得绕过分支保护
- ❌ 不得新建第二套调度系统（cangjie-gm 是唯一权威）
- ❌ 不得自行批准生产部署
- ✅ 可自主：技术路线、重试、环境恢复、测试设计、缺陷优先级、回归补充

## 待董事长裁定（阻塞项）

| 编号 | 内容 | 影响 |
|---|---|---|
| **OQ-1** | 考生3（DeepSeek Harness）定案：a 恢复额度(花钱) / b 改用其他模型 / c 缺席报 BLOCKED | **当前=c**。决定"考生2"能否真正调用模型 |
| **OQ-2** | Gold Set 提供方与时点 | 评分恒为 NOT_SCORABLE |
| **OQ-3** | 真实材料送外部模型的授权 | 只能用合成材料验证 |

## next_action

1. WP-R0 完成五项审计（A 正文为何未进流程 / B 索引与认知卡为何未充分使用 / C PDF/Word/Excel 正文为何没交到匹配层 / D 为何只有少量类型进候选池 / E DeepSeek 实际读到什么）
2. 审计结论落 `docs/dd-v1-fos71/WP-R0-*.md`（入仓）
3. 开 `feat/71-wp-r1` 分支进入 WP-R1
