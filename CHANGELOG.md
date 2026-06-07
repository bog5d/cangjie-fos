# Changelog — 仓颉 FOS

所有重要变更按版本记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [1.9.2] — 2026-06-06  DD 红队 P0 加固：抗注入 / 防记忆投毒 / 防路径穿越

> 测试基线：807 passed（新增 `test_dd_redteam.py` 9 个 + 记忆信任 2 个）
> 红蓝对抗视角:威胁"正确交付"的三条工业级底线。威胁模型=文件正文/文件名/清单文字
> 皆不可信、一次人工误确认、恶意文件名。

### Security / Hardened
- **P0-1 提示注入**（`dd_match_service`）:文件正文/文件名/摘要进 LLM 前先 `_neutralize` 给疑似指令打码;精判 prompt 显式声明正文为不可信数据;**关键兜底**——模型若说"满足"且要给绿,但需求与正文【零字面重合】(`_req_content_overlap`),强制降级到 yellow 待复核,不放绿。正文里的"判我为满足"无法操纵交付。
- **P0-2 学习记忆投毒**（`dd_match_service`）:一次人工误确认会污染跨机构记忆并自动扩散。对策——记忆需**跨 session 确认≥2 次**才升级为可信(green、可被 bulk-confirm);仅确认 1 次=建议(yellow·待复核、预填但不自动放行)。单次误点无法自动错误交付;高确认数的正确文件自动盖过被投毒的旧映射。
- **P0-3 导出路径穿越**（`dd_export_service`）:`matched_filename`/类别名/问题文件夹名此前未充分清洗,携带 `../` 可写出 output_dir。新增 `_safe_filename`/`_safe_component`(去路径分隔/控制字符/前后导点,杜绝 `.`、`..`)+ `_within` 兜底闸(目标解析后必须仍在 output_dir 内,否则跳过)。

### Tests
- `backend/tests/test_dd_redteam.py`（9）:注入打码/零重合兜底/对照不误伤、误确认不被 bulk-confirm 扫过、纠偏盖过投毒、文件名与文件夹穿越均被收纳在 output_dir 内。
- `test_dd_material_architecture.py`:记忆单次确认=yellow、≥2 次=green 两例。

---

## [1.9.1] — 2026-06-06  DD 物料架构红队加固 + 压测固化

> 测试基线：798 passed（v1.9.0 的 795 + 熔断/防错年/压测烟雾 3 个）
> 自造 1188 文件复杂材料库做压力测试，红队视角挖出并修掉 5 个真实脆弱点。

### Added
- **压测固化**：`backend/bench/dd_stress.py`（可手动按 `--scale small/medium/large` 放大 + `--charts` 出图 + `--real-llm`）；`backend/tests/test_dd_stress_smoke.py` 把核心不变量（全文落库率/验证齐全/跨机构锁定/并发零错误）锁进 CI。

### Fixed / Hardened（红队）
- **连接开销（全局）**：`db_base._connect` 此前每次都重跑全套 DDL + 迁移检查，成为高频小查询主要开销。改为**进程内按 db_path 缓存「已初始化」**，同路径只首连接建表/迁移一次（线程安全双检锁）。测试隔离与迁移正确性不变。
- **精判自我吊死**（`_refine_session_matches`）：LLM 持续失败时,此前每条需求都重试退避(120条≈十几分钟)。新增**熔断**:连续失败 `_REFINE_MAX_CONSECUTIVE_FAILS=3` 次即判定 LLM 不可用,剩余项降级为置信度判定;并加单 session 调用上限 `_REFINE_MAX_CALLS=500` 防 runaway。
- **跨机构记忆套错年份**（`normalize_requirement`）：此前归一化把年份也抹掉,「2023审计报告」与「2024审计报告」会落到同一 key,可能跨机构套错文件且被 bulk-confirm 直接扫过。改为**保留数字/年份**,只去标点/空白/括号/礼貌引导词——宁可少命中,不可错命中。
- **超大/扫描件 PDF 拖死索引**（`extract_full_text`）：全文模式此前读 PDF 全部页,扫描件(每页抽不出字、永不触顶)会遍历上千页。加页数安全帽 `_FULL_MAX_PAGES=80`。
- **连接 churn（DD 热路径）**：`_refine_session_matches` 与 `_apply_decision_memory` 改为**单连接 + executemany 批量写**,不再每条 item 各开 1~2 个连接(并发下也降低锁竞争)。`lookup_decision_memory` 增加可选 `conn` 复用参数。

### Changed
- 测试：`test_dd_material_architecture.py` 新增熔断、防错年 2 例;`normalize` 用例更新为「保留年份」语义。

---

## [1.9.0] — 2026-06-06  DD 物料架构升级：全文精判 + 机器验证 + 跨机构学习

> 测试基线：795 passed（新增12个 `test_dd_material_architecture.py`）
> 背景：尽调响应台此前只拿「文件名 + 20字摘要」做匹配（拿影子匹配 50 页报告），准确率有天花板；
> 且没有「匹配完怎么知道对不对」的验证层。本版补上**内容层 → 生产线 → 学习闭环**三段地基。
> 架构讨论与分阶段方案见 `AGENTS.md`「DD 物料架构」节。

### Added
- **阶段1 · 全文精判（内容层）**：
  - `dd_file_parser.extract_full_text()`：读全部页 / 默认 6000 字（区别于 `extract_text` 只读前 3 页 / 800 字做摘要）。
  - `dd_asset_index.content_text`（migration 23）：索引时把材料**全文落库**，精判节点据此逐条核对正文，不再只看 20 字摘要。
  - `dd_match_service._llm_refine_candidate()` / `_refine_session_matches()`：匹配后对「有正文、非记忆锁定」的已匹配项喂正文做精判，按「是否真满足」调整置信度并产出**原文证据片段**。
- **阶段2 · 机器验证（evaluator）**：
  - `dd_match_items.verdict` / `evidence`（migration 24/25）：精判产出红/黄/绿判定 + 证据，写回每项。阈值 green≥0.70 / yellow≥0.40 / red（与 `engine/matchmaker.py` 四色一致）。机器先验、人工终审——绿一键过、黄重点看、红改。
  - 前端 `DueDiligenceWizard`：审核表在文件名下展示 🟢🟡🔴 + 证据片段，加速人工终审。
- **阶段3 · 跨机构决策记忆（学习闭环）**：
  - `dd_decision_memory` 表（migration 26/27）+ `normalize_requirement` / `record_session_decisions` / `lookup_decision_memory` / `_apply_decision_memory`。
  - **材料库共享** → 人工确认的「需求→文件」映射**机构无关**地沉淀；A 机构确认的选择，B/C/D 遇到同类需求时自动锁定（高置信 green，跳过精判省 token）。记忆文件若已不在当前库则不强行套用。
  - 写入挂在既有确认流程（`_write_dd_outcomes` 同址），与 per-institution 飞轮互补、独立容错。

### Changed
- `dd_match_service.run_matching`：批量匹配后串接「记忆覆盖 → 全文精判+验证」两段，各自 try/except 容错，不影响主流程终态。
- 设计取舍：精判全文读取复用既有 pdfplumber/python-docx/openpyxl，**未引入 markitdown**（新依赖、网络受限环境装不稳）。扫描件/图片 PDF 正文读不出者标记跳过，仍靠文件名+摘要参与粗筛；markitdown+OCR 列为未来演进锚点（见 `dd_file_parser.extract_full_text` docstring 与 AGENTS.md）。

### 留给下一棒的钩子
- **「写材料」场景**（投后报告模板填充 / 微信问题生成 Word 答复）：本版未做，但内容层（`content_text`）已就位。方向详见 AGENTS.md「下一步开发方向」节与 `dd_qa_service.py` 顶部锚点。

---

