# CODEX_TASKS.md — Codex 自动测试任务收件箱

> **Codex 每次拉取仓库更新后，先读本文件，再执行测试。**
> 本文件由 Claude Code 在每次 PR 合并后更新。

---

## 当前版本：v1.8.0 | 最后更新：2026-06-03

---

## ⚠️ 测试执行规则（必读，不可跳过）

> **vitest 单元测试 ≠ 浏览器验收**。vitest 运行在 jsdom 模拟环境里，
> 无法验证真实 Chrome 渲染、CSS 可见性、叠层阻塞、真实点击流程。
> **每次改动了任何前端组件（.tsx/.ts），必须同时跑 Playwright 浏览器冒烟。**
> 「前端已有 vitest 覆盖」不能替代浏览器测试，两者必须都通过。

---

## 第一步：自动化基线（必须全绿才算通）

```bash
# ── 1. 后端单元/集成测试 ──────────────────────────────────────────
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py \
                           --ignore=tests/test_ui_smoke.py -q
# 期望：783+ passed, 0 failed

# ── 2. 本轮新增专项（v1.8.0 gk 模式 机构问答响应引擎 阶段一）──────
uv run --extra dev pytest tests/test_dd_gk_scan.py tests/test_dd_gk_export.py \
                          tests/test_dd_qa_service.py tests/test_dd_gk_api.py \
                          tests/test_dd_gk_password.py -q
# 期望：28 passed（11 扫描 + 4 导出 + 5 问答 + 3 API + 5 密码）

# ── 3. 前端单元测试（jsdom，验证逻辑，不替代浏览器）────────────────
cd ../frontend
npm install   # 依赖有变化时运行
npm test
# 注意：用 `npm test`，不要用 npx vitest run 单跑某文件（jsdom 冷启动偶发不加载）
# 期望：24+ passed, 0 failed

# ── 4. TypeScript 编译 ────────────────────────────────────────────
npm run build
# 期望：exit code 0，无 error（warning 忽略）

# ── 5. 【强制】Playwright 浏览器冒烟 + 带截图 PDF 报告 ───────────
# ⚠️ 关键：这是命令行跑的 Playwright（本地 chromium 子进程），
#    不是 in-app Browser Use，不受 Browser Use URL policy 限制 —— 可正常访问
#    127.0.0.1:8000 / 5173。Codex 之前 in-app browser 被拦的问题，用这条命令绕开。
#
# 必须先启动后端服务（另一终端）：
#   cd backend && uv run uvicorn cangjie_fos.main:app --port 8000
# 再启动前端（另一终端）：
#   cd frontend && npm run dev
# 等服务就绪后执行（-s 让 PDF 路径打印出来）：
cd backend
uv run --extra dev pytest tests/test_ui_smoke.py tests/test_ui_smoke_gk.py -v -s
# 期望：全部 passed；跑完会在 backend/data/ui_reports/ 生成带截图 PDF
#   （每步一帧 + 中文 PASS/FAIL 横幅）。任一步 FAIL → 文件名带 FAILED_ 前缀。
#
# test_ui_smoke_gk.py（gk 尽调向导专项，Claude 已本机真跑通，5 passed / 7 帧 PDF）：
#   Tier A 免数据：尽调入口 / Step1 材料库文件夹+开始扫描+清单 / 关闭无叠层
#   Tier B 播种会话→恢复→Step3：🔒加密锁+密码登记 / 💬草稿+📁按问题归档 / 候选附加
#
# 默认账号（无 .env 时）：gk001 / 123456（auth 内置）；conftest 已自动回退到它。
# 若环境 playwright 默认浏览器版本不匹配/下载被拦，设环境变量指向已装 chromium：
#   PW_CHROME_EXECUTABLE=/path/to/chrome uv run --extra dev pytest tests/test_ui_smoke_gk.py -v -s
```

**FAIL 判定**：上述任一步骤有 failed，或第 5 步因「服务未启动」全部 skip（跳过视为未完成）。

### 📄 回传要求（强制）

