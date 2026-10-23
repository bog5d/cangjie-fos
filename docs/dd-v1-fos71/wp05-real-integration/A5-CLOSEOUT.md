# A5 · 收口规格件（仓内唯一留存件）

> ★ 本文件是 **A5 包的规格件**（本仓唯一留存件）。
> ★ **收口总报告（rev2）与全部证据不在本仓**：按波总 13:42 硬约束（证据不得进入会被 push 的公开仓树），
>   已迁到司仓侧可审计区（GM 仓 `work/evidence/W-DD-V1-REALINT-2026-WP-A5/`）。
> ★ 本文件**不含**本机绝对路径、司仓会话 ID、真实客户名或材料库代号；证据面只给位置，不给内容。

## 1. 本包范围

- **内容**：收口（硬 Gate 全表复核 + 双进度条复算）+ 续棒演练（★ G-A5-2）+ Skills 复盘与审计。
- **性质**：research 包 —— **未改任何 FOS 产品代码 / 测试**；未改 A0–A4 的裁定书、交付文档与证据。
- **基座**：`453957e`；**分支**：`feat/71-a5-closeout`。

## 2. 硬 Gate 复核结果（HG-01 … HG-09）

| HG | 判定 | 依据（摘要） |
|---|---|---|
| HG-01 单 writer / 单 GM | PASS | 运行时 lease 唯一有效 owner；无第二调度器 |
| HG-02 真实 FOS 调用 | PASS（接线层）/ 交付层未合入 | 合同链已接通到组包末端 |
| HG-03 Gold 盲隔离 | PASS（合成盲测层）/ A4b 真机层 BLOCKED | 真机层缺 4 项触发条件 |
| HG-04 数据与费用 | PASS | 0 外部调用、0 费用 |
| HG-05 无假 MATCH | PASS | 判定层口径有据 |
| HG-06 人工 + 精确交付 | PASS | 人工确认步骤与逐义务组包 |
| HG-07 Reviewer 独立 | PASS（历史包）/ **本包自身回执已补**（见 §5） | 本包回执落盘后本条才完整成立 |
| HG-08 真实 Windows 闭环 | **BLOCKED** | 缺 4 项触发条件，缺一不可 |
| HG-09 无人值守续棒 | PASS（判据原文口径）＋**无人值守属性打折已登记**（见 §4） | 真实接棒 + 真实产物 + 指针自动前进 |

## 3. 续棒演练（★ G-A5-2）

- 真实闭环已跑通：真实调度 → 唯一 Executor → 真实产物 → 独立门 → **自动下一项**（门 PASS 后 13.3 秒内自动进位）。
- **不是反例**：反例是「心跳更新 / Cron 存在 / 留言送达即报成功」；本包给出的是**真实 commit + 真实测试退出码 + 门裁决 + 指针自动前进的前后读数**。
- 演练过程中挖出的真断线（第二段 7 条 + 第三段 1 条）已由司仓在本轮接线修复（**不属 A5 白名单**，在 GM 侧逐项披露）。

## 4. ★ 诚实登记：无人值守纯度被打折（对应第一轮独立裁定 MAJOR-3）

演练窗口内实有 **7 次** `SUPERVISOR_DIRECT_EDIT_VIOLATION`
（时点 06:44 / 06:45 / 06:47 / 07:05 / 07:25 / 08:54 / 08:56；wp = WP-DRILL-1 / WP-DRILL-2），改动面含：

- `gm/judge.py`、`gm/dispatcher.py`、`gm/achievement_ledger.py`
- `gm/runtime_watchdog/transport.py`、`gm/wiring_ledger.py`
- `config/runtime_watchdog.json`、`config/gm_runtime_controller.json`

⇒ 旧表述「**全程无人工值守触发**（只做了一次接管指针 + 杀掉空转 worker）」**不成立**，已改正。
⇒ HG-09 的**判据原文口径仍成立**（真实接棒 + 真实产物），但**无人值守纯度被显著低估** ⇒ 直接影响 O5 计分条件。

## 5. 改动面逐件对账（白名单外 0）

