# 考生2 · 第二轮 R2-WP1（期间语义）证据包

- 需求源：`bog5d/cangjie-fos#71`（业务 Owner 第二轮目标导向开发令）
- 基座：`d1ebe3392fb20f04c2d0ecb00bbe639804187ac2`（R1 交卷 SHA；**不是** master）
- 分支：`feat/71-player2-r2-wp1-period-semantics`
- 本轮范围：**只做 WP1（期间语义）**，不做 WP2／WP3。

## 分段施工（每段自洽 ⇒ commit + push ⇒ 再做下一段）

| 段 | 内容 | 状态 |
|---|---|---|
| 1 | `dd_v1_period_service.py`（四态解析 + 兼容判定 + 锚点解析）＋其单测 ＋ 探针落盘 | 见提交历史 |
| 2 | 语义层与 R4 校验层接线（候选可用性 / 规则提示 / 匹配判定） | 未开始 |
| 3 | 正式入口接线（`tools/dd_v1_local_run.py`、`tools/dd_team_channel.py`） | 未开始 |
| 4 | 全链路回归矩阵 ＋ 证据成卷 | 未开始 |

## 期间语义四态（口径）

| 态 | 含义 | 判定依据 |
|---|---|---|
| `EXPLICIT` | 明确年度 | 文本里的绝对年份 |
| `RELATIVE` | 相对期间 | **必须**有可验证的截止日期（锚点）才能展开 |
| `CURRENT` | 当前有效 | 该类无年度口径（执照/章程）⇒ 不继承段落年份 |
| `UNKNOWN` | 期间未知 | 文本压根没提期间 ⇒ 该维度不构成门槛 |

兼容判定四态：`MATCH` ／ `MISMATCH` ／ `UNVERIFIABLE`（依据不足 ⇒ UNCERTAIN，
保留候选证据 + `abstain_reason`，**不得**升格 `MATCHED`）／ `NOT_A_CONSTRAINT`。

锚点来源（**只有**这三种，**没有**「当前系统时间」）：
`EXPLICIT_CONFIG`（显式配置）＞ `CHECKLIST_DECLARATION`（原文自带声明）
＞ `MATERIAL_DATE`（材料自身年度）。

## 仓内自检件

- `shape_probe.py`：司仓禁形自检 7 族（作用域＝本轮写出字节），**可扫自己且自扫 0**。
- `run_with_ps_evidence.sh`：测试读数三件套采集器（UTC 起止 + junit XML +
  pytest 自身退出码 + ps 主进程采样）。

```bash
python3 docs/dd-v1-fos71/player2-r2-wp1/shape_probe.py <本轮写出文件> [更多路径]
```

## 段 2（笔2）：相对期间语义接线 + R4 闸

- **四态口径**：期间语义四态（EXPLICIT 明确 / RELATIVE 相对 / CURRENT 当前 / UNKNOWN 未知）
  在语义检索层落地为 `ob["period_spec"]`；旧 `ob["period"]` 字符串**逐字不动**，
  兼容判定由 `spec_from_obligation()` 单一入口做降级（不新增第二套类型表）。
- **CURRENT 三档（不扩枚举）**：`CLASS`（无年度口径类，如执照/章程；带年份副本仍兼容）、
  `LATEST`（「最新/现行」⇒ 须取候选池最大年度）、`LABEL`（旧数据只有 CURRENT 标签 ⇒ 严格不放宽）。
- **UNCERTAIN 出口**：依据不足时保留候选（`candidate_status` 阶梯与 `NO_CANDIDATE_REASONS` 不动），
  经 `rule_hint` 返回 UNCERTAIN 判定，并附候选文件列表与 `abstain_reason` 说明文本；
  **绝不升格 MATCHED**，也**不判「缺失/不合规」**。
- **锚点来源（永不使用系统时间）**：`EXPLICIT_CONFIG` > `CHECKLIST_DECLARATION` > `MATERIAL_DATE`；
  `assert_no_system_clock()` 为源码级守卫，纯整数月运算，不引入 datetime。
- **R4 闸**：候选 MATCH/PARTIAL 但期间依据不足 ⇒ 报 `CANDIDATE_%i_PERIOD_BASIS_INSUFFICIENT`；
  期间不符 ⇒ `CANDIDATE_%i_PERIOD_MISMATCH`。

## 笔1：C-1 / F-1 修复（先于段 2 落远端）

- **C-1**：文本同时含相对期间字面与四位年份时，单年 EXPLICIT 分支先 return
  ⇒ 相对期间语义被静默丢弃（危害方向：自信地紧）。
  修法：新增 `_has_relative_marker()`，含相对期间字面时改走相对期间分支（可被锚点展开）；
  明确区间仍最优先。回归用例 2 条。
- **F-1**：`test_module_has_no_second_doc_type_table` 的 AST 收集只取 `node.module`，
  不看 `node.names` ⇒ 包级写法 `from cangjie_fos.services import dd_v1_requirement_service` 逃逸。
  修法：抽出 `_imported_module_names()` 同时收两者；并加阳性对照用例（守卫必须抓到包级写法）。

## 仓内证据件

- `before_after_period.py`：同一合成输入集（9 条需求 × 同口径）在**基座树**与**改动树**各跑一次，
  逐行对照「候选状态 + 规则判定」。用法：`python3 before_after_period.py <代码树根目录>`。

```bash
python3 docs/dd-v1-fos71/player2-r2-wp1/before_after_period.py /workspace/fos-wt2
```