跑完第 5 步后，**把 `backend/data/ui_reports/` 下最新生成的 PDF 回传给 Claude**
（贴路径或附件）。这份 PDF 是「模拟人工测试」的可视证据，Claude 会逐帧审 UI
真实渲染。**不回传 PDF = 本轮浏览器验收未完成。**

> 注：命令行 Playwright 是本地 chromium 子进程，**不走 in-app Browser Use 通道**，
> 因此 v1.8.0 验收时 in-app browser 被 Browser Use URL policy 拦住的问题，用这套
> 命令行 smoke 即可绕开 —— Codex 不必再依赖 in-app browser 访问 127.0.0.1。

> 为什么必须 PDF：vitest 跑在 jsdom，看不到真实 Chrome 渲染/CSS/叠层/点击跳转
> （约 30% 真实人工场景测不到）。「vitest 全绿 + build 通过」**不等于**人工验收 PASS。

---

## 第二步：浏览器冒烟——gk 模式尽调向导（Playwright 自动化）

> 这一组已写入 `tests/test_ui_smoke.py`（`TestDueDiligenceWizardSmoke`），
> 跑 `pytest tests/test_ui_smoke.py -v` 自动覆盖，**无需手动点浏览器**。

| 测试方法 | 验收点 |
|---------|--------|
| `test_dd_wizard_button_visible` | 主页有「尽调响应」按钮且可见 |
| `test_dd_wizard_opens_step1` | 点击后 Step 1 出现「材料库路径」字样 |
| `test_dd_wizard_step1_has_scan_button` | Step 1 有「开始扫描」按钮 |
| `test_dd_wizard_step1_has_checklist_upload` | Step 1 有「清单」相关入口 |
| `test_dd_wizard_close_no_overlay` | 关闭向导后无遮罩叠层（Chrome Bug 回归） |
| `test_dd_wizard_session_history_shown` | 向导打开后不崩溃、Step1 稳定渲染 |

**FAIL 判定**：任一用例 FAILED（skip 因服务未起，Codex 必须先起服务）。

---

## 第三步：手动冒烟清单（Playwright 无法覆盖的场景）

> 以下需要真实数据/文件操作，Playwright 无法模拟，由**开发者/QA 人工验**。

### gk — 【v1.8.0】机构问答响应引擎 阶段一

| 能力 | 测试文件（自动化） | 人工验收点（额外） |
|------|---------|--------|
| F1 布局检测+去重+加密标记 | `test_dd_gk_scan.py`（11） | 真实 per_institution 文件夹扫描，徽章显示正确机构数 |
| F2/F5 按问题归档导出 | `test_dd_gk_export.py`（4） | 真实导出后用文件管理器确认目录结构 |
| F4 历史问答复用 | `test_dd_qa_service.py`（5） | 真实补充文档扒取后，草稿答案是否合理 |
| F3 加密密码登记/附带 | `test_dd_gk_password.py`（5） | 真实加密 PDF 流程：登记密码 → 导出「加密文件密码.txt」 |

**⚠️ vitest 覆盖的前端逻辑（不替代浏览器）**：

| 前端能力 | vitest 覆盖 | 浏览器是否已覆盖 |
|---------|---------|--------|
| F1 布局徽章 | `DueDiligenceWizard.layout.test.tsx` | ✅ Playwright `TestDueDiligenceWizardSmoke` |
| F3 加密🔒+密码 | `DueDiligenceWizard.password.test.tsx` | ⚠️ 仅 jsdom，需人工验 |
| F2/F5 按问题归档 | `DueDiligenceWizard.byquestion.test.tsx` | ⚠️ 仅 jsdom，需人工验 |
| F2 多文件附加 | `DueDiligenceWizard.multifile.test.tsx` | ⚠️ 仅 jsdom，需人工验 |
| F4 问答草稿 | `DueDiligenceWizard.qadraft.test.tsx` | ⚠️ 仅 jsdom，需人工验 |

---