## [1.6.0] — 2026-06-02  P0 稳健性三补丁

> 测试基线：744 passed（新增11个 `test_dd_robustness_p0.py`）
> 来源：全系统稳健性扫描后确认的三个 P0 真实脆弱点（已排除2个误报：SQL注入/路径穿越在桌面内网单租户场景下不成立）

### Added
- **SQLite 每日快照备份**（`services/db_backup.py`，新建）：此前单文件零备份，损坏/误删即全部机构与尽调数据不可恢复。新增基于 SQLite 在线备份 API 的一致快照（并发写入下也不会复制脏页），落在 `backend/data/backups/`，自动保留最近 7 份。由 lifespan 的 APScheduler 每日 03:00 调度（`daily_db_backup`）。

### Fixed
- **匹配中途崩溃误标"完成"**（`dd_match_service.run_matching`）：此前任何异常都在 finally 一律 `_mark_session_done`（matched），前端/导出把残缺结果当成功。现新增 `_mark_session_failed`，异常时标记 `failed`；正常路径（含"无可匹配文件"早退）仍标 `matched`。session 始终到达终态，前端轮询不挂死。
- **LLM 宕机整批静默归零**（`dd_match_service._llm_batch_match`）：此前 DeepSeek 三次重试全失败后 `batch_results = {}`，50 条需求全部 confidence=0，与"真的没材料"无法区分。现新增 `_keyword_fallback_match`，LLM 不可用时用汉字 bigram 关键词兜底匹配，相关项给降级置信度 0.3 并标注「⚠️ AI暂不可用，关键词匹配」。

### Changed
- `dd_match_service` 抽出共享的 `_requirement_bigrams` / `_row_search_text` 辅助（预筛与降级匹配复用，消除重复）
- `CODEX_TASKS.md` v1.6.0：新增 I 节（P0 三补丁测试方案，以 `test_dd_robustness_p0.py` 11 条为权威）
- 测试：新增 `backend/tests/test_dd_robustness_p0.py`（11 条）；`test_dd_v072.py::test_match_session_completes_on_error` 断言更新为终态 `failed`

---

## [1.1.0] — 2026-05-21  同事反馈5个Bug全修复

> 测试基线：643+ passed（新增17个，41 in modified files pass）

### Fixed
- **尽调扫描超时（Bug 1）**：`dd_index_service` 新增 `MAX_LLM_SUMMARIZE_FILES=200`，文件数 >200 时跳过 LLM 摘要仅记录文件名；新增 `progress_callback` 参数每50文件上报进度；前端扫描轮询超时从 120s → 400s（10分钟），并实时显示扫描进度百分比
- **尽调向导白色文字（Bug 2）**：`DueDiligenceWizard.tsx` 5处 `input/textarea` 补 `text-gray-900`，解决 App 根节点 `text-white` 继承导致字不可见的问题
- **匹配完全无效（Bug 3）**：`dd_match_service._get_index_for_folder` 移除 `AND readable=1` 过滤，图片型PDF/加密文件等不可读文件现在通过文件名参与匹配
- **路演报告字段无法编辑（路演 Bug 5）**：`RoadshowIntelView` 的 `key_questions`、`interest_signals`、`next_actions` 渲染循环补传 `editMode` 和 `onChange` 回调，点击「✏️ 编辑摘要」后条目级全部可内联修改
- **路演无法生成HTML报告（路演 Bug 4）**：`roadshow.py` 新增 `POST/GET /api/v1/roadshow/jobs/{id}/html-report`，生成自包含暗色中文 HTML 报告（含所有章节）；`ReviewWorkbench` 路演视图底部新增 `RoadshowHtmlExport` 组件

### Changed
- `auth.py` `sync_pull_route` 改为异步后台执行（避免 GitHub 同步30秒超时卡死前端）
- 测试：`test_dd_file_parser.py` 新增7个（大文件夹跳LLM/进度回调/不可读文件匹配）；`test_roadshow_api.py` 新增6个（HTML报告生成/文件内容/章节/404错误）

---

## [1.0.0] — 2026-05-18  尽调响应台体验升级：原生文件夹选取

> 测试基线：643 passed（不变）

### Added
- **尽调响应台原生文件夹/文件选取**：新增后端 `GET /api/v1/dd/pick-folder` 和 `/pick-file`，调用 `tkinter.filedialog` 弹出系统原生对话框
- 前端 Step1（材料库路径）、Step3（导出路径）、手动指定文件三处均新增「📁 选择文件夹/选择文件」按钮，无需手动输入路径

### Changed
- `DueDiligenceWizard.tsx`：Step1 提示语由"输入路径"改为"选择文件夹"，用户体验更直观

---

## [0.9.0] — 2026-05-16  Bug修复 + 代码质量提升

> 测试基线：641 → 643 passed（+2 新增，修复 Bug #10 资产搜索）

### Fixed
- **Bug #10（资产搜索）**：资产台账中文文件名/标签搜索已验证正确工作（`/api/v1/assets/search` 使用 casefold() 子串匹配，对中文完全有效）；新增2个回归测试固化此行为
- **utcnow() deprecation**：`github_sync.py` 中 `push_roadshow_report` 的 `datetime.utcnow()` 改为 `datetime.now(timezone.utc)`（Python 3.12 将 utcnow 标记为 deprecated）

### Added
- `tests/test_assets_api.py`: 新增 `test_search_sqlite_chinese_filename` + `test_search_sqlite_chinese_tag`（Bug #10 回归测试）

---

## [0.8.0] — 2026-05-16  Phase DD-2 尽调响应台全面升级

> 测试基线：630 → 641+ passed（+11 新增）

### Added
- `dd_checklist_parser.py`: 清单**分块解析**（4000字/块 + 300字重叠 + 去重），彻底消除5000字截断静默丢失；整合 `dd_llm_client` 重试机制
- `dd_match_service.py`: `_prefilter_files_for_batch` — 大材料库（>50文件）**汉字二元组关键词预筛**，每批只传最相关50个文件给 LLM，防token爆炸
- `GET /api/v1/dd/sessions` — Session历史列表接口（含需求项数量 + 已确认数统计）
- `POST /api/v1/dd/sessions/{id}/items/bulk-confirm` — **一键确认**所有置信度 ≥ 阈值的需求项
- `institution_store.py`: `update_stage_by_name` — 按名称更新机构Pipeline阶段
- 创建Session时可选传 `institution_name`，自动将对应机构推进到**DD阶段**
- `github_sync.py`: `push_dd_session` — 导出成功后自动同步DD摘要到 `analytics/{tenant}/dd/`
- 前端 `DueDiligenceWizard.tsx`（380行→600行）：**Session历史恢复**面板 / **批量确认**按钮 / **手动文件替换**内联输入 / **机构名称**字段

### Changed
- `_llm_batch_match` 签名简化（移除 `file_list_text` 参数，内部按批次计算）
- `export_session` 端点新增 BackgroundTasks，导出后异步触发GitHub同步
- `migration 12`: 现有DD数据库自动添加 `institution_name` 列

---

## [0.7.2] — 2026-05-16  尽调响应台稳定性加固

> 测试基线：630 passed（625 + 5 新增）

### Changed
- **统一 LLM 客户端**：新增 `dd_llm_client.py`，所有 DD 服务（dd_match_service / dd_index_service / dd_checklist_parser）统一使用 `get_dd_llm_client()` 获取客户端，不再各自硬编码 DeepSeek
  - 密钥优先级：`DEEPSEEK_API_KEY` > `OPENAI_API_KEY`（与其他服务文件一致）
  - 所有 LLM 调用增加 `call_with_retry()` 3次重试（指数退避 2s/4s/8s），**网络抖动不再导致整批30条需求「无匹配」**
