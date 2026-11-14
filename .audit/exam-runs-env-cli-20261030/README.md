# dsh 受控凭证通道（CLI）· 真实端到端证据

## 跑的是什么

用**本 PR 新增的 CLI 旗标** `--dsh-env-override` 跑了一场**真实模型**的考试 C：

```
python tools/dd_v1_exam_suite.py run --exam C --agent dsh --allow-local-dsh \
  --run-mode AGENT_REQUIRED --dsh-env-override DEEPSEEK_API_KEY --out <dir>
```

★ 凭证值**只**从本进程环境取（`os.environ`），命令行里**只有变量名**。

## 结果（运行清单 · model 块）

| 字段 | 值 |
|---|---|
| agent_spec | `dsh` |
| examinee_mode | `HARNESS_MODEL` |
| participated | `true` |
| requested_mode | `AGENT_REQUIRED` |
| **execution_path** | **`REAL_MODEL`** |
| actual_model | `deepseek-flash` |
| model_identity_verified | `true` |
| score_name | `AI_SYSTEM_SCORE` |
| total_score | **100.0** |
| 交付 / 归因 | 31 件 / 175 |
| safety_gate | `PASS` |
| failures | 0 |

## ★ 红线复验（本次实测）

对**整个输出目录**做明文扫描：

```
grep -rlF "$DEEPSEEK_API_KEY" <输出目录>   ⇒  无任何命中
```

⇒ answer.txt / stderr.log / run_record.json / 证据目录里**没有明文凭证**。

## 这份证据证明什么

1. **CLI 通道可达**（上游只有配置文件通道 ⇒ 每次换凭证都要改磁盘文件）；
2. **值只从本进程环境取**（`ps` / history / argv_summary 都看不到值）；
3. **名字缺失即拒绝**（不给 dsh 传空值，避免「看起来调用了、必然鉴权失败」的假调用）；
4. **stdout 脱敏已补齐**（上游只对 stderr 用合并环境 ⇒ 回显到 stdout 会明文落进 answer.txt）。
