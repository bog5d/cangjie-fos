# WP-R0 · 现状审计：考生2为什么没做完

> 基线：`cangjie-fos@a7a7e24`（2026-10-16）｜日期：2026-10-19
> 方法：以**实际运行路径**为准（`tools/dd_v1_local_run.py` 的真实调用链），不靠文档推断。

## 结论一句话

**DeepSeek Harness 从未被调用（adapter 是桩，降级 RULE_ONLY）；即使调用了，候选池也是从「员工手工打标的元数据清单」按 `doc_type` 等值筛出来的，不查全文索引、不自动抽正文。**
这两条各自独立成立，足以解释「考生2没做完、只能按文件名检索」。

## 因果链（全部有 file:line）

### 断点 1：模型没参与 —— adapter 是桩

| 事实 | 位置 |
|---|---|
| `DeepSeekHarnessAdapter` 默认 enabled=False，**不发起任何调用**，直接返回 UNAVAILABLE | `dd_v1_agent_adapters.py:10-11, 292` |
| 失败状态一律降级 `RULE_ONLY` | `dd_v1_agent_adapters.py:9` |
| WP04 实测：deepseek-harness `exit=2 / UNAVAILABLE / BLOCKED，未起进程 / RULE_ONLY` | `docs/dd-v1-fos71/wp04/EVIDENCE-WP04.md` 实跑表 |
| 原因：OQ-1 未裁定，当前选项 c「考生3 缺席，报 BLOCKED」 | `docs/dd-v1-fos71/wp02/SPEC-WP02.md:33` |
| 本地真跑需显式 `--allow-local-dsh`，由操作员在自己机器开启 | `dd_v1_agent_adapters.py:293` |

> **刘江看到的 100% 是 RULE_ONLY 输出**——纯规则判的文件名匹配，模型一次都没参与。
> ChatGPT 说「模型没拿到正文」方向对，但根因更硬：**模型根本没被调用**。

### 断点 2：候选池靠手工打标，不查全文索引

`tools/dd_v1_local_run.py` 的 `cmd_run` 真实调用链：

```text
cmd_scaffold → _load_items → local_material_snapshot → run_semantic
```

**全程没有调用**：
- `dd_v1_manifest_service.build_manifest`（不建 Manifest）
- `dd_v1_parser_service.parse_pending_batch`（不抽正文、不写正文缓存）
- `dd_v1_card_service.build_cards_for_library`（**不建认知卡 ⇒ FTS 索引根本不存在**）

候选池的真正来源 —— `dd_v1_semantic_retrieval_service.py:141`：

```python
pool = [m for m in meta
        if m["entity"] == ob["entity"] and m.get("doc_type") == ob["doc_type"]]
```

**双重等值筛，且 `meta` 是员工手工填的** —— `tools/dd_v1_local_run.py:52-54`：

```python
meta.append({"file_id":..., "entity": a.entity or "", "doc_type": dt,
             "part": "附注" if "附注" in rel else "正文", ...})
```

| 后果 | 说明 |
|---|---|
| 未打标的文件 `doc_type=""` | `m.get("doc_type") == ""` 匹配不到任何义务 ⇒ **该文件对所有义务不可见** |
| 未打标的文件 `entity=""` | 同样等值筛不掉 |
| `part` 靠文件名含「附注」 | 靠文件名判断正文/附注 |
| `untrusted_excerpt` | `:147` `_text_for(snapshot_dir, m, text_root)` —— 正文依赖**外部 text_root**，默认没有 ⇒ `NO_TEXT` |

### 断点 3：这正是董事长指令第 4 条要消除的

> 指令原文：「文件夹内部**不能要求员工预先把所有文件重命名或精细分类**」

当前实现**要求员工预先把每个文件的 entity / doc_type / period 手工打标**，否则该文件对模型完全不可见。
→ 「非常依赖一个稳定的文件包」这一反馈，**代码级坐实**。

## 五问逐条回答

| 问 | 答 |
|---|---|
| **A. Markdown 预热/正文缓存为何没进考生流程** | **根本没调**。`cmd_run` 不调 prefetch、不调 parser。正文缓存表无人写入考生路径。 |
| **B. FTS 索引与认知卡为何没被充分使用** | **根本没建**。`build_cards_for_library` 不在 `cmd_run` 链路里 ⇒ `dd_v1_material_fts` 无数据。`retrieve_minimal_evidence` 也不查 FTS，只筛 `meta`。 |
| **C. PDF/Word/Excel 正文为何没交给匹配系统** | 正文走 `_text_for(..., text_root)`，**依赖员工另外准备一份文本目录**，默认空 ⇒ 模型看到 `NO_TEXT`。Excel 工作表/单元格**未保留**（见下）。 |
| **D. 为何只有少量材料类型能进候选池** | 候选池按 `doc_type` 等值筛；义务侧拆不出 `doc_type` 时标 `NEEDS_HUMAN_SPLIT` 且不调用模型（`dd_v1_local_run.py:115`）。材料侧类型靠**员工手工填**，与文件真实内容无关。 |
| **E. DeepSeek 实际读到什么** | 读到的是 `build_semantic_packet` 构造的最小证据包：file_id / relative_path / sha256 / entity / period / doc_type / part / version_status / locator / `untrusted_excerpt`。**实体模型一次都没参与。** |