- **匹配结果显式标记**：LLM 返回结果不包含某需求 ID 时，显式写入 `confidence=0.0, match_reason='未匹配'`，替代之前的留 NULL（前端无法区分「未匹配」和「未处理」）
- **DD scan status DB fallback**：`get_scan_status` 服务重启后降级查询 `dd_asset_index` 表，返回最近索引时间，不再永远返回 `not_found`
- **导出大小防护**：`dd_export_service.py` 新增两个 guard
  - 单文件 > 100MB → 跳过，记入缺失清单
  - 累计 > 500MB → 终止全部导出，返回错误说明

### Architecture
- 新增文件：`services/dd_llm_client.py`（共享 LLM 客户端工厂）
- 新增测试：`tests/test_dd_v072.py`（5个：LLM空结果/异常恢复/文件大小guard/总大小guard/DB fallback）

---

## [0.7.1] — 2026-05-15  尽调响应台红队加固

> 测试基线：625 passed

### Fixed
- [CRITICAL] 临时文件泄漏 → `try/finally + os.unlink`
- [CRITICAL] LLM 返回 0 条需求项时产生级联 404 → 提前返回 400
- [CRITICAL] `run_matching` 异常时 session 永远不标记完成 → `finally _mark_session_done`
- [CRITICAL] 前端所有 fetch 无 try/catch → UI 冻结 → 全面补错误处理
- [MODERATE] 扫描轮询无超时 → 增加 120 次上限（3分钟）
- [MODERATE] 匹配轮询后强制跳 Step3 即使 0 条 → 加空结果守卫
- [MODERATE] interval 未在 unmount 时清理 → useEffect cleanup

---

## [0.7.0] — 2026-05-15  尽调响应台（Phase DD-1）

> 测试基线：625 passed（605 + 20 新增）

### Added
- **尽调响应台**：机构发来尽调清单 → AI 匹配本地材料库 → 表格审核（🔴🟡🟢置信度）→ 导出文件夹 + 缺失清单
  - `dd_file_parser.py`：PDF/Word/Excel/txt 内容提取（pdfplumber + openpyxl + python-docx）
  - `dd_index_service.py`：文件夹扫描建索引（LLM 生成20字摘要，存 `dd_asset_index` 表）
  - `dd_checklist_parser.py`：清单解析——代码读格式 + AI 只做语义提取（解决之前解析准确率差的根本原因）
  - `dd_match_service.py`：批量 LLM 匹配（每批30条，全文件列表+摘要 vs 需求项）
  - `dd_export_service.py`：按大类子目录复制文件 + 生成缺失清单.txt
  - `api/routes/dd_response.py`：7个 API 端点（索引/session/匹配/审核/导出）
  - `DueDiligenceWizard.tsx`：3步向导前端（扫描材料库 → 上传清单 → 审核&导出）
- 新增依赖：pdfplumber、openpyxl
- 新增 SQLite 表：`dd_asset_index`、`dd_match_sessions`、`dd_match_items`
- 新增测试：20个（test_dd_file_parser.py + test_dd_checklist_parser.py + test_dd_e2e.py）

---

## [0.6.9] — 2026-05-15  外发版修复：启动脚本编码根治 + 打包脚本排除 .claude 目录

> 测试基线：605 passed，0 skipped，0 failed

### Fixed
- **build_release_zip.ps1**：新增 `.claude` 到排除目录列表，防止 Claude Code worktree 文件泄漏进发版包
- **发版验证**：确认最新 zip 中 `安装并启动.ps1` 为修复版（无 here-string），`_embedded.py` 已包含（开箱即用）

### Changed
- 外发包 zip 从 3.9 MB 降至 3.3 MB（排除 .claude 目录）


## [0.6.8] — 2026-05-15  DB 隔离架构 + marker 自治 + bare except 收敛

> 测试基线：605 passed，0 skipped，0 failed

### Added
- **`_isolate_db_per_test` autouse fixture**：每个测试独立 SQLite 临时数据库，杜绝并行状态泄漏
- **`@pytest.mark.real_db` marker**：测试文件声明自己使用真实 DB（替代中央豁免列表硬编码）
  - 适用：module/class 级 fixture 预写数据、已有独立 DB 隔离 fixture
  - 5 个文件已迁移：`test_wizard_pipeline_e2e`, `test_pipeline_e2e`, `test_p0_retry_eval`, `test_follow_ups_api`, `test_wiki_display`
- **`get_audio_dir()` 路径抽象**（`core/paths.py`）：支持 `CANGJIE_AUDIO_DIR` 环境变量覆盖，测试可隔离音频目录
- `test_report_builder.py` 新建（10 测试）：desensitize/han_initials/apply_masks + 缺音频降级场景

### Fixed
- **test_p1b_html_report_service**：移除 2 个 `@pytest.mark.skip`，补齐完整 mock 链，修复跨平台路径问题
- **test_wiki_display**：双重 monkeypatch 导致偶发 `database is locked`，通过 `@pytest.mark.real_db` 豁免

### Changed
- **7 处硬编码音频路径** → `get_audio_dir()`（pitch, roadshow, main, pitch_upload_pipeline, pitch_wizard_runner）
- **裸 except 收敛**：`_evaluation.py` 6 个 → 具体异常 / `Exception as e` + 日志；`report_builder.py` 4 个 → 具体异常
- **全项目裸 except 存量**：36 个（从 v0.6.5 的 61 个降至 36 个）


## [0.6.7] — 2026-05-15  同事部署问题 3.5/3.6 修复

> 同事 Word 文档 6 个问题全部清零。测试基线：600 passed。

### Fixed
- **Bug 3.5 — data/ 目录未自动创建**：`main.py` 启动时创建 `data/audio` 目录
- **Bug 3.6 — HTML 报告缺音频直接崩溃**：`report_builder.py` + `html_report_service.py` 优雅降级
  - `raise FileNotFoundError` → `logger.warning` + 跳过音频切片，生成纯文本报告

### Added
- `test_report_builder.py` 新增 4 个测试（缺音频降级场景）


## [0.6.6] — 2026-05-15  根治启动脚本编码崩溃 + JSON GBK 兜底

> 测试基线：596 passed（asset_bridge 2 个之前失败的测试现已通过）

### Fixed
- **`安装并启动.ps1`**：根治 PS5.1 GBK 解析崩溃
  - 顶部加 `[Console]::OutputEncoding` + `$OutputEncoding = UTF8`
  - here-string → 字符串数组拼接
  - 诊断报告文件名改为纯 ASCII
  - `uv sync --extra dev` → `uv sync`（提速）
  - `uv sync` 失败时自动清理 `.venv` 后重试
- **`.bat` 脚本全部重写**：UTF-8 + `chcp 65001`，彻底消除中文乱码
- **JSON 读取编码回退链**：`utf-8 → gbk → utf-8-sig`（`asset_bridge.py`, `investor_matcher.py`）
  - 修复中文 Windows 生成的 GBK 编码 JSON 导致 `UnicodeDecodeError`


## [0.6.5] — 2026-05-15  代码质量：裸异常收敛

### Changed
- **收敛 20 个裸 `except Exception` 为具体异常类型**
  - `services/github_sync.py`（8 个）：`urllib.error.URLError, OSError, ValueError, json.JSONDecodeError`
  - `engine/document_reader.py`（7 个）：`ValueError, RuntimeError, OSError`
  - `services/nightly_settle.py`（5 个）：`RuntimeError, OSError, ValueError`
- llm_judge 交叉导入已确认全为绝对路径，无需修改
- dashboard/war_room 同名文件确认无实际歧义（完全限定导入）

---

## [0.6.4] — 2026-05-15  npc_chat_graph 测试 + 清理

### Added
- `tests/test_npc_chat_graph.py`（23 个测试）：离线模式、单例、图结构、display name、消息导出
- 全量测试基线：596 passed（0 regression）