### A — 【本轮新增】Pipeline 新增机构入口

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| A1 | 打开页面 → 找到「机构 Pipeline 看板」区块 | 顶部右侧有「➕ 新增机构」按钮（青色圆角） |
| A2 | 点击该按钮 | 弹出创建弹层，有「机构名称」「Pipeline 阶段」「热度」「引荐方」字段 |
| A3 | 填写名称「TestVC」，其他默认，点「✅ 创建机构」 | 弹层关闭，卡片列表顶部出现「TestVC」 |
| A4 | 查看成就墙「路演接触」数字 | 数字比创建前 +1 |
| A5 | 刷新页面，再找「TestVC」 | 卡片仍存在（持久化成功） |

**FAIL 判定**：按钮不存在 / 弹层不出现 / 创建后列表无变化 / 刷新后消失

---

### B — 【本轮修复】线下见面语义：家数 vs 次数

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| B1 | 找任意一个机构卡片，点击编辑 | 编辑弹层打开 |
| B2 | 找「线下会面次数」输入框，填入 **3**，保存 | 保存成功 |
| B3 | 查看成就墙「线下交流」卡片 | 显示 **1家（3次）**，而不是只显示数字 3 |
| B4 | 再找另一个机构，将线下次数设为 **2**，保存 | 成就墙更新为 **2家（5次）** |

**FAIL 判定**：卡片只显示数字 / 无「家」字 / 无括号次数

---

### C — 【本轮修复】DD 手动替换按钮有文字

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| C1 | 打开「📋 尽调响应」→ Step1 扫描任意有文件的文件夹 | 扫描完成 |
| C2 | Step2 粘贴任意需求文本，触发匹配 | 进入 Step3 审核表格 |
| C3 | 查看每行操作按钮区 | 能看到「缺」和「📂 替换」两个文字按钮 |
| C4 | 点「📂 替换」 | 展开内联输入行（含「📁 选择文件」按钮） |

**FAIL 判定**：只有 📂 图标无文字 / 点击无反应

> ✅ **已加自动化兜底**：`frontend/src/components/__tests__/DueDiligenceWizard.step3.test.tsx`
> 通过「恢复历史会话」喂入一条未确认 item，断言「✓」「缺」「📂 替换」三按钮齐全且点替换展开输入行。
> 浏览器只恢复到已确认 session 时可跳过本节，以该 vitest 用例为准。

---

### D — 【本轮修复】成就墙保存后即时刷新

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| D1 | 找一个 NDA 未签的机构，点击编辑 | 弹层打开 |
| D2 | 勾选「NDA 已签」，点保存 | 弹层关闭 |
| D3 | 不刷新页面，直接看成就墙「NDA 签署」 | 数字比保存前 +1（即时更新） |

**FAIL 判定**：数字不变，需手动刷新才更新

> ✅ **已加自动化兜底**（编辑保存路径，不只创建机构）：
> - `frontend/src/components/__tests__/InstitutionList.save.test.tsx`：编辑保存后断言 `onMilestonesChanged` 被调用。
> - `frontend/src/components/__tests__/WarRoomMap.refresh.test.tsx`：`milestoneRefreshKey` +1 时断言重新拉取 `/api/v1/pipeline/milestone-stats`。
> in-app 浏览器对编辑弹层滚动不稳定时，以这两条 vitest 用例为准。

---

### E — 【本轮新增】DD 学习飞轮接通

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| E1 | 完成一次完整 DD 流程：扫描→匹配→Step3 批量确认 | 确认成功 |
| E2 | 访问 `http://localhost:8000/api/v1/institutions/{机构名}/briefing` | JSON 里 `has_history=true` 且 `preferred_paths` 数组有值 |
| E3 | 若机构名留空，检查 Step2 机构名输入框旁边是否有黄色提示 | 出现「⚠️ 建议填写 — 确认记录将关联此机构...」 |

> ⚠️ **字段口径**：briefing API 真实字段是 `preferred_paths`（不是 `preferred_files`）+ `has_history`。

**FAIL 判定**：has_history 始终 false / preferred_paths 始终为空 / 无任何警告提示

---