## 审计补充（代码级，已核实）

### 新发现 1：`--entity` 未传 ⇒ 静默全 MISSING（最可能的直接触发原因）

`tools/dd_v1_local_run.py:52`：`entity` 是 `--entity` **单一值灌给所有文件**，不传则 `meta.entity` 全为空串。
`sem:141` 的 `m["entity"] == ob["entity"]` 是**无兜底硬等** ⇒ 全池为空 ⇒ 全条 MISSING，**不报错**。
员工漏传 `--entity` 就会得到一份「全部缺材料」的答卷，且没有任何提示。

### 新发现 2：PDF/Word/Excel 连 300 字都给不了

`sem:36` `TEXT_SUFFIXES = {".txt",".md",".csv",".json",".tsv"}`；
`sem:123` 之外一律 `return None` ⇒ `sem:147` 取到 `NO_TEXT`。
所谓「每文件最多 300 字摘录」**只对文本类文件生效**；PDF/Word/Excel 连摘录都没有。

### 新发现 3：Excel 结构全丢

`dd_file_parser.py:100-112` `_extract_excel`：**`wb.active` 只取活动表**、`values_only=True`、
无表名、无单元格地址、行上限 200 ⇒ **工作表/单元格结构全部丢失**。
→ 直接命中董事长指令「Excel 应保留工作表、单元格及数字来源」。

### 新发现 4：摘录截断无标记

`sem:35` `MAX_EXCERPT_CHARS = 300`，截断在 `sem:112` 的 `[:MAX_EXCERPT_CHARS]`，**无 truncated 标记**；
对比 `parser_service.py:120-123` 的 parser 层**有**显式 truncated。excerpt 层漏了。

### 断链汇总（五环）

| 环节 | 状态 | 证据 |
|---|---|---|
| ① 正文抽取 | **断** | `local_run.py:85-146` 无抽取调用；`sem:123` 非文本后缀直接 None |
| ② 正文缓存 | **断** | 写在 `prefetch:92` / `parser:227`，run 读 `sem:119` 的 `meta.text_path`，而 scaffold 不产出该字段（`local_run.py:52-55`） |
| ③ FTS / 认知卡 | **断** | 写入仅 `card:482-491`；`build_cards_for_library` 调用方仅 `dd_v1_manifest.py:185`、`dd_team_channel.py:147`；`retrieve_minimal_evidence` 零 FTS 引用 |
| ④ 召回 | **通但极窄** | `sem:141` 硬等 + `sem:145` 截 6 个 + `sem:112` 截 300 字无标记 |
| ⑤ 模型 | **断** | 桩 `adapters:314-318` / 失败 `:336-337` → `agent_result:218` → `sem:214` `mode="RULE_ONLY"` |

**五环里四环是断的。**这解释了为什么「考生1 能干活」而「考生2 完全做不完」：
Codex 自己会翻文件，DD-V1 这条链却把正文、缓存、索引全绕开了。

### 五问最终回答

- **A** 正文缓存**根本没调**。写入方（prefetch/parser）与读取方（run）不是同一批代码。
- **B** FTS 与认知卡**根本没建**；`retrieve_minimal_evidence` 是纯 metadata 召回，零 FTS 引用。
- **C** PDF/Word/Excel **连抽取器都进不去**，直接 `NO_TEXT`；Excel 只取活动表、丢结构。
- **D** 7 类白名单（`sem:27-28`：`审计报告/营业执照/公司章程/社保缴纳证明/财务报表/验资报告/纳税证明`）+
  别名 2 个；`--entity` 不传则全池空。**类型识别是准入闸，不是排序因子**——与指令第 8 条冲突。
- **E** 模型 packet 只有 file_id/relative_path/sha256/entity/period/doc_type/part/version_status/
  locator/≤300字 excerpt；`rule_hint` 只用 period/version_status/part 三个字段算判定，**从不看正文**。

## 结论对 WP-R1 的约束（施工依据）

1. **候选池必须从文件内容自动派生**，不能依赖员工手工 tag。
2. **正文与表格必须自动抽取**并落受控 Data Plane，不要求员工另备 text_root。
3. **类型识别不得作为准入闸**（先高召回，再精排），与指令第 8 条一致。
4. 模型是否参与受 OQ-1 阻塞，**但不妨碍 WP-R1~R4 施工**：先把「材料能被读懂」这层建起来。
