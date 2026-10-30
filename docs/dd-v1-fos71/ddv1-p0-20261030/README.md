# DD-V1｜PR #86 真机测试缺陷修复｜2026-10-30（P0-1／P0-2 ＋ Gold 缺口 ＋ 分层评分）

**基线（刘江 Windows 实测）**：`d68c5411bcfae5ebca74f2fcc595fea2bed503a2`（PR #86 head）
**来源**：`bog5d/cangjie-teams-channel#108`（刘江 2026-10-30 两条实测评论）＋ 波总同日裁定
**施工分支**：`feat/71-ddv1-p0-fix-20261030`（自上述基线起）
★ **落位说明（如实记账）**：★ 推送助手的目标分支此前是**硬编码**的（我以为可以指定分支、实际被忽略）
⇒ ★ 本轮这一笔提交因此落在 **PR #86 的分支**（`feat/71-ddv1-exam-v1-20261028`）上。
⇒ ★ **处置**：★ **不回退、不改写已落字节**（禁 force／amend）⇒ ★ **另建一个 ref**（`feat/71-ddv1-p0-fix-20261030`）
指向**同一 commit** `ac442ec0048ee30e8fb39564cffd8ea962a7bd7f` ⇒ ★ **两个 ref、同一 commit、同一 tree** ⇒
★ **历史一字未改**；★ 且刘江**继续测 PR #86** 即可拿到本轮修复（与波总「用指定冻结 SHA 重跑」的指令一致）。

---

## 一、两个 P0 的**代码级**根因（本轮坐实，非推测）

### P0-1｜空库假 READY

| 项 | 内容 |
|---|---|
| **现象** | 材料库 0 份、义务 0 条、Gold 映射 0 份时，`preflight` 返回 `READY_FOR_FORMAL_SCORING` |
| **根因** | `dd_v1_exam_preflight_service.py` 的三处检查**只判「在不在」**（`state="FOUND"`），**不判「空不空」** ⇒ 三处都 FOUND ⇒ `ready=True` |
| **另一处** | `dd_v1_gold_service.check_correspondence` 对「`expected_files` 全空」的 Gold **一条问题都不报** ⇒ 对应关系判 `CONFIRMED` ⇒ Gold 侧同样是「在就算好」 |
| **修法** | ①「空」升级为**阻塞事实**：`LIBRARY_EMPTY`／`CHECKLIST_NO_OBLIGATIONS`／`CHECKLIST_ITEM_COUNT_ZERO`／`GOLD_NO_EXPECTED_FILES`／`GOLD_NO_OBLIGATIONS`；② 分项 `problems` **全部进入 `blockers`**（原先只躺在分项里 ⇒ `blocked_by` 为空 ⇒ 读起来像「什么都在」）；③ 状态由**全部阻塞事实按优先级**推导 ⇒ **库/考卷为空时不得把责任说成 Gold 的问题**（`TEST_BLOCKED_EXAM_INPUT_EMPTY`） |
| **三档能力** | 新增 `capability`：`ENGINEERING`（只能工程测试）／`DIAGNOSTIC`（可业务诊断，**结果必须标「非正式评分」**）／`FORMAL_SCORING`（可正式评分） |
| **负例回归** | `backend/tests/test_dd_v1_preflight_p0_empty.py`（**16 条**）：刘江实测那一档（空库＋0 义务＋0 映射）＋ 九类异常逐条 ＋ 三档能力 |
| **变异验证** | 删 `LIBRARY_EMPTY` 闸 → **2 red**；删 `CHECKLIST_NO_OBLIGATIONS` 闸 → **2 red**；删 `GOLD_NO_EXPECTED_FILES` 闸 → **2 red** ⇒ ★ 三道闸**都有判别力**（不是摆设） |

### P0-2｜同一张 42 题考卷，两套拆解（91 vs 15）