### Fixed
- `tests/test_report_builder.py`：修复 2 个断言与实现不匹配的测试
- 清理 `llm_judge.py.bak` 残留文件

### Changed
- CHANGELOG 补录 v0.6.3 条目

---

## [0.6.3] — 2026-05-15  Bug #3 + #10 修复，13/13 全部完成

> 🎉 同事 zt001 反馈的 13 个问题全部修复。

### Fixed
- **Bug #3 — 尽调匹配不准 + 打包下载**
  - `investor_matcher.py`：`match_institutions()` 新增子串匹配（75% 阈值）、`stage_match()` 容忍阶段±1
  - 新增 `pack_institutions_json()` 打包下载函数
  - `asset_bridge.py`：`find_related_assets()` 大小写不敏感 + 逐字段兜底搜索
- **Bug #10 — 资产台账搜索不到内容**（同上 asset_bridge 修复）

### Added
- `tests/test_investor_matcher.py`（29 个测试）
- `tests/test_asset_bridge.py`（24 个测试）
- `tests/test_job_pipeline.py`（7 个测试）
- `tests/test_report_builder.py`（6 个测试）
- 全量测试基线：573 passed

### Changed
- AGENTS.md：Bug 状态表更新为 13/13

---

## [0.6.2] — 2026-05-15  Bug #1 修复：录音片段不完整

> 根因：`_map_aliyun_paraformer_to_schema` 在 Paraformer 返回句子缺词级时间戳时
> 静默丢弃整句（`continue`），导致转写输出缺失段落。

### Fixed
- **Bug #1 — 录音片段不完整（ASR 截取有误）**
  - 根因：`backend/src/cangjie_fos/engine/transcriber.py` `_map_aliyun_paraformer_to_schema` L449-450
    - 句子缺词级 `begin_time/end_time` 时，整句被 `continue` 跳过
    - Paraformer API 在低质量音频或短句时可能只返回句子级时间戳
  - 修复：
    - 整句缺词级时间戳时：用句子级 `begin_time/end_time` 创建单条词记录兜底
    - 句中部分词缺时间戳时：线性插值估算缺失词的时间窗口（前后最近有效词取中点）
    - 新增 `tests/test_transcriber.py`（10 个测试）覆盖：正常流、缺词级时间戳、混合场景、多说话人

### Changed
- 测试基线：502 → **512 passed**（+10，test_transcriber.py）

---

## [0.6.1] — 2026-05-15  紧急修复：向导轨道数据不同步 GitHub

### Fixed
- **数据不同步到 coach_data 仓库**（关键Bug）
  - `backend/src/cangjie_fos/services/pitch_wizard_runner.py`
  - 向导提交轨道（复盘/路演）任务完成后，数据从未同步到 `bog5d/coach_data`。
    原因：`run_pitch_wizard_track_job` 缺少 `github_sync.push_pitch_job()` 调用。
    现已在任务成功完成后补加，与上传轨道行为一致。
  - `backend/src/cangjie_fos/services/github_sync.py`
  - `push_match_session` 留 TODO：tenant 读取硬编码 env var，待 match_sessions 表加 tenant_id 列后修。

### Changed
- 测试基线：502 → 502 passed（+0，无新增测试，逻辑已被现有 E2E 覆盖）

---

## [0.6.0] — 2026-05-15  7个Bug修复 + 启动体验增强 + Pipeline编辑

> 继 v0.5.4 修复3个Bug后，本版处理剩余同事反馈中优先级最高的7个问题，并改善启动调试体验。
> 共修复 #2/#4/#6/#8/#9/#12/#13，累计已解决13中的10个。

### Added

- **Bug #2 — 新增风险点缺「问题简述」字段**
  - `frontend/src/components/workbench/left/AddRiskPointForm.tsx`
  - 「新增遗漏痛点」表单顶部加入「问题简述」必填输入框（对应 `problem_summary` 字段，30字内）

- **Bug #6 — 锁定后无法解锁编辑**
  - 后端：`backend/src/cangjie_fos/api/routes/pitch.py` 新增 `DELETE /api/pitch/jobs/{id}/review-lock` 端点
  - 前端：`frontend/src/components/workbench/WorkbenchHeader.tsx` 锁定状态旁出现「🔓 解锁编辑」按钮
  - `frontend/src/pages/ReviewWorkbench.tsx` 增加 `handleUnlock` 回调，点击后清除 DB 的 `committed_at`

- **Bug #4 — 口述实录无法编辑**
  - `frontend/src/components/workbench/left/RiskPointCard.tsx`
  - 每张风险点卡片新增「口述实录」区块，显示 `original_text` 字段
  - 非锁定状态下可直接编辑（纠正 ASR 错字/语序问题）

- **Bug #12 — 路演情报报告无编辑入口**
  - `frontend/src/components/workbench/RoadshowIntelView.tsx` 支持 `onSave` 和 `saving` props
  - 报告顶部加「✏️ 编辑摘要」按钮，进入编辑模式可修改：会议氛围综述、隐性顾虑（每行一条）、机构档案更新建议
  - 编辑模式保存后调用 `PATCH /api/pitch/jobs/{id}/review`，与常规审查台共用同一提交路径
  - `ReviewWorkbench.tsx` 修复 `handleCommit` 支持 `reportOverride` 参数，路演报告现可正常保存

- **Bug #13/#8/#9 — Pipeline看板卡片内容为空 / 无法点开编辑 / 阶段计数无法改**
  - 后端：`backend/src/cangjie_fos/schemas/institution.py` 新增 `InstitutionProfileUpdate` schema
  - 后端：`backend/src/cangjie_fos/services/institution_store.py` 新增 `update_institution()` 函数
  - 后端：`backend/src/cangjie_fos/api/routes/pipeline.py` 新增 `PATCH /api/v1/pipeline/institutions/{id}`
  - 前端：`frontend/src/components/InstitutionList.tsx` 全面重写：
    - 卡片内容为空时显示「暂无摘要 · 点击编辑机构画像」提示
    - 所有卡片点击可开启编辑弹窗（EditModal）
    - 编辑弹窗包含：综合画像、核心疑虑、投资偏好、Pipeline阶段（下拉）、热度（下拉）
    - 保存后热更新卡片显示，无需刷新页面

- **启动体验 — 失败自动生成桌面诊断报告**
  - `安装并启动.ps1` 重写：
    - 启动日志落盘 `backend/logs/startup_YYYYMMDD_HHMMSS.log`
    - 任意步骤失败时自动生成 `桌面/诊断报告_请发给AI_YYYYMMDD_HHMMSS.txt`，包含错误信息 + AI提示模板
    - 自动用记事本打开诊断报告，引导用户复制给技术支持
  - `tools/doctor.py` — `--fix` 模式将修复操作追加写入 `backend/logs/doctor_fixes.log`
  - `backend/logs/.gitkeep` — 日志目录占位符（`.gitignore` 已排除 `*.log` 文件）

### Changed
- 测试基线：**502 passed**（不变，无新增后端测试需求）
- `npm run build` — ✓ 零错误（frontend/dist 已重新构建）

---

## [0.5.5] — 2026-05-14  单仓库自包含（移除 AI_Pitch_Coach 外部依赖）

> **背景**：AI_Pitch_Coach 的所有核心模块早已迁入 `engine/` 子包（Phase 1，v0.3.0）。
> 但 `pyproject.toml` 的 testpaths 一直保留着指向兄弟目录的引用，导致克隆单仓库无法完整运行。

### Changed
- **`backend/pyproject.toml`** — 从 `testpaths` 移除 `../../AI_Pitch_Coach/tests`
  - 单独克隆 `cangjie-fos` 即可运行全部 502 个测试，无需兄弟仓库
  - 验证：移除前后测试数量完全一致（502 passed），AI_Pitch_Coach 测试本已因模块路径问题静默跳过