### F — 【本轮新增】轻量匹配器升级正式尽调

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| F1 | 打开页面中下部「资产台账」→「尽调响应台」区块 | 显示机构名输入和需求文本区 |
| F2 | 填机构名「TestVC」，粘贴任意文本，点「解析并匹配」 | 出现匹配结果 |
| F3 | 查看按钮行 | 能看到「提交确认（X）」和「📋 发起正式尽调」两个按钮 |
| F4 | 点「📋 发起正式尽调」 | 顶部「📋 尽调响应」弹层打开，停在 Step2，清单文本框已预填 |
| F5 | 关闭弹层，再次从顶栏点「📋 尽调响应」 | 弹层打开，回到 Step1，清单为空 |

**FAIL 判定**：无升级按钮 / 打开后停在 Step1 / 清单未预填 / 关闭后再开仍有残留

---

### G — 成就墙 9 节点完整性

| 期望 | 判定 |
|------|------|
| 成就墙显示9个节点：路演接触 · NDA签署 · 线下交流 · 立项 · 内部尽调 · 外部尽调 · 投决过会 · 协议签署 · 交割 | PASS 全部存在，FAIL 缺少任何一个 |
| 每个节点显示「X家」（有单位） | PASS 有"家"字，FAIL 裸数字 |
| 漏斗5段：路演接触/NDA签署/立项+尽调/投决过会/协议+交割 | subtitle 有数字 |

---

### BLOCKED（跳过，非代码问题）

- **路演评分/路演情报**：依赖本机 AI 评估引擎目录配置，与代码无关，不计入本轮
- **GitHub sync**：需要真实 Token（configured=false 属正常，不是 bug）

---

## 评分标准

| 级别 | 标准 |
|------|------|
| **PASS** | 期望行为完全符合 |
| **PARTIAL** | 主要功能工作，有小问题（如文案、样式、非阻塞 bug） |
| **FAIL** | 期望行为不出现，或出现错误/崩溃 |
| **BLOCKED** | 外部依赖未就绪，与代码逻辑无关 |

---

## 历史版本记录

| 版本 | 日期 | 主要内容 | 结果 |
|------|------|---------|------|
| v1.2.0 | 2026-05-31 | 里程碑重排、飞轮接通、升级按钮、共享索引 | PASS 23 / PARTIAL 3 / FAIL 1 / BLOCKED 4 |
| v1.3.0 | 2026-05-31 | 新增机构入口、家/次双显、替换按钮、create修复 | PASS A/B/E/F/G · PARTIAL C/D（浏览器滚动不稳定） |
| v1.4.0 | 2026-05-31 | vitest 兜底 C/D + 修 briefing 字段口径 + 前端依赖安装说明 | PASS（自动化全绿）|
| v1.5.0 | 2026-05-31 | DD 大批量修复：token 溢出/进度条/截断兜底/逐批存储，733 passed | 待验 |
| v1.6.0 | 2026-06-02 | P0 稳健性三补丁：SQLite每日快照备份/匹配异常标failed/LLM宕机降级关键词，744 passed | ✅ PASS |
| v1.7.0 | 2026-06-03 | P1 稳健性四补丁：Token持久化/内存字典上限/LLM Prompt截断/匹配状态DB降级，754 passed | 待验 |

---

### H — 【v1.5.0 新增】尽调响应台 50 条大批量稳定性

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| H1 | 打开「📋 尽调响应」→ Step1 扫描含 20+ 文件的文件夹 | 扫描完成，显示文件数 |
| H2 | Step2 粘贴 **50 条**需求（可用下方样本）→ 点「解析并匹配」 | 解析显示「共 50 项」，进入匹配等待 |
| H3 | 匹配中，观察按钮 | 按钮显示「**匹配中… X/50 项**」动态进度（不再只是转圈） |
| H4 | 等待匹配完成，进入 Step3 | 50 行全部有结果，**不出现全部 confidence=0 的情况** |
| H5 | 查看匹配结果分布 | 高置信度行（绿）/ 低置信度行（红）/ 无匹配行 各有分布，非全红 |
| H6 | 点「提交确认（X）」批量确认高置信度项 | 弹层关闭或确认数更新，不报错 |