| 项 | 内容 |
|---|---|
| **现象** | `dd_v1_manifest.py checklist` ⇒ 91 条义务（覆盖 42 题）；`dd_v1_local_run.py split` ⇒ 15 条（覆盖 12 题）⇒ 覆盖率被低报成 28.6% |
| **根因** | **两套拆解**并存：库侧 `rq.build_obligations`（按并列连接词切，**永不丢题**）vs 运行器侧 `sem.split_items`（按材料类型切，**无材料类型关键词的整题丢弃**） |
| **为什么必须统一到库侧** | ① 库侧**覆盖全部 42 题**；② ★ **Gold 的 `obligation_id` 引的就是库侧那条** ⇒ 运行器用另一套 ⇒ **答卷与标准答案根本对不上**（分数必错） |
| **修法** | ★ **不开发第三套**：库侧那套升为**唯一权威**，新增 `rq.export_obligation_contract()` 导出**统一数据契约**，运行器**消费**它（`dd_v1_local_run.py split/run --library <LIB>`） |
| **统一契约** | 每条义务可追溯：原始题号／归题号／原文／义务唯一 ID＋稳定 key／主体要求／期间要求（含四态 `period_spec`）／文件类型／证据键／处理状态；★ **判不出材料类型只标 `NEEDS_HUMAN_SPLIT`，不删** |
| **题号解析** | 新增 `rq.canonical_question_id()`：★ **分部目录 `1-1_基本资料` 归一为 `1-1`**（**不会**被当成三级题号）；join **两级**（逐字 → 归一）；★ **挂不上的必须显式报出**（`unmatched_items`），**绝不静默丢题** |
| **负例回归** | `backend/tests/test_dd_v1_obligation_contract_wp2.py`（**11 条**）：42 题全覆盖／原文逐字保留／不重复不漏／条数稳定（幂等）／契约字段可追溯／**运行器与库侧逐条一致**／旧路径**覆盖不到 42 题**（证明 P0 量级）／题号归一四例 |

---

## 二、WP3｜Gold 缺口的**逐件**清单（波总裁定第 1 条）

★ 波总要求：「**不删原始 Gold、不把 42 题改成缩小后的总分母、不用缺失项凑 0 分或 PASS**；先列出 11 份缺失、4 份歧义的**逐件清单、原始路径/哈希及对应题号**，排查是路径、文件名、哈希或材料库范围错误」。

⇒ 新增 `gold_svc.gold_gap_report()`：**逐件**输出 `题号 ／ 原始路径 ／ 指纹 ／ 分类 ／ 候选 ／ 修复动作`，分类 A–F：

| 类 | 含义 | 修复动作 |
|---|---|---|
| A | 确实缺料（库里无同内容、无同路径/同名件） | **补料清单**（不得删 Gold） |
| B | 路径解析错误 | 人工纠正映射 |
| C | 文件名匹配错误（同名不同内容） | 人工补正确指纹（**程序不得猜**） |
| D | 哈希/内容识别错（同路径不同指纹） | 人工核对：内容被替换 or Gold 记错 |
| E | 主体/期间/范围错 | 人工核对主体/期间口径 |
| F | Gold 清单需人工确认（无期望文件/无题号） | 人工补 Gold（**不得因此删义务**） |

⇒ 新增 CLI：`dd_team_channel.py gold-report --contract <json> [--library <LIB>]`；⇒ **预检报告里也直接带这张表**（不再只有计数）。

## 三、WP4｜可信评分（三组并列）

⇒ `grade` 的成绩单现在**同时**给三组（`dd_v1_exam_service.py`）：

1. **第一组 · 全卷成绩**：`questions_total`（**分母来源写明**：权威题单 or 仅答卷＋Gold）、已处理／正确／未匹配／歧义／未完成／**全卷可验证覆盖率**，**逐题状态**；
2. **第二组 · Gold 可评分成绩**：可评分义务数（分母）／正确／错误／得分率／**未纳入原因逐条**；
3. **第三组 · 证据差异**：逐项 —— Gold 预期文件／机器实际选择／主体／期间／是否正确／**文件哈希**／**归因**。