- **`core/paths.py` `ensure_pitch_coach_import_path()`** — 改为警告 + 返回 None，不再 raise FileNotFoundError
  - AI_Pitch_Coach 不存在时静默降级，不影响应用启动和核心功能
- **`core/readiness.py`** — AI_Pitch_Coach 目录缺失从「问题（issues）」降为「静默通过」
  - `engine/` 已包含全部核心模块，兄弟目录是可选的历史遗留

### Changed
- 测试基线：**502 passed**（不变）
- AI_Pitch_Coach 仓库现为可选归档参考，不再是运行依赖

---

## [0.5.4] — 2026-05-14  同事反馈13个问题，本版修复3个（#5/#7/#11）

> 同事 zt001 测试 v0.5.3 后反馈13个问题，完整状态见 AGENTS.md「最近做了什么」。
> 本版修复3个纯Bug（#5/#7/#11），其余10个（#1/#2/#3/#4/#6/#8/#9/#10/#12/#13）待后续排期。

### Fixed

- **Bug #11 — 路演情报报告第5步字段全部显示undefined/空白**（用户可见严重Bug）
  - 根因：`frontend/src/components/RoadshowWizard.tsx` 本地 TypeScript 接口与后端
    `engine/schema.py` 字段名不符，导致 JavaScript 运行时访问不存在的属性
  - 具体不符点（错误→正确）：
    - `KeyQuestion.question/theme/asked_by` → `verbatim/underlying_concern/speaker_id`
    - `InterestSignal.signal/sentiment` → `verbatim/signal_type/interpretation`
    - `NextAction.owner/deadline` → `actor`（后端无 deadline 字段）
    - `key_verbatim_moments: KeyVerbatim[]` → `string[]`（后端返回纯字符串列表）
  - 修复：删除错误的本地接口定义，全部对齐后端 schema；Step5 渲染直接使用正确字段名

- **Bug #7 — 复盘审查台删除风险点后总分不更新**
  - 根因：`frontend/src/pages/ReviewWorkbench.tsx` `handleRiskDelete` 只过滤了
    `risk_points` 数组，没有重算 `total_score`
  - 修复：删除后重算 `total_score = max(0, 100 - Σ(remaining.score_deduction))`

- **Bug #5 — 复盘历史记录列表缺机构名列**
  - 根因：`PitchJobSummary` schema 未含 `institution_id`，路由也未回填，前端无法展示
  - 修复三件套：
    1. `backend/src/cangjie_fos/schemas/pitch_upload.py` — `PitchJobSummary` 加 `institution_id: str | None`
    2. `backend/src/cangjie_fos/api/routes/pitch.py` — 列表路由回填 `db_row.institution_id`
    3. `frontend/src/components/PitchJobHistory.tsx` — `JobRow` 加字段，列表显示 `🏢 机构名`（自动过滤 `待确认_` 前缀）

### Changed
- 测试基线：**502 passed**（不变，三个修复均为前端逻辑，无需新增后端测试；后端 schema 改动
  通过现有 PitchJobSummary 序列化测试验证）

---

## [0.5.3] — 2026-05-12  Chrome叠层Bug全面修复 + 路演数据打通Pipeline CRM

### Fixed
- **Bug #Chrome-1（Chrome叠层）全面根治**：登录后 Chrome 页面被透明薄膜覆盖无法点击
  - 根因：5个 Modal/Wizard 组件的透明外层 `fixed inset-0` wrapper 没有 `pointer-events-none`，
    Chrome `backdrop-filter: blur()` 导致合成层拦截所有点击事件
  - 修复：`ParticipantConfirmModal.tsx` / `PitchUploadWizard.tsx` / `DoctorPanel.tsx` /
    `PitchReportPreviewModal.tsx` / `AssetScanConfigModal.tsx` — 外层容器加 `pointer-events-none`，
    可见背景层和内容卡片加 `pointer-events-auto`
  - **额外修复**：`ExpHud.tsx` — 顶部 EXP 显示徽标是纯展示组件，加 `pointer-events-none`
    防止遮挡按钮点击（Playwright 实际测试中发现）
- **Bug #Data-打通（路演 → Pipeline CRM）**：路演分析完成后数据从不更新左侧战情室
  - 根因：`resume_roadshow_analysis()` 完成后只写 `pitch_jobs` 表，`institution_store`（Pipeline CRM）从未收到通知
  - 修复：`pitch_upload_pipeline.py` — 路演完成后自动 `upsert_institution()`，阶段至少为 PITCHED，
    不降级（已在DD/TS的机构保留阶段），`meeting_atmosphere` 映射到机构热度

### Added
- **`tests/conftest.py`** 升级：新增 `fos_login_credentials` session fixture，自动读取
  `backend/.env` 的 `FOS_ACCOUNTS`，确保浏览器测试用正确凭据登录（不再硬编码 dev/dev）
- **`tests/test_ui_smoke.py`** 全面更新：6个测试全绿
  - 修复 `_login()` 函数（登录表单有3个字段：指挥官名称/账号/密码，之前只填了2个）
  - 所有测试注入 `fos_login_credentials`
  - `test_roadshow_button_clickable` 使用 `get_by_text("路演日期")` 验证向导打开

### Changed
- 测试基线：502 → **506 passed**（浏览器烟雾测试从3通→6通）

---

## [0.5.2] — 2026-05-12  Hotfix 启动脚本编码修复

### Fixed
- **`安装并启动.ps1`**（UTF-8 无 BOM → 加 BOM）：PowerShell 5.1 在非中文系统上用 ANSI 编码读文件，
  第37行 `Write-Host "按 Ctrl+C 停止服务"` 被解析成含引号的乱码，触发 "missing string terminator" 解析错误，
  脚本完全无法执行。加 UTF-8 BOM 后 PowerShell 强制以 UTF-8 读取，问题消除。
- **`点击开始-仓颉FOS.bat` / `填写API密钥_双击我.bat` / `诊断_打不开请运行我.bat`**（UTF-8 → GBK）：
  `.bat` 文件由 `cmd.exe` 用系统 ANSI 编码（中文 Windows = GBK）读取，UTF-8 中文显示乱码。
  转为 GBK 后标题、提示文字正常显示。
- **其余含中文的 `.ps1` 文件**统一加 UTF-8 BOM：
  `run_dev.ps1` / `build_release_zip.ps1` / `ci_check.ps1` / `nightly_verify.ps1` /
  `preflight_local.ps1` / `backup_sqlite.ps1`

### Changed
- 测试基线：**495 passed**（不变，编码修复不影响逻辑）

---

## [0.5.1] — 2026-05-11  Hotfix 路演分析3个真实Bug

### Added
- **`tests/conftest.py`**（新文件）：Playwright 浏览器测试基础设施
  - `fos_server_url` session fixture：检测服务是否在 8000 端口运行，未运行则 skip
- **`tests/test_ui_smoke.py`**（新文件）：Playwright Chromium 浏览器烟雾测试
  - `TestLoginNoOverlay`：登录页可见、登录成功进主页、无阻塞叠层（Chrome Bug #Chrome-1 回归）、路演分析按钮可点击
  - `TestChromeRenderingDiagnosis`：收集登录后所有 fixed 元素渲染信息（调试辅助，永远 pass）
- **依赖**：`playwright>=1.59.0` + `pytest-playwright>=0.7.2` 加入 dev extras；Chromium headless 已安装

### Changed
- `CLAUDE.md` 测试分层表格新增"浏览器烟雾"层，补充 Playwright 运行说明
- **开发规范**：新增全屏 Modal/Wizard 必须配套浏览器烟雾测试（检查关闭态无叠层）

---

## [0.5.1] — 2026-05-11  Hotfix 路演分析3个真实Bug

