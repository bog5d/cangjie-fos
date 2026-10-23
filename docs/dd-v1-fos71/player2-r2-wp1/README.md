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
