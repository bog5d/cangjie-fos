# CALLCHAIN · 修复前后对照（cangjie-fos#71 考生2 P0）

base：`d9bd8e89c1a35aa7f27893bfcd84be4713cf27d2`（master tip）→ 分支 `feat/71-player2-p0-fix-20261023`
行号口径：**修复前** = `git show master:<file>` 的行号；**修复后** = 本分支工作树行号。

---

## 0. 一句话

修复前，**义务侧**（清单文本）与**材料侧**（材料路径）各自用一张**只覆盖 10 类中 7 类**的中文类型表，
而桥接链用的是**英文 key 空间** ⇒ 三处口径分叉 ⇒ 证据池恒空且**静默**返回空列表。
修复后，类型取值空间**只剩一处**（`dd_v1_requirement_service._DOC_TYPE_RULES` 的 10 个英文 key），
两侧比较前先归一，候选为空时给出**六态原因**。

---

## 1. 正式入口 B（`tools/dd_v1_local_run.py`）

### 1.1 `scaffold`（扫材料 → meta.json）

| 环节 | 修复前 | 修复后 |
|---|---|---|
| 类型判定 | `:157` `dt = next((d for d in sem.DOC_TYPES if d in rel), "")` —— **整条相对路径** + 语义层的 7 类中文表 | `:179` `dt, prov, _evidence = dts.resolve_doc_type(file_name=f.name)` —— **只看文件名**，产出英文 key + provenance |
| 类型表来源 | `dd_v1_semantic_retrieval_service.py:27` `DOC_TYPES = ("审计报告","营业执照","公司章程","社保缴纳证明","财务报表","验资报告","纳税证明")` | `dd_v1_requirement_service._DOC_TYPE_RULES`（10 英文 key，**唯一权威**，本文件不另抄） |
| 期间判定 | `:159` `"CURRENT" if dt in ("营业执照","公司章程")`（中文常量） | `:182` `"CURRENT" if dt in rq.CURRENT_DOC_TYPES`（英文 key，来源同表） |
| 产物字段 | `file_id / relative_path / entity / period / doc_type / part / version_status` | 同上 **+ `doc_type_provenance`**（INFERRED / UNKNOWN） |

**为什么整条路径是错的**（机械证，见 `EVIDENCE-PLAYER2-P0.md` §3-D）：
真实材料库按法人/类型建多级目录，布局形如 `1.审计报告(1)/营业执照2024.pdf` ⇒
按路径判定会把**目录里别人的类型**认成这份材料的类型。`dd_v1_doc_type_service` 的模块文档
（第 39–42 行）早已写明「只看文件自己的名字」，但入口 B 没照做。

### 1.2 `split`（清单 → 原子义务）

| 环节 | 修复前 | 修复后 |
|---|---|---|
| 入口 | `:169 cmd_split` → `sem.split_items` | 同（拆解逻辑已换） |
| 类型判定 | `dd_v1_semantic_retrieval_service.py:46 _doc_type()` + `:27 DOC_TYPES`（7 类中文） | `:114 _doc_type_spans()` → `rq.parse_doc_type_spans()`（权威 10 类） |
| 一段两类 | `:50 hits[0] if len(hits) == 1 else None` ⇒ **整条丢弃**（`:75-77` NEEDS_HUMAN_SPLIT） | 可分离 ⇒ **按类拆成多条原子义务**（每条一类、共享该段期间与附件要求）+ 留痕 `AMBIGUOUS_SPLIT`；复合词（无分隔符）**不拆** |
| 期间判定 | `:66` `"CURRENT" if dt in ("营业执照","公司章程") or "最新" in seg` | `:176` `all(k in rq.CURRENT_DOC_TYPES for k, _s, _e in spans) or "最新" in seg`（同表，英文 key） |
| 留痕结构 | `split_item` 返回 `(obligations, dict|None)` | `split_item` 返回 `(obligations, flags: list)`；包内新增 `split_flags`，`unsplit_items` 仍只收 NEEDS_HUMAN_SPLIT / PARTIAL_SPLIT |

### 1.3 `run`（候选召回 → 语义判断）