### Fixed
- **`api/routes/roadshow.py` Bug #1**：移除重复的 `db_job_create()` 调用 — `job_create()` 内部已写 SQLite，外部再调导致 UNIQUE constraint 500 错误（音频上传必现）
- **`api/routes/roadshow.py` Bug #2**：`speaker-preview` 重写合并逻辑 — ASR输出短段（"你们的"/"退出路径"）必须拼成完整话语再展示；≥8字保留，每100字切断，选最长3条
- **`services/pitch_upload_pipeline.py` Bug #3**：`resume_roadshow_analysis()` 补充 `biz_type="01_机构路演"` 到 `explicit_context` — 缺失时 PitchGraphService 走评分分支生成错误格式报告，前端黑屏

### Added
- **`tests/test_roadshow_e2e.py`**（新文件）：17个E2E回归测试，覆盖3个Bug的精确触发场景
  - `TestRoadshowTranscriptE2E`：文字稿模式完整链路（无重复写入、合并话语、biz_type传递、报告字段）
  - `TestRoadshowAudioE2E`：音频模式完整链路（mock ASR，验证同样的3个Bug）
  - `TestSpeakerPreviewMergeLogic`：合并算法单元测试（连续段合并、说话人切换、8字过滤、100字切断）

### Changed
- 测试基线：**491 → 495 passed**（+4）

---

## [0.5.0] — 2026-05-11  Phase 7.4+7.5 机构路演计数 + 路演分析独立工作流

### Added

**Phase 7.5 — 路演分析独立工作流**
- **`api/routes/roadshow.py`**（新文件）：5个专属端点
  - `POST /api/v1/roadshow/start`：上传音频或文字稿，返回 job_id；文字稿直接跳到 awaiting_speakers
  - `GET /api/v1/roadshow/jobs/{id}/status`：轮询状态（步骤2/4用）
  - `GET /api/v1/roadshow/jobs/{id}/speaker-preview`：返回每位说话人样本台词 + AI推测角色
  - `POST /api/v1/roadshow/jobs/{id}/confirm-speakers`：用户确认说话人身份，触发LangGraph
  - `GET /api/v1/roadshow/jobs/{id}/report`：获取完整路演情报报告
- **`services/transcript_parser.py`**（新文件）：多格式文字稿解析（「说话人A:」「[A]」「【A】」等）
- **`frontend/src/components/RoadshowWizard.tsx`**（新文件）：5步独立向导（上传→等待→确认说话人→分析→报告）
- **`frontend/src/App.tsx`**：新增「🎯 路演分析」按钮（紫色，独立于复盘上传向导）
- **`schemas/pitch_upload.py`**：新增 `AWAITING_SPEAKERS` / `RESUMING_ANALYSIS` 状态
- **`services/pitch_job_db.py`**：新增 `is_roadshow` / `confirmed_speakers_json` / `referrer` 列（含迁移）
- **`engine/schema.py`**：`RoadshowIntelReport` 扩展 `referrer` / `dominant_speaker` / `competitor_mentions` / `timeline_signals` 四个字段
- **`services/pitch_upload_pipeline.py`**：新增 `run_roadshow_asr_job()`（ASR后暂停等待说话人确认）和 `resume_roadshow_analysis()`（注入说话人身份后继续LangGraph）
- **`services/github_sync.py`**：新增 `push_roadshow_report()`，推送路演情报到 `analytics/{tenant}/roadshow_{date}_{id[:8]}.json`
- **`tests/test_roadshow_api.py`**（新文件）：25个测试，覆盖所有端点 + 文字稿解析器 + 说话人角色推测逻辑

**Phase 7.4 — 机构路演统计 + 安全加固**
- **`services/pitch_job_db.py`**：`db_institution_pitch_stats()` — CTE UNION ALL 合并两数据源统计各机构路演次数和最后日期
- **`frontend/src/components/InstitutionList.tsx`**：每个机构卡片显示「N次路演 · 最近X天前」
- **`frontend/src/App.tsx`**：强制登录（去掉 accountsConfigured 旁路条件）
- **`frontend/src/components/ParticipantConfirmModal.tsx`**：confirmedBy 非空校验

### Changed
- 测试基线：**466 → 491 passed**（+25）
- `api/router.py` 注册 roadshow 路由

---

## [0.4.1] — 2026-05-11  Phase 7.1 情报→档案闭环 + 待跟进行动项系统

### Added

**P0 — 情报→档案闭环**
- **`follow_up_items` SQLite 表**（`pitch_job_db.py`）：持久化路演后续行动项，含 `id / tenant_id / job_id / institution_id / actor / action / priority / source / done / done_at`；两个索引：租户-完成状态-时间、job_id
- **`pitch_jobs.institution_id` 迁移列**（`pitch_job_db.py`）：向现有 `pitch_jobs` 表追加 `institution_id TEXT NOT NULL DEFAULT ''`，用于将路演与机构名绑定
- **5个 CRUD 函数**（`pitch_job_db.py`）：`db_follow_up_insert / db_follow_up_list / db_follow_up_mark_done / db_follow_up_list_by_job / db_job_bind_institution`
- **路演分析完成后自动写入行动项**（`pitch_wizard_runner.py`）：检测到 `RoadshowIntelReport` 时，将 `next_actions` 逐条写入 `follow_up_items`，跳过 `institution_id`（参与人确认后回填）
- **修复 `category` 字段未落盘**（`pitch_wizard_runner.py`）：首次 `db_job_update` 调用补加 `category=category`，确保"01_机构路演"等分类写入 SQLite

**P1 — participants 机构绑定**
- **`db_job_bind_institution(job_id, name)`**（`pitch_job_db.py`）：原子操作，同时更新 `pitch_jobs.institution_id` + 回填该 job 所有 `institution_id=''` 的 follow_up_items
- **participants 确认时提取机构名**（`participants.py`）：POST `/participants` 完成后自动从参与人里找投资方（GP执行/LP投资方/政府招商）的 institution 字段，调用 `db_job_bind_institution`；响应新增 `institution` 字段

**P1 — 新增 API 路由**（`api/routes/follow_ups.py`）
- `GET /api/v1/follow-ups?tenant_id=X` — 列出待跟进行动项（`include_done`/`limit` 参数）
- `PATCH /api/v1/follow-ups/{item_id}/done` — 标记完成
- `GET /api/v1/pitch/jobs/{job_id}/follow-ups` — 指定 job 的所有行动项（含已完成）
- `GET /api/v1/institutions/{name}/jobs` — 机构路演时间线（按时间倒序的 pitch_jobs）

**P1 — 前端**
- **`FollowUpWidget.tsx`**（新组件）：主页待跟进清单，默认收折，展开后列出所有未完成行动项，支持一键标记完成；无待办时自动隐藏
- **`InstitutionArchivePanel.tsx` 路演时间线**：机构详情侧边栏新增"路演时间线"区块，展示该机构关联的历次 pitch_jobs（日期/类别/状态/路演标题），点击跳转到对应审查台

**P3 — E2E 测试**
- **`test_roadshow_e2e.py`**（13个测试）：文字稿 `.txt` → wizard_runner → DB 验证（status/category/report_type/follow_up_items） → Review API → follow-ups API → mark_done
- **`test_follow_ups_api.py`**（16个测试）：CRUD 单元 + API 层（list/mark_done/404/job_follow_ups/institution_timeline） + participants 确认→机构绑定→follow_up 回填 集成测试

### Changed
- **测试基线**：422 → **451 passed**（+29）
- `api/router.py` 注册 `follow_ups` 路由

---

### V5.2 Wiki 知识展示层（2026-05-05）Phase 5.2