本包 FOS 侧白名单（任务书第 3 段）与逐件处置：

| 白名单路径 | 本次处置 |
|---|---|
| `docs/dd-v1-fos71/wp05-real-integration/A5-CLOSEOUT.md` | 保留为**本规格件**（原「收口总报告 + 证据包」按硬约束迁出仓内） |
| `docs/dd-v1-fos71/wp05-real-integration/a5-evidence/**` | ★ **已迁出仓内**（迁往司仓侧可审计区，6 件逐字节留存） |

**白名单外：1 件** = `docs/dd-v1-fos71/wp05-real-integration/INTENT-SPEC-ARCHITECTURE.md`（+3 / −1）

- **性质：安全修复（脱敏）** —— 把基线中一处**真实客户短名**中性化 + 1 行 marker 注释；**不是越权改动**。
- **处置**：本迁出提交中把该文件**对齐到 master 版本** —— master 已由脱敏包包含同一处中性化
  （复核命令 `git diff origin/master -- <该路径>` ⇒ **实测为空，0 行差异**）。
- ★ **口径说明（不得含糊）**：相对**本包基座** `453957e`，该文件仍显示 3/−1 的差异 ——
  因为**基座自身带那一处真实短名**；本提交的效果是把它**中性化**（与 master 逐字节一致），
  **不存在越权改动**。因此「白名单外改动归零」的准确口径是：
  **相对 master 归零**（复核命令 `git diff --stat origin/master -- <该路径>` ⇒ 空），
  而相对旧基座的差异是**安全修复**本身，已在此显式披露。
- ⇒ 其余改动面全部落在第 3 段白名单内（见上表），**白名单外越权改动 = 0**。

## 6. 双进度条（本包不给自己记账）

- **工程进度**：分母 **6 冻结**；A5 计入与否以**独立裁定**为准（第一轮裁定 = FAIL：MAJOR-1 / 2 / 3 / 5 / 6）。
- **效果进度**：**0 / 100**（O1–O5 全 UNKNOWN；A4b 真机盲考仍 **BLOCKED**）⇒ 本包**不因前进效果分**。

## 7. 证据位置（司仓侧可审计区）

- 收口总报告（rev2，含 MAJOR-1/2/3 与 7 项 MINOR 的逐条处置）：GM 仓 `work/evidence/W-DD-V1-REALINT-2026-WP-A5/A5-CLOSEOUT.md`
- 证据包 6 件（含冻结清单与 provenance）：GM 仓 `work/evidence/W-DD-V1-REALINT-2026-WP-A5/a5-evidence/`
- 第一轮独立裁定书（FAIL）：GM 仓 `work/evidence/W-DD-V1-REALINT-2026-WP-A5/A5-REVIEW-VERDICT-ROUND1.md`
- 交付契约回执（result.json + DONE）：GM 仓 `data/inbox/T-DD-V1-REALINT-2026-WP-A5/`

## 8. 欠账（摘要，详见 rev2 全报告 §12）

1. `daemon._worker_needles()` 只认 cursor ⇒ needle 清单仍是维护性负债（应自动推导）。
2. 客观门 FAIL 时的**失败用例归档**未做（无每次门裁决的失败集历史）。
3. 存量 39 条治理线失败（基线名单只增不减）⇒ 另立工作包。
4. 名册部分既有条目 schema 不全（`evidence` / `next_action` 缺）⇒ orchestrator 走到即抛。
5. `backend/.venv` 未被 gitignore ⇒ push 时**只 add 白名单**。
6. 守护进程重启要等 lease TTL（实测空转 3 分钟）⇒ 已验证「作废旧 lease 心跳」的零空转绕行法，待脚本化 + generation fencing。
7. 接线总账的 FOS trace 源指向 A1 旧快照 ⇒ 曾报「合同链缺 package_service」的**假缺口**（该假缺口已在司仓侧修掉并复算为 0）。
8. 执行器链存在**第二个真相源**（硬编码链 vs 配置文件）⇒ 待收成单一来源（属运行时链语义变更，须独立 Reviewer 过）。