★ **分层评分**（波总裁定）：★ **部分缺口 ≠ 全盘不可评分** ⇒ 阻塞分两档：
· **HARD**（考卷/图书馆指纹冲突、无可比基准）⇒ `NOT_SCORABLE`；
· **GAPS**（个别文件缺料/歧义）⇒ ★ **继续出分层成绩单**（`SCORED_PARTIAL`），**保留全卷分母**，缺口逐件列出。
⇒ **不可评分时仍保留量化诊断**（`diagnostic` 块）⇒ ★ 既不是 0 分，也不是「完全没有结果」。

★ **既有硬口径未回退**：0 件交付 ⇒ 总分强制 0（**不是** NOT_SCORABLE）；命中 0 件 ⇒ 总分强制 0。

---

## 四、WP5｜回归与端到端验证（全部合成数据）

| 项 | 读数 |
|---|---|
| **全量回归**（`pytest tests/ --ignore=tests/test_ui_smoke_gk.py`） | **2069 tests ／ 2068 passed ／ 1 failed ／ 0 errors**（唯一红＝`test_doctor_script`（沙箱环境项，CI 显式 ignore））⇒ **零新增失败**（基线 2027／2026／1／0 ⇒ 本轮 **+42 条全绿**） |
| **本轮新增用例** | `test_dd_v1_preflight_p0_empty.py`(**16**) ＋ `test_dd_v1_obligation_contract_wp2.py`(**11**) ＋ `test_dd_v1_gold_gap_and_scorecard_wp4.py`(**15**) ＝ **42 条**（★ 以 `--junitxml` 实测为准；★ **零新增失败**） |
| **合成 42 题端到端** | 建库 84 份材料 ＋ 42 题清单 ⇒ 库侧拆 **42 条义务／42 题**；运行器 `--library` 路径 **42 条／42 题（0 挂不上）**；★ **旧路径对照：21 条／21 题 ⇒ 丢一半题**（与刘江实测 15／12 同形态） |
| **预检 e2e** | 合成 Gold（30 可解析 ＋ 8 缺料 ＋ 2 无期望文件）⇒ 状态 `TEST_BLOCKED_GOLD_BROKEN`、**档位 `DIAGNOSTIC`**、**逐件缺口 10 件**（A_MISSING 8 ＋ F 2） |
| **阅卷 e2e** | 三组：① 题数 42（分母来源 `LIBRARY_OBLIGATION_CONTRACT`）｜已处理 42｜正确 30｜未匹配 0｜未完成 2｜覆盖率 1.0 ② 可评分 32（分母）｜正确 30｜错误 2｜得分率 0.9375｜未纳入 {MISSING_IN_LIBRARY: 8, NO_EXPECTED_FILES: 2} ③ 证据差异 42 条 |
| **合成 run 的总分口径** | ★ `total_score = 0.0`，★ **因为合成答卷的 `delivered_files = 0`** ⇒ 命中既有硬口径「**有效标准答案 ＋ 0 件交付 ⇒ 总分强制 0**（不是 NOT_SCORABLE）」⇒ ★ **这个 0 分与业务成绩无关**，★ 也不代表真实考卷会是 0 分 |

★ 端到端产物：`证据/`（预检 md/json ＋ Gold 缺口 json ＋ 成绩单 json，**全部合成数据**）。
★ ★ **本目录的产物已用**最终代码**重跑一遍**（2026-10-30T12:55Z）：★ **每份产物都对应同一份最终字节**⇒ ★ 目录里**只有一份**成绩单（★ 早期修复过程中的中间产物已删除 ⇒ ★ 避免有人读到**上一轮的旧读数**）。
★ Gold 缺口逐件字段：`item_no`（题号）／`gold_relative_path`（原始路径）／`gold_sha256`（指纹）／`gold_entity`（主体）／`gold_period`（期间）／`gap_class`（A–F 分类）／`candidates`（候选）／`remedy`（修复动作）／`obligation_id`。

## 五、尚未解决 / 如实标注