**50 条样本文字**（直接粘贴到 Step2 文本框）：
```
1. 近三年经审计财务报告（资产负债表、利润表、现金流量表）
2. 最新一期未经审计财务报表（月报/季报）
3. 公司注册证明文件及营业执照
4. 公司章程及最新修订版
5. 股权结构图（含各层穿透至自然人）
6. 股东名册及持股比例说明
7. 历次股权融资协议及 Term Sheet
8. 现有投资方 VCC/LPA 协议摘要
9. 核心管理团队简历（CEO/CFO/CTO）
10. 董事会成员名单及简介
11. 员工总数及核心团队构成说明
12. 期权激励计划（ESOP）文件
13. 主要产品/服务介绍 PPT 或说明文档
14. 近 12 个月产品路线图
15. 核心技术专利清单及证书
16. 软件著作权登记证书
17. 商标注册证书（境内外）
18. 主要客户合同（脱敏后）
19. 客户名单（Top 20，含收入占比）
20. 收入确认政策说明
21. 主要供应商合同及合作协议
22. 采购条款与定价说明
23. 近 3 年纳税申报表及完税证明
24. 社保缴纳记录（近 12 个月）
25. 公积金缴纳记录（近 12 个月）
26. 银行流水（公司主账户近 12 个月）
27. 贷款合同及还款计划
28. 对外担保情况说明
29. 应收账款账龄分析表
30. 存货明细及减值情况说明
31. 固定资产清单及折旧政策
32. 租赁合同（办公/生产场地）
33. 重大合同清单（金额超 100 万）
34. 关联交易明细及公允性说明
35. 历史诉讼及仲裁记录
36. 监管处罚记录
37. 数据安全合规证明（等保/GDPR 等）
38. 环保合规证明（如适用）
39. 公司战略规划文件（3 年）
40. 市场竞争格局分析报告
41. 目标市场规模及增长预测
42. 商业模式说明文件
43. 定价策略及毛利率分析
44. 销售渠道及分销网络说明
45. 市场营销费用明细
46. 客户获取成本（CAC）及留存率数据
47. 现有融资用途计划书
48. 资金使用进度及里程碑
49. 下一轮融资计划及预期估值
50. 退出机制说明（IPO/并购路径）
```

**FAIL 判定**：匹配中无进度显示 / 50 条全部 confidence=0（匹配全失败）/ 进入 Step3 时页面崩溃

---

### I — 【v1.6.0 新增】P0 稳健性三补丁

> 本组以**自动化测试为权威**（`backend/tests/test_dd_robustness_p0.py`，11 条）。
> 浏览器层面只需确认未引入回归（DD 流程仍可正常跑通一遍即可）。

**自动化验证（必跑）**：
```bash
cd backend
uv run --extra dev pytest tests/test_dd_robustness_p0.py -v
# 期望：11 passed
```

#### I-1 — SQLite 每日快照备份（防数据丢失）

| 检查项 | 期望 |
|--------|------|
| `db_backup.create_snapshot()` | 用 SQLite 在线备份 API 生成一致副本，源库继续写入不影响已生成快照 |
| `db_backup.prune_snapshots(keep=7)` | 超过 7 份时删除最旧的，仅保留最新 7 份 |
| 服务启动后 | APScheduler 注册 `daily_db_backup`（每日 03:00），快照落在 `backend/data/backups/` |

**人工冒烟（可选）**：服务跑起来后，手动调用
`python -c "from cangjie_fos.services.db_backup import run_daily_backup; print(run_daily_backup())"`，
确认 `backend/data/backups/fos_snapshot_*.sqlite` 生成。

**FAIL 判定**：快照不生成 / 快照打不开 / prune 删错文件（删了最新的）

#### I-2 — 匹配中途崩溃标记 failed（不再误当完成）

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| I2-1 | 正常完成一次匹配 | `dd_match_sessions.status = 'matched'` |
| I2-2 | 匹配过程内部抛异常（自动化用 mock 模拟） | `status = 'failed'`，**不是** 'matched' |
| I2-3 | 无已索引文件的空文件夹匹配 | `status = 'matched'`（合法的"无可匹配"，非失败） |

