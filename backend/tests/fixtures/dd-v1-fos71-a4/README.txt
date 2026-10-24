A4a 合成盲测 fixture（#71 WP-A4a）
==================================

用途：让「盲化 → 冻结 → 拆分 → 跑 → 评分」这条链路能**零成本**跑通（**链路自检**）。
★ 这里的一切都是**合成**材料：不调用任何模型、没有独立考生答卷、**不是**「盲考通过」。

目录：
  material/                合成材料（.txt）+ **手写** meta.json（不用 cmd_scaffold）
    主体甲/                  7 件（审计报告 2024 正文 / 附注 / 正文补充、审计报告 2023 正文、
                             社保缴纳证明 2024、营业执照 2024、审计报告 2024 **草稿** DRAFT）
    主体乙/                  1 件（审计报告 2024 正文）——**第二个 entity**
  raw_items.json           8 条合成条目（R1…R8）
  gold.json                合成 Gold（confirmed_by = 司仓机械核对（非人工批准））
  replies/                 预置回贴（run-<tag>.json + run-<tag>.provenance.json）
  make_synthetic_replies.py 预置回贴生成器（盲化 → 冻结 → 拆分 → 取证据 ⇒ 回贴）

形态约束（司仓第 3 条勘误）：
  * meta.json 手写：≥2 个 entity（主体甲 / 主体乙）+ ≥2 个 period（2024 / 2023）。
  * file_id 稳定编号 F00001…F00008 ⇒ 盲化改路径也不影响 Gold 对表。
  * 文件名**不以「数字 + 分隔符」开头**（避开 is_index_artifact 的索引件判定）。
  * 目录名 / 文件名 / 正文**故意**带题号（Q-2024-07）、机构名（案例甲机构 / 案例乙机构）、
    项目名（星海项目）⇒ 用来证明盲化有效（盲化后 grep 不到这些词）。
  * version_status=DRAFT 的件（F00007）不可被 MATCH/PARTIAL 引用（语义层当场拒收）。

泄漏词表（必须与说明书命令一致）：
  Q-2024-07, 案例甲机构, 案例乙机构, 星海项目

回贴设计（故意覆盖 6 类 + 1 例 UNCERTAIN）：
  R1 TP（verdict 对 + 文件集相等）
  R2 FP（文件集多出非期望件 F00002）
  R3 WRONG_PERIOD + CONFIDENT_MISMATCH（答 2023 的件、confidence 0.9）
  R4 WRONG_PERIOD（答 2023 的件、confidence 0.5）
  R5 FN（答 MISSING，期望有货）
  R6 UNCERTAIN（单列，**不进 FN**）
  R7 WRONG_ENTITY（答主体甲的件，Gold 期望主体乙的 F00008）
  R8 WRONG_FILE_SET（verdict/主体/期间对，文件集错选）
