# ⑤ 人工审核步骤（回执）

★ 本次为**合成**审核流：审核与批准动作由司仓在**合成 fixture** 上显式执行，
  记录真实退出码与产物，不涉及任何真实材料。

- review 命令退出码：**0**
- review_id：`d0d1ae4f91374bbb8ce69017c0ce2f0e`

## 真实命令与退出码

```
$ register --library SEVEN --root /Users/mac/.minimax/sessions/mvs_9d861162716f4f6785d5e4bf09d4941e/workspace/_7item/lib --authorized-by 波总7项成卷（合成）   # rc=0
$ entity --library SEVEN --id E1 --name 示例科技有限公司 --source 波总7项成卷（仓内合成 fixture）   # rc=0
$ entity --library SEVEN --id E2 --name 羊班 --source 波总7项成卷（仓内合成 fixture）   # rc=0
$ build --library SEVEN   # rc=0
$ parse --library SEVEN --no-docling   # rc=0
$ cards --library SEVEN   # rc=0
$ checklist --library SEVEN --file /Users/mac/.minimax/sessions/mvs_9d861162716f4f6785d5e4bf09d4941e/workspace/_7item/checklist.tsv --institution 某机构   # rc=0
$ match --library SEVEN   # rc=0
$ review --library SEVEN   # rc=0
```

## 声明

- 本包使用**仓内合成 fixture**（`backend/tests/fixtures/dd_v1_fos71_wp04/snapshot`），
  **零真实客户标识、零材料库代号**。
- Agent 结果为**预置合成回放**（`SYNTHETIC_REPLAY`），**零模型、零费用、零外部调用**；
  **不宣称**真实模型参与推理。