| 环节 | 修复前 | 修复后 |
|---|---|---|
| 召回过滤 | `dd_v1_semantic_retrieval_service.py:146` `pool = [m for m in meta if m["entity"] == ob["entity"] and m.get("doc_type") == ob["doc_type"]]` —— **精确字符串相等** | `:338`/`:357` 两侧 `doc_type` **先 `dts.normalize_doc_type()` 归一**再比；主体两侧按 `dd_v1_entity_service.normalize_name` 归一（`:295`） |
| 空结果 | 静默返回 `[]` | `:319 retrieve_minimal_evidence_detailed()` 返回 `no_candidate_reason`（六态）+ `diagnostics`（年度/版本/附件/权限/截断计数） |
| 规则提示 | `:176` MISSING + `note="NO_EVIDENCE"`（六种原因不分） | `:457 rule_hint(ob, evidence, no_candidate_reason)` —— 证据为空时附 `no_candidate_reason`；证据非空时逐位不变（不破坏既有断言） |
| 语义包 | `unsplit_items` / `evidence` | 同上 **+ `evidence_status`**（逐义务的原因与诊断）**+ `split_flags`** |

---

## 2. 桥接链（`dd_v1_bridge_service.py`）—— 修复前已自洽，只把「当前有效」子集也收归唯一来源

| 环节 | 修复前 | 修复后 |
|---|---|---|
| `build_meta` | `:163` → `resolve_material_doc_type`（`:91`）→ `rq.parse_doc_type` ⇒ **英文 key** | 不变 |
| `build_semantic_obligations` | `:236` → `rq.parse_doc_type` / `rq.doc_type_search_terms` ⇒ **英文 key** | 不变 |
| 「当前有效」子集 | `:86 _CURRENT_DOC_TYPES = ("license", "charter")`（**另抄一份**） | `:87 _CURRENT_DOC_TYPES = rq.CURRENT_DOC_TYPES`（同源，不另抄） |

★ 司仓 2026-10-22 已把 `backend/tests/test_dd_v1_policy_and_entry.py:261` 的断言从中文 doc_type 改成英文 key
（注释写明「WP-A1 口径更正」），**产品实现没跟上** ⇒ 半拉子状态。本 PR 把实现补齐（根因 D）。

---

## 3. 类型取值的**唯一来源**（本 PR 新增的公开 API）

| 位置 | 修复前 | 修复后 |
|---|---|---|
| `dd_v1_requirement_service._DOC_TYPE_RULES` | `:144`（10 英文 key） | **不动**（唯一权威表） |
| `dd_v1_requirement_service.CURRENT_DOC_TYPES` | — | `:160` 新增（"license","charter"）—— 语义层/桥接层/入口 B 共用 |
| `dd_v1_requirement_service.parse_doc_type` | `:653`（只返回第一类） | `:658` **不动**（既有调用方语义不变） |
| `dd_v1_requirement_service.parse_doc_type_spans` | — | `:665` **新增**：返回全部命中 + 位置；重叠按「规则表顺序优先、同序取更长」消解（⇒「劳动合同」不会被拆成 labor+contract） |
| `dd_v1_requirement_service.parse_doc_types` | — | `:696` **新增**：按出现位置去重后的 key 列表 |
| `dd_v1_doc_type_service.normalize_doc_type` | — | `:79` **新增**：比较/归一环节的唯一入口（英文 key 直通；中文类型名经 `rq.parse_doc_type` 归一；扩展名/乱写 ⇒ 空串=UNKNOWN） |

★ **没有第三套类型表**：语义层与 CLI 都只调公开 API，仓内 `DOC_TYPES` / `DOC_TYPE_ALIASES` 两张旧中文表**已删**
（`grep -rn "DOC_TYPES\|DOC_TYPE_ALIASES" --include=*.py` 现在只剩 `rq.CURRENT_DOC_TYPES` / `DOC_TYPE_KEYS` / `rq._DOC_TYPE_RULES` 三处**引用**，无新表）。

---

## 4. 数据流（修复后）

```
清单文本 ──split_item(:149)──► 义务 doc_type = 英文 key（rq.parse_doc_type_spans）
                                    │
材料文件 ──cmd_scaffold(:153)──► meta[].doc_type = 英文 key（dts.resolve_doc_type(file_name=f.name)，带 provenance）
                                    │
                    retrieve_minimal_evidence_detailed(:319)
                      ├ 义务侧 doc_type ─┐
                      ├ 材料侧 doc_type ─┴─► dts.normalize_doc_type(:79) ─► 同一 key 空间
                      ├ 主体两侧 ───────────► es.normalize_name（跨法人不混桶）
                      ├ access 规则 ────────► 受限材料不进池（计数留痕）
                      └ 候选为空 ───────────► no_candidate_reason 六态 + diagnostics
                                    │
                    build_semantic_packet(:507) ──► evidence + evidence_status + split_flags
                                    │
                    validate_semantic ──► accepted/rejected（模型输出永远只是建议）
                                    │
                    rule_hint(:457) ──► MATCH / PARTIAL / OUTDATED / MISSING(+no_candidate_reason)
```
