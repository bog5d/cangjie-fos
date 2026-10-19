# DD-V1 持久状态（受版本管理的权威位置）

> 本文件是 DD-V1 的**唯一权威状态**。
> 上一轮事故教训：状态曾只放在临时 session 工作区，目录被删除后全部丢失，
> 而 `check_consistency.py` 还活着、却被守卫的对象没了。故状态必须入仓。

```text
PROJECT_COMPLETE = false
CURRENT_WP       = WP-R1（正文/索引链路接通）— 核心已合入本分支，未提 PR
STATUS           = WP-R1_CORE_DONE / WP-R2~R5 待续
PERSISTENT_ROOT  = /Users/mac/dd-v1-workspace
REPO             = bog5d/cangjie-fos
BASE_COMMIT      = a7a7e24 (master, 2026-10-16)
BRANCH           = feat/71-wp-r1
COMMITS          = e60ed23 WP-R0 审计 / 79eecdd WP-R1 核心 /
                   81dafd9 Excel多表+PDF页码+正文抽主体
STATUS           = WP-R1_DONE · 系统侧端到端已通 · 待授权开 dsh
ISSUE_OF_RECORD  = cangjie-fos#71
LAST_UPDATE      = 2026-10-19
```

## WP 台账（执行方自测数字独立列出，不挂验收方名下）

| WP | 目标 | 状态 | 证据 | 阻塞 |
|---|---|---|---|---|
| WP-R0 | 环境恢复 / 现状审计 / 目标冻结 | ✅ DONE | `WP-R0-AUDIT.md`（130 行，五环断链全部 file:line） | 无 |
| WP-R1 | 接通正文解析、缓存、索引；召回改高召回；自动派生 meta | ✅ **DONE** | `79eecdd` + `81dafd9`；DD-V1 292 项全绿；真实模型实跑见下 | 无 |
| WP-R2 | 召回质量精排 | ⬜ 未开工 | — | — |
| WP-R3 | 清单→待审核答卷完整流程 | ⬜ 未开工 | — | — |
| WP-R4 | 合成测试图书馆 + 10 条代表性考试要求 | ⬜ 未开工 | — | — |
| WP-R5 | 独立验收 + 员工手册 + 交接 | ⬜ 未开工 | — | — |

## WP-R1 已完成（四项改动，全部向后兼容）

1. `_text_for` 新增 `cached_text` 来源 → PDF/Word/Excel 不再直接落 `NO_TEXT`
2. `retrieve_minimal_evidence` 改**并集高召回**：FTS 召回 + 元数据兜底，
   类型只影响排序，不再一票否决
3. 新增 `derive_meta_from_cards()` / `recall_by_text()`；
   `dd_v1_local_run.py` 新增 `--auto-meta` → **员工不必预先整理材料**
4. 消除静默全 MISSING：`_validate_args()` 无 meta 无 auto-meta 直接 exit 3；
   `_warn_missing_tagging()` 整批无 entity/period 时显式告警

**实测（仓库合成 fixture，零手工打标）**：

| | 修复前 | 修复后 |
|---|---|---|
| 每条义务候选 | **0** | **6** |
| 正文摘录 | `NO_TEXT` | **真实正文 + 行号 locator** |

## 真实模型端到端实跑（2026-10-19，minimax-pi，零手工打标）

```text
$ dd_v1_local_run.py run --material-root <fixture/snapshot> --items raw_items.json \
      --auto-meta --adapter minimax-pi --max-calls 1 --max-total-calls 4

{"auto_meta": {"library":"auto","cards":8,"meta":8}}
R1  adapter=OK  85.62s  RULE_ONLY          acc=0 rej=1  ALL_RESULTS_REJECTED
R2  adapter=OK  22.96s  AGENT_SUGGESTION   acc=1 rej=1   ← 模型真的参与了
R3  status=NEEDS_HUMAN_SPLIT
R4  adapter=OK  93.52s  AGENT_SUGGESTION   acc=1 rej=0   ← 模型真的参与了
```

**R2/R4 不再是 RULE_ONLY ⇒ 模型已实际参与语义判断**（修复前 DeepSeek 桩导致全程 RULE_ONLY）。

**R4-O1 模型判 MISSING 是正确行为，不是 bug**：义务要求 2022 年度审计报告，
候选全是 2024/2023（库中确无 2022）⇒ MISSING 正确。模型基于证据判断，
确定性校验器同时在正常把关。

## 关键新发现

- **`dsh` 0.1.7-rc.2 已装在本机** `/Users/mac/.npm-global/bin/dsh`。
  WP03/WP04 记的「dsh 已停用」指的是 **adapter 是桩**，不是没装。
  只差显式 `--allow-local-dsh`。**但真实调用会产生 API 费用，
  OQ-1 选项 a 明确标注「花钱，需批准」，本执行窗口未擅自开启。**
- `pi`（minimax-pi）与 `codex` 本机均可用，可作替代验证路径。

## 剩余子项

- [ ] `sem.MAX_EXCERPT_CHARS` 截断**无标记**（parser 层有 truncated，excerpt 层漏了）
- [ ] WP-R4 合成考试题库（10 条代表性要求 + 陷阱文件）
- [ ] WP-R2 召回精排 / WP-R3 答卷完整流程 / WP-R5 验收交接

## 授权边界（不变）

- ❌ 充值 / 恢复 dsh 额度（OQ-1 选项 a，花钱，需批准）— **本 WP 未越界**
- ❌ 真实材料送外部模型（OQ-3 未授权）— 实测正确拦截仓库外目录
- ❌ 自动外发 / 删除原始资产 / 绕过分支保护 / 自行批准生产部署
- ✅ 技术路线、重试、环境恢复、测试设计、缺陷优先级、回归补充

## 恢复步骤（任何窗口接手照此执行）

```bash
cd /Users/mac/dd-v1-workspace/cangjie-fos
git checkout feat/71-wp-r1
git log --oneline -3
cd backend && [ -d .venv ] || (uv venv --python 3.11 .venv && uv pip install --python .venv -e . pytest pytest-asyncio)
.venv/bin/python -m pytest tests/ -k dd_v1 -q -p no:randomly \
  --ignore=tests/test_ui_smoke_gk.py --ignore=tests/test_ui_smoke.py
```

期望：`DD-V1：执行 292 · 通过 292 · 失败 0`

## next_action

继续 WP-R1 剩余子项（Excel 工作表/单元格、PDF 页码、摘录截断标记、
平铺目录下的主体抽取），然后进 WP-R2。**不新开分支、不新建调度系统。**

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
