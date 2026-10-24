# MINOR-4 fixture 豁免闸口 · 证据包

本目录是 `docs/dd-v1-fos71/wp05-real-integration/MINOR4-FIXTURE-GATE-ERRATA.md`（勘误二次修订）的证据附件。

| 文件 | 内容 |
|---|---|
| `probe_minor4_fixture_gate.py` | 四组对照探针（A/B/B'/C），可复跑；零真实客户标识 |
| `probe-result-before.json` | **修前**读数（被测代码 sha256 `15282351088537ee…`）⇒ `PROBE_VERDICT=REPRODUCED` |
| `probe-result-after.json` | **修后**读数（被测代码 sha256 `e8d85b8327c9db3b…`）⇒ `PROBE_VERDICT=FIXED` |
| `regression-tests.txt` | 回归守卫 5 条：**修前 3 红 / 修后 5 绿**（判别力已验证） |
| `SHA256SUMS.txt` | 本目录各文件 sha256 |

★ 两份 JSON 是探针**原始输出**，仅**本地绝对路径**前缀做了脱敏（`<REPO_BASE>` / `<REPO_FIX>` / `<WORKSPACE>` / `<PYTHON>`），其余字段逐字未改。
★ 探针默认在被测仓的**仓副本**上跑（副本的 ROOT = 副本位置）⇒ **不写/不删被测仓任何文件**。
★ 探针用的「仓外材料」是自造合成文本（指纹 `MINOR4-PROBE-MARKER`），零真实客户标识。
★ 复跑命令见勘误文档 §6。