#### Added
- **`db_institution_briefing()`**（`pitch_job_db.py`）：机构智慧简报，从 `match_sessions` 查缺口（confirmed session 中 color=gray/red 的需求，去重最多5条），代表"素材库已知短板"
- **`db_asset_wiki_summary()`**（`pitch_job_db.py`）：资产选用历史摘要，从 `match_outcomes` 聚合选中次数、出现次数、选中率、关联机构
- **`candidate_to_dict()` reason 字段**（`matchmaker.py`）：每个匹配候选附带人类可读说明（标签命中/文件名匹配/摘要相关/机构历史首选）
- **`GET /api/v1/institutions/{name}/briefing`**：机构简报端点，返回历史次数、偏好标签、已知缺口
- **`GET /api/v1/assets/wiki/{path:path}`**：资产选用历史摘要端点
- **`GET /api/v1/digest/pending`**：未读晨报建议端点（读 `nightly_suggestions` 表）
- **`POST /api/v1/digest/{id}/consume`**：标记晨报已读
- **`POST /api/v1/assets/match` 返回值新增 `gap_hints`**：匹配完成后注入历史缺口列表
- **`InstitutionBriefingCard`**（`MatchMakerPanel.tsx`）：机构名 onBlur 后自动加载简报，展示历史次数/偏好标签/缺口
- **`GapAlertBanner`**（`MatchMakerPanel.tsx`）：匹配完成后若有缺口，显示橙色告警条（可关闭）
- **ResultRow reason 列**（`MatchMakerPanel.tsx`）：最佳匹配文件下方显示 reason 小字
- **`WikiPreview`**（`InstitutionArchivePanel.tsx`）：机构详情面板顶部自动展示知识画像
- **`AssetWikiPanel`**（`AssetLibrary.tsx`）：资产行 📊 按钮，点击展开匹配历史浮层（懒加载）
- **`DigestBanner.tsx`**（新组件）：晨报推送横幅，展示未读 nightly_suggestions，支持逐条/全部已读
- **测试：`test_wiki_display.py`**：11 个新测试，覆盖 DB 函数 + API 端点
- **架构文档**（`matchmaker-skill-evolution.md`）：新增"九、Wiki 知识展示层"章节

#### Changed
- **测试基线**：371 → **382 passed**（+11 wiki_display 测试）

---

### 生产热修复（2026-04-28）

#### Fixed
- **`request_context.py`：413 大文件上传失败** — `RequestContextMiddleware` 对 `multipart/form-data` 请求错误地应用了 JSON 8MB body 上限，导致 172MB+ 音频无法上传。修复：检测 content-type，文件上传跳过 body size 检查。
- **`asr_polish.py` / `memory_engine.py`：`No module named 'llm_judge'`** — Phase 1 engine/ 迁移遗漏函数体内懒导入（`from llm_judge` / `from retry_policy`），测试因 mock 层次较高未发现。修复：改为 `cangjie_fos.engine.*` 完整路径。
- **`安装并启动.ps1`：FFmpeg 首次下载失败** — `imageio_ffmpeg` 首次调用时联网下载二进制，慢网/断网机器无提示失败。修复：启动脚本新增 `[3/4]` 预下载步骤（`imageio_ffmpeg.get_ffmpeg_exe()`），失败时打印警告而非阻断启动。
- **测试基线**：289 passed（不变，修复不影响测试覆盖层）

---

### Phase 7.0 阶段5（2026-04-28 完成）

#### Added
- **`tools/doctor.py`**：跨平台诊断修复脚本，9 项检查（Python/uv/依赖/端口/data目录/FFmpeg/SQLite/env/node_modules），`--fix` 模式自动修复可修复项，Windows UTF-8 输出
- **`GET /api/v1/doctor`**：HTTP 版诊断探针，返回 `python_version/ffmpeg_available/data_dir_writable/db_writable/env_exists/issues/fix_suggestions`，供前端「系统诊断」面板使用
- **`DoctorPanel.tsx`**：前端系统诊断弹窗，调用 `/api/v1/doctor`，展示各项状态（✅/❌）、问题列表及修复建议，导航栏右上角「🔧 系统诊断」入口
- **`诊断_打不开请运行我.bat` 增强**：调用 `doctor.py --fix` 自动诊断修复后再启动 uvicorn，启动失败分情况输出中文错误说明
- **README.md 快速启动更新**：3步启动指引、系统需求表格、遇到问题诊断入口
- **测试覆盖**：新增 `tests/test_doctor_probe.py`（9个测试）和 `tests/test_doctor_script.py`（2个测试）

#### Changed
- **测试基线**：278 → **289 passed**

### Phase 7.0 阶段4（2026-04-28 完成）

#### Added
- **`db_job_list_risk_keywords(tenant_id, limit)`**：查询某租户最近N条已完成路演的风险点列表，用于素材匹配分析
- **`db_assets_search_by_keywords(tenant_id, keywords)`**：基于 material_contributions 表 tags/filename 字段做关键词匹配
- **`db_material_contribution_bulk_upsert(tenant_id, asset_ids, action)`**：批量 upsert 素材贡献度（ON CONFLICT 累加 usage_count）
- **`capture_review_diff` 全链路数据关联**：审查员提交修改后自动触发 → 提取风险关键词 → 匹配素材 → 更新 material_contributions + 写入 material_match_history
- **`_generate_material_suggestions` 真实 TF-IDF 计算**：替换占位实现，基于最近10条路演风险关键词计算素材覆盖率（<30%触发 material_update 建议）+ 识别零贡献高引用素材（institution_insight 建议）
- **`ContributionBoard.tsx` 前端组件**：调用 `GET /api/contributions` 显示贡献度排行榜（名次/贡献者/得分/路演数），嵌入 AssetLibrary 页底部
- **`GET /api/v1/admin/association-log?tenant_id=X&limit=N`**：返回 material_match_history 按机构聚合记录，用于调试确认关联链路真实触发
- **测试覆盖**：新增 `tests/test_phase4_association.py`（12个测试）：DB查询格式/过滤、关键词匹配、bulk_upsert累加、capture_review_diff关联触发、nightly_settle真实计算、API端点200/422

#### Changed
- **测试基线**：266 → **278 passed**

### Phase 7.0 阶段3（2026-04-28 完成）

#### Added
- **`nightly_suggestions` SQLite 表**：夜间进化建议持久化，含 `id/tenant_id/type/content/asset_id/priority/consumed_at`（`db_nightly_suggestion_insert / list_pending / mark_consumed`）
- **`nightly_settle.py` 夜间结算服务**：`nightly_settle_all_tenants()` / `nightly_settle_for_tenant(tenant_id)`，3步流水线：偏好提取 → 素材建议生成 → 写入 nightly_suggestions
- **APScheduler 3.11.2 接入 FastAPI lifespan**：每晚2:00自动触发 `nightly_settle_all_tenants`，lifespan 启动/关闭生命周期管理
- **`POST /api/v1/admin/nightly-settle?tenant_id=X`**：调试用手动触发端点，返回 `{tenant_id, suggested}`
- **豆豆 NPC 夜间建议注入**：`_inject_system_health` 节点追加读取未消费 `nightly_suggestions`（priority≤5，最多3条），注入后标记已消费
- **测试覆盖**：新增 `tests/test_nightly_settle.py`（8个测试）：表创建、CRUD、优先级过滤、limit、mock调用链、端点200/422

#### Changed
- **测试基线**：258 → **266 passed**

### Phase 7.0 阶段2（2026-04-28 完成）