- ★ **真实 42 题仍未跑**（需刘江在授权 Windows 环境用**新冻结锚点（tag `ddv1-p0-20261030`）** 重跑）⇒ **业务验收未完成**；
- ★ **真实 11 份缺料 ＋ 4 份歧义**仍未逐件核对（工具已就位，需真实 Gold 与真实材料库）；
- ★ **真实 `HARNESS_MODEL` 端到端未测**（沙箱无文本生成 LLM）；
- ★ **UI 烟雾测试未测**（沙箱无 playwright；基线同样炸 ⇒ 环境项）；
- ★ **WINDOWS-HANDOFF §0⑥′ 的措辞与实现不符**（「材料不出本机」 vs 本机 `dsh` 调云端模型）⇒ ★ **本轮已修**：改为「数据流以本机 Harness 的实际实现为准 ⇒ **不保证「材料不出本机」**」，并补授权口径（未授权 ⇒ 只用脱敏/合成数据，真实 42 题记 **BLOCKED**）。

## 六、冻结锚点：为什么把「sha」换成「tag」（★ 本轮踩到的自指坑）

★ 本指南初稿第 3 行写的是「本轮冻结版本＝`<sha>`」⇒ ★ 那个 sha 是**写它的上一笔**的 tip
⇒ ★ **写下这一笔自身就把分支推前一位** ⇒ ★ **那行 sha 从写下那刻起就是移动靶**（永远对不上它自己）。

⇒ **结构性改法**（不是补一次就完）：
1. **冻结锚点＝ tag `ddv1-p0-20261030`**（★ tag 不随分支前进而漂移 ⇒ ★ 刘江拉 tag 永远拿到同一份字节）；
2. **版本核对＝ 内容标记命中**（`LIBRARY_EMPTY` / `export_obligation_contract` / `add_argument("--library"` 三条，各 ≥1 行）
   ⇒ ★ 内容标记不会移动 ⇒ ★ 判据从此稳定（★ 已在 tag 上实测：命中 **3 / 1 / 2** 行）；
3. 「P0 代码引入于哪一笔」的 sha **保留但降级**为历史事实，并**显式否掉「导航」语义**（★ 「不表示当前 head、不要按它导航」）。

## 七、最终 head 上的读数与如实记账

| 项 | 读数（作用域／版本／时刻） |
|---|---|
| **最终 head** | tag `ddv1-p0-20261030`（★ 分支 `feat/71-ddv1-exam-v1-20261028` 与 `feat/71-ddv1-p0-fix-20261030` 同指该 tip） |
| **全量回归** | **2069 tests ／ 2068 passed ／ 1 failed ／ 0 errors**（唯一红＝`test_doctor_script`，沙箱环境项）｜作用域＝`backend/tests/`（`--ignore=tests/test_ui_smoke_gk.py`）｜**版本＝代码提交 `f448d6e`**｜时刻＝2026-10-30T04:48Z |
| **最终 head 的新增用例复跑** | **42 项全绿**（0 failed／0 errors）｜作用域＝本轮三个新测试文件｜**版本＝最终 head 的字节**｜命令：`cd backend && pytest tests/test_dd_v1_preflight_p0_empty.py tests/test_dd_v1_obligation_contract_wp2.py tests/test_dd_v1_gold_gap_and_scorecard_wp4.py --junitxml=…` |
| **代码字节未变** | ★ 自 `f448d6e`（全量所跑的那一笔）到最终 head 的变更面＝**3 个 docs 文件**、**非 docs 路径 0 个** ⇒ ★ **全量读数对最终 head 的代码字节成立** |
| **逐路径核对** | **161/161 一致**（本地 vs 远端 tip）｜★ master `3781311c4b1157c68a0f891506b7c33ab327f7c4` **未动** |

★ ★ **孪生提交（如实记账，不 force 清理）**：★ 我的 REST 推送工具此前**每次重推整条链** ⇒ 远端历史里出现**同一 tree 的重复提交**
⇒ ★ **最终 tree 正确**、**没有** force／amend／改写任何已落字节；★ **判据是最终 tree 与逐路径内容，不是 commit 条数**。
⇒ ★ **工具已改**：★ 推送时只给「上次已推的本地提交..HEAD」这一段 ⇒ ★ 手抄/重推这一类动作在流程里就不存在了。