**关键点**：异常时 session 仍到达**终态**（前端轮询不挂死），但终态是 `failed` 而非 `matched`，
便于区分"真完成"与"中途崩溃"。

**FAIL 判定**：异常后 status 仍为 'matched' / 或停在 'pending'/'matching'（前端永久轮询）

#### I-3 — LLM 宕机降级关键词匹配（不再整批归零）

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| I3-1 | LLM 三次重试全失败（自动化 mock client 持续抛异常） | 相关需求项仍被关键词兜底匹配，不是全部 confidence=0 |
| I3-2 | 查看降级匹配项 | confidence ≈ 0.3（红色低置信徽章），reason 含"⚠️ AI暂不可用，关键词匹配" |
| I3-3 | 完全无关键词命中的需求 | 返回空候选（不硬塞错误文件） |

**FAIL 判定**：LLM 宕机时 50 条全部 confidence=0 / 无关键词标注 / 把无关文件硬匹配上去

**自动化兜底文件**：`backend/tests/test_dd_robustness_p0.py`
- 备份：`test_create_snapshot_*` / `test_prune_*` / `test_run_daily_backup_*`
- 失败标记：`test_matching_exception_marks_failed` / `test_matching_success_marks_matched` / `test_matching_no_index_marks_matched`
- 关键词降级：`test_keyword_fallback_unit` / `test_llm_down_falls_back_to_keyword`

---

### J — 【v1.7.0 新增】P1 稳健性四补丁

> 本组以**自动化测试为权威**（`backend/tests/test_p1_robustness.py`，10 条）。

**自动化验证（必跑）**：
```bash
cd backend
uv run --extra dev pytest tests/test_p1_robustness.py -v
# 期望：10 passed
```

#### J-1 — Token 持久化（重启后无需重新登录）

| 检查项 | 期望 |
|--------|------|
| 登录后清空内存 `_sessions` | `get_session(token)` 仍能从 `fos_sessions` 表恢复 session |
| 已过期 token（> 72h）在 DB | `get_session` 返回 None，不恢复 |
| logout 后 | DB 里的 token 也被删除，重启后不可恢复 |

**FAIL 判定**：重启后用户必须重新登录（内存清空后 token 验证失败）

#### J-2 — 内存字典容量上限（防内存泄漏）

| 检查项 | 期望 |
|--------|------|
| `_scan_status` 超过 200 条 | `_evict_oldest()` 自动清除最旧条目，字典长度有界 |
| `_match_status` 超过 200 条 | 同上 |
| 大量新 scan/match 操作后 | 内存字典最终不超过 `_MAX_STATUS_ENTRIES=200` |

**FAIL 判定**：长期运行后 `len(_scan_status)` 或 `len(_match_status)` 无界增长

#### J-3 — LLM Prompt 长度上限（防上下文溢出）

| 检查项 | 期望 |
|--------|------|
| 单条文件摘要 > 150 字符 | `_build_file_list_text()` 截断到 150 字符并加"…" |
| 50 条文件 × 超长摘要 | 文件列表文本总长 < 15000 字符 |

**FAIL 判定**：超长摘要导致 Prompt > 32K 字符，DeepSeek API 整批失败

#### J-4 — 匹配进度 DB 降级（重启后状态不丢失）

| 检查项 | 期望 |
|--------|------|
| 创建 session 后清空 `_match_status` | `GET /sessions/{id}/match-status` 返回 `source=db_fallback` |
| 不存在的 session_id | 返回 `status=not_found`（不报 500） |

**FAIL 判定**：重启后前端查询 match-status 永远返回 not_found，导致进度轮询挂死

**自动化兜底文件**：`backend/tests/test_p1_robustness.py`
- Token：`test_token_survives_memory_clear` / `test_expired_token_not_restored_from_db` / `test_logout_removes_from_db`
- 内存上限：`test_scan_status_dict_capped` / `test_match_status_dict_capped` / `test_evict_removes_oldest_entries`
- Prompt 截断：`test_long_summary_truncated_in_file_list` / `test_prompt_total_length_bounded`
- DB 降级：`test_match_status_db_fallback` / `test_match_status_not_found_for_unknown_session`