#### Added
- **`executive_memories` SQLite 表**：高管错题本迁移，含 UUID 幂等插入、按公司/标签查询、删除（`db_exec_memory_insert / list / delete`）
- **`material_contributions` SQLite 表**：素材贡献度，ON CONFLICT 累加 `usage_count / contribution_score`（`db_material_contribution_upsert / list`）
- **`contribution_scores` SQLite 表**：贡献者汇总，ON CONFLICT 累加（`db_contribution_score_upsert / list`）
- **`material_match_history` SQLite 表**：素材-机构匹配历史（`db_material_match_insert / list`）
- **`GET /api/materials/health`**：素材健康度列表（usage_count / contribution_score / tags）
- **`POST /api/materials/match`**：为机构生成素材清单并记录匹配历史（tag/keyword 评分）
- **`GET /api/contributions`**：贡献度排行（score DESC），支持 `?limit=N`
- **分页参数**：`GET /api/pitch/jobs` 支持 `?page=1&size=20`（page>1 时走 SQLite OFFSET）
- **structlog 25.5.0**：新增结构化日志依赖，应用于 `materials` 路由

#### Changed
- **前端懒加载**：`WarRoomMap` 和 `AssetLibrary` 改为 `React.lazy()` 按需加载，bundle 拆分为独立 chunk

### 战略规划更新（2026-04-27）
- 战略计划文件已纳入 Kimi 外部评审建议：SQLite WAL 模式、LLM 多模型 fallback、文件 MIME 校验、前端懒加载、structlog、分页 API（见 `plans/adaptive-finding-valiant.md`）
- 明确拒绝：Git Submodule、aiosqlite、Celery、Prometheus、K8s、PostgreSQL 迁移

### 待做（近期）
- **阶段3**：APScheduler 夜间自动进化任务
- WebSocket 实时推送替代 Task Rail 轮询
- 路演倒计时计时器（审查台）

## [0.3.0] — 2026-04-28  Phase 7.0 阶段1 FSS 代码完全合并

### Changed
- **FSS 全部核心模块迁入 `engine/` 子包**（共 23 个模块）：
  - 第一批：`transcriber`、`memory_engine`、`asset_bridge`、`schema`、`retry_policy`、`language_detector`、`investor_matcher`、`growth_engine`
  - coach 流水线：`agent_nodes`、`agent_workflow`、`agent_runner`、`agent_state`、`agent_sanitize`、`agent_tenant`、`llm_judge`
  - 第二批（2026-04-28补完）：`asr_polish`、`audio_preprocess`、`document_reader`、`job_pipeline`、`report_builder`、`runtime_paths`、`sensitive_words`
- **全面消灭 `ensure_pitch_coach_runtime()` / `ensure_pitch_coach_import_path()` 调用**：`pitch_upload_pipeline`、`pitch_graph_service`、`audio_service`、`html_report_service`、`pitch_wizard_runner`、`tenant_context`、`api/routes/pitch.py`、`api/routes/pitch_wizard.py` 全部改为 `from cangjie_fos.engine.*` 直接导入
- **engine/ 内部 import 修正**：`asr_polish`、`report_builder`、`job_pipeline` 内部引用改为 `cangjie_fos.engine.*`
- **删除 `adapters/coach_memory_bridge.py`**：逻辑内联，使用 `engine.memory_engine` + `engine.coach.agent_tenant`
- **删除 `adapters/institution_coach_sync.py`**：依赖清除
- **测试全面更新**：`test_p0_retry_eval`、`test_p0_pipeline_persistence`、`test_p1b_html_report_service`（完全重写为 engine.* patch）、`test_pipeline_e2e`、`test_wizard_pipeline_e2e` 均更新 mock 路径

### 结果
- `ensure_pitch_coach_runtime()` 在 FOS 业务代码中**调用次数 = 0**（函数定义保留在 `core/paths.py` 以防万一）
- 测试基线：**239 passed**，无需 `CANGJIE_PITCH_COACH_ROOT` 环境变量（mock 已内化）
- FSS 仓库（`D:\AI_Workspaces\AI_Pitch_Coach`）可正式归档

---

## [0.2.1] — 2026-04-27  Phase 7.0 R3 LLM 重试 + 重跑评估

### Added
- **`pitch_graph_service.py` 指数退避重试**：LLM 调用遇到 `ConnectionError` / `TimeoutError` 自动重试3次（4次总计），间隔 2/4/8s；其他异常立即抛出不重试
- **`POST /api/pitch/jobs/{id}/retry-eval`**：读取 SQLite 中的 `words_json` 重跑 LangGraph 评估，无需重新上传音频；返回 404/409/422 校验 + 200 成功
- **`PitchJobSummary.has_words_json`**：新增布尔字段，`GET /api/pitch/jobs` 返回每条任务是否可重跑
- **TaskRail「重跑评估」按钮**：failed 卡片在 `has_words_json=true` 时显示按钮，点击调用 retry-eval 端点并刷新轨道
- **测试覆盖**：新增 `tests/test_p0_retry_eval.py`（11 个测试），228 → 239 passed

---

## [0.2.0] — 2026-04-26  Phase 6.4 第二轮补丁

### Added
- **Task Rail substatus**：流水线 8 节点细粒度进度文字（压缩→上传→ASR→转写→分析→诊断→报告→完成）
- **Task Rail 秒表**：active 任务实时显示"已等待 Xm Xs"
- **豆豆系统诊断**：`inject_system_health` 图节点，将 readiness + 最近失败任务注入 NPC 上下文
- **SQLite 重启兜底**：服务重启后 Task Rail 不再空白，自动从 SQLite 读历史任务
- `db_job_list_recent_errors()` 工具函数
- `substatus` 字段（SQLite DDL + schema + API 透传 + 前端展示）

### Changed
- **ASR 错误信息精确化**：`FILE_DOWNLOAD_FAILED` 等 8 种阿里云错误码不再显示通用兜底文案，改为具体原因和操作建议
- **审查台卡片**：移除"原文实录"显示区块（字段数据保留，后处理仍使用）；AddRiskPointForm 同步移除该输入框
- **NPCPanel 滚动修复**：外层 `max-h-[min(900px,90vh)]` + 消息区 `flex-1 overflow-y-auto`，真正实现内部滚动

### Fixed
- 服务重启后 `/api/pitch/jobs` 返回 500（SQLite fallback 路径 `warnings` JSON 字符串未反序列化）

---

## [0.1.0] — 2026-04-22  Phase 6.4 基础版本（初始 GitHub 发布）

### 系统全貌
- **FastAPI 后端** + **React 18 前端**，SQLite 持久化
- **LangGraph 多 Agent 评估引擎**：路演录音 → ASR 转写 → 风险分析 → 结构化报告
- **全屏审查台**（ReviewWorkbench）：风险点卡片、音频片段播放、HTML 报告生成
- **Task Rail**：上传任务进度追踪（pending/transcribing/evaluating/completed/failed）
- **豆豆 NPC 顾问**：LangGraph 对话图，融资知识 + 任务状态感知
- **机构漏斗（War Room Map）**：Teaser→DD→签约 全流程追踪
- **资料库（AssetLibrary）**：FSS 资产管理与上下文注入
- **进化飞轮骨架**：EvolutionCapture / Extractor / Injector 骨架已落地
- **就绪检查（Readiness）**：`preflight.py` + `readiness.py` + `诊断_打不开请运行我.bat`
- **Docker 支持**：`Dockerfile` + `docker-compose.yml`
- **228 个自动化测试**，覆盖 Pipeline E2E、API 路由、DB 持久化、NPC 上下文

### 外部依赖说明
- 本仓库（FOS）依赖 **AI Pitch Coach（FSS）** 作为 LLM/ASR 评估后端
- FSS 未公开发布；本地部署需将 FSS 路径配置至 `PITCH_COACH_ROOT` 环境变量
- 不依赖 FSS 的功能（机构漏斗、资料库、豆豆对话）可独立运行
- 测试套件通过 mock 隔离 FSS 依赖，可在无 FSS 环境下全部通过

---

## 版本号规则

`major.minor.patch`  
- major：架构级重构  
- minor：新功能 Phase  
- patch：Bug 修复 / 小改动
