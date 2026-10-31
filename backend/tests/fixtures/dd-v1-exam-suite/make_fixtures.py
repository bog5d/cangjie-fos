#!/usr/bin/env python3
"""DD-V1 **自动考试套件** · 合成夹具生成器（**零真实业务内容**）。

**干什么**：生成三套合成考试（考试 A 基础功能 / 考试 B 复杂业务 / 考试 C 完整 42 题）的
材料、清单与**声明式期望**。

★ **为什么期望（expectations）不直接写 ``obligation_id``**：
  库内义务主键 ``obligation_id`` 是 ``uuid4``（**每次建库都变**），
  内容派生的稳定键是 ``obligation_key``。
  ⇒ 期望只按**题号 + 材料相对路径**表达（人工语义审阅后冻结），
    由 ``tools/dd_v1_exam_suite.py`` 在建库后**从库侧权威契约**导出义务标识。
  ⇒ **标准答案与系统同源** ⇒ 杜绝「Gold 自造一套 ID ⇒ 永远对不上」这类夹具级自证。

**运行**::

    python backend/tests/fixtures/dd-v1-exam-suite/make_fixtures.py

★ 生成物全部落在本目录内（``exams/``），可重复生成（幂等）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMS = HERE / "exams"

# ── 合成主体（全部虚构，不对应任何真实企业） ────────────────────────────────
PARENT = "合成母公司"
SUB_A = "合成子公司甲"
SUB_B = "合成子公司乙"

#: 合成材料正文模板（★ 不含任何真实业务内容）
BODY = ("{entity} {year}年度 {doc_cn}\n"
        "合成测试材料：仅用于 DD-V1 自动考试体系，不含任何真实业务内容。\n"
        "用途：{part}。\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _material(entity: str, year: int | str, doc_cn: str, part: str,
              fname: str | None = None, content: str | None = None) -> str:
    """写一份合成材料，返回相对路径（相对材料根）。"""
    stem = fname or f"{entity}_{year}年度_{doc_cn}_{part}.txt"
    rel = f"{entity}/{stem}"
    text = content if content is not None else BODY.format(
        entity=entity, year=year, doc_cn=doc_cn, part=part)
    _write(EXAMS / "_materials_tmp" / rel, text)
    return rel


def _spec(exam_id: str, title: str, lib: str, institution: str,
          entities: list[dict], anchor_year: int) -> dict:
    return {
        "exam_id": exam_id,
        "title": title,
        "library_id": lib,
        "institution": institution,
        "anchor_year": anchor_year,
        "entities": entities,
        "checklist_file": "checklist.tsv",
        "expectations_file": "expectations.json",
        "materials_dir": "materials",
        "note": ("★ 合成考场：材料、清单、标准答案期望全部为**合成数据**，"
                 "不含任何真实客户材料；实体名称均为虚构。"),
    }


def _ents(parent_id: str = "E01") -> list[dict]:
    return [
        {"id": "E01", "name": PARENT, "relation": "parent", "group_root": True,
         "source": "合成登记（自动考试专用，非真实依据）"},
        {"id": "E02", "name": SUB_A, "relation": "subsidiary", "parent": parent_id,
         "source": "合成登记（自动考试专用，非真实依据）"},
        {"id": "E03", "name": SUB_B, "relation": "subsidiary", "parent": parent_id,
         "source": "合成登记（自动考试专用，非真实依据）"},
    ]


# ══════════════════════════════════════════════════════════════════════════
# 考试 A · 基础功能（3 题 · 单主体 · 6 份材料）
# ══════════════════════════════════════════════════════════════════════════
def build_exam_a() -> None:
    root = EXAMS / "A"
    if (root / "materials").exists():
        shutil.rmtree(root / "materials")
    mats = root / "materials"

    def mat(entity: str, year: int | str, doc_cn: str, part: str,
            fname: str | None = None, content: str | None = None) -> str:
        stem = fname or f"{entity}_{year}年度_{doc_cn}_{part}.txt"
        rel = f"{entity}/{stem}"
        text = content if content is not None else BODY.format(
            entity=entity, year=year, doc_cn=doc_cn, part=part)
        _write(mats / rel, text)
        return rel

    # ★ **业务口径**：审计报告是「一年一份」法定文件 ⇒ 同一主体同一年度**只有一份**
    #   （拆成正文/附注两份 ⇒ 同主体同期双版本 ⇒ 系统判**真 CONFLICT** 需人工裁定，
    #     这不是缺陷，是**口径**）⇒ 多文件场景改用「合法多份」类型（营业执照 正本/副本）。
    a_audit = mat(PARENT, 2024, "审计报告", "正文")
    a_audit_2023 = mat(PARENT, 2023, "审计报告", "正文")          # ★ 错年份干扰
    a_license_a = mat(PARENT, 2024, "营业执照", "正本")
    a_license_b = mat(PARENT, 2024, "营业执照", "副本")            # ★ 合法多份（多文件要求）
    a_ops_2024 = mat(PARENT, 2024, "经营情况说明", "说明")          # ★ 无类型关键词

    checklist = [
        ("1-1", f"请提供{PARENT}2024年度审计报告"),
        ("1-2", f"请提供{PARENT}2024年度营业执照"),
        ("1-3", f"请提供{PARENT}2024年度经营情况说明"),
    ]
    _write(root / "checklist.tsv",
           "\n".join(f"{no}\t{raw}" for no, raw in checklist) + "\n")

    exp = {
        "meta": {
            "note": ("考试A：基础功能。★ 「1-3」刻意**不含材料类型关键词**"
                     "（旧规则拆解会整题丢弃 ⇒ P0-2 形态）；"
                     "★ 「1-2」是**多文件**要求（正本＋副本，缺一不算完成）；"
                     "★ 审计报告按「一年一份」口径只放一份（避免制造真冲突）。"),
            "confirmed_by": "合成测试（非人工批准）",
            "confirmed_at": "2026-10-30T00:00:00+08:00",
        },
        "questions": {
            "1-1": {"verdict": "MATCH", "expect_paths": [a_audit]},
            "1-2": {"verdict": "MATCH", "expect_paths": [a_license_a, a_license_b]},
            "1-3": {"verdict": "MATCH", "expect_paths": [a_ops_2024]},
        },
    }
    _write(root / "expectations.json", json.dumps(exp, ensure_ascii=False, indent=2))
    _write(root / "spec.json", json.dumps(
        _spec("DDV1-SYN-A", "考试A · 基础功能", "LIB-DDVE-A", "合成机构A",
              _ents()[:1], 2024), ensure_ascii=False, indent=2))
    print("A ok")


# ══════════════════════════════════════════════════════════════════════════
# 考试 B · 复杂业务（9 题 · 三主体母子 · 跨年度 · 多文件 · 缺失 · 歧义 · 幂等）
# ══════════════════════════════════════════════════════════════════════════
def build_exam_b() -> None:
    root = EXAMS / "B"
    if (root / "materials").exists():
        shutil.rmtree(root / "materials")
    mats = root / "materials"

    def mat(entity: str, year: int | str, doc_cn: str, part: str,
            fname: str | None = None, content: str | None = None) -> str:
        stem = fname or f"{entity}_{year}年度_{doc_cn}_{part}.txt"
        rel = f"{entity}/{stem}"
        text = content if content is not None else BODY.format(
            entity=entity, year=year, doc_cn=doc_cn, part=part)
        _write(mats / rel, text)
        return rel

    p_audit = mat(PARENT, 2024, "审计报告", "正文")
    p_audit_2023 = mat(PARENT, 2023, "审计报告", "正文")            # ★ 错年份干扰
    p_audit_draft = mat(PARENT, 2024, "审计报告", "草稿")            # ★ 版本干扰
    p_license_a = mat(PARENT, 2024, "营业执照", "正本")
    p_license_b = mat(PARENT, 2024, "营业执照", "副本")              # ★ 合法多份（多文件要求）
    p_ops_2023 = mat(PARENT, 2023, "经营情况说明", "说明")
    p_ops_2024 = mat(PARENT, 2024, "经营情况说明", "说明")
    a_2024 = mat(SUB_A, 2024, "审计报告", "正文")                    # ★ 错主体干扰
    a_2023 = mat(SUB_A, 2023, "审计报告", "正文")
    b_2024 = mat(SUB_B, 2024, "审计报告", "正文")
    b_2023 = mat(SUB_B, 2023, "审计报告", "正文")
    tax_a = mat(PARENT, 2024, "纳税证明", "正本")
    # ★ **同内容不同路径** ⇒ 标准答案按 SHA256 解析时**歧义** ⇒ 该条不可评分（分层）
    tax_b = mat(PARENT, 2024, "纳税证明", "正本",
                fname=f"{PARENT}_2024年度_纳税证明_正本_副本.txt",
                content=BODY.format(entity=PARENT, year=2024,
                                    doc_cn="纳税证明", part="正本"))

    checklist = [
        ("2-1", "请提供集团及下属公司2024年度审计报告"),       # ★ 多主体分簇（D1 形态）
        ("2-2", f"请提供{SUB_A}2023年度审计报告"),             # ★ 跨主体跨年度
        ("2-3", f"请提供{SUB_B}2024年度审计报告"),
        ("2-4", f"请提供{SUB_B}2022年度审计报告"),             # ★ 库中缺料 ⇒ MISSING
        ("2-5", f"请提供{PARENT}2024年度营业执照"),
        ("2-6", f"请提供{PARENT}近三年经营情况说明"),           # ★ 相对期间
        ("2-7", f"请提供{PARENT}2024年度审计报告和营业执照"),   # ★ 并列连接词 ⇒ 多义务
        ("2-8", f"请提供{PARENT}2024年度审计报告"),             # ★ 重复题（幂等）
        ("2-9", f"请提供{PARENT}2024年度纳税证明"),             # ★ Gold 歧义
    ]
    _write(root / "checklist.tsv",
           "\n".join(f"{no}\t{raw}" for no, raw in checklist) + "\n")

    exp = {
        "meta": {
            "note": ("考试B：复杂业务。覆盖 **多主体分簇 / 跨主体 / 跨年度 / 多文件 / "
                     "库中缺料 / 相对期间 / 并列多义务 / 重复题幂等 / Gold 内容歧义**。"),
            "confirmed_by": "合成测试（非人工批准）",
            "confirmed_at": "2026-10-30T00:00:00+08:00",
        },
        "questions": {
            # ★ 多主体：集团范围 ⇒ 一条库义务分簇到 3 个主体 ⇒ 期望材料是**并集**
            "2-1": {"verdict": "MATCH", "expect_paths": [p_audit, a_2024, b_2024]},
            "2-2": {"verdict": "MATCH", "expect_paths": [a_2023]},
            "2-3": {"verdict": "MATCH", "expect_paths": [b_2024]},
            "2-4": {"verdict": "MISSING", "expect_paths": []},
            "2-5": {"verdict": "MATCH", "expect_paths": [p_license_a, p_license_b]},
            "2-6": {"verdict": "MATCH", "expect_paths": [p_ops_2023, p_ops_2024]},
            "2-7": {"verdict": "MATCH", "expect_paths": [p_audit, p_license_a, p_license_b],
                    "note": "并列连接词 ⇒ 拆成两条原子义务；期望按**题**表达 ⇒ 按材料类型落到各条"},
            "2-8": {"verdict": "MATCH", "expect_paths": [p_audit]},
            "2-9": {"verdict": "MATCH", "expect_paths": [tax_a],
                    "note": "★ 同内容两份（tax_b）⇒ SHA256 解析**歧义** ⇒ 该条不可评分"},
        },
    }
    _write(root / "expectations.json", json.dumps(exp, ensure_ascii=False, indent=2))
    _write(root / "spec.json", json.dumps(
        _spec("DDV1-SYN-B", "考试B · 复杂业务", "LIB-DDVE-B", "合成机构B",
              _ents(), 2024), ensure_ascii=False, indent=2))
    print("B ok")


# ══════════════════════════════════════════════════════════════════════════
# 考试 C · 完整 42 题（真实尽调业务规模 · 三主体 · 91 条义务量级）
# ══════════════════════════════════════════════════════════════════════════
def build_exam_c() -> None:
    root = EXAMS / "C"
    if (root / "materials").exists():
        shutil.rmtree(root / "materials")
    mats = root / "materials"
    ents = [PARENT, SUB_A, SUB_B]
    # ★ 考试C 的类型域：**只用规范 10 类里的年度类**（审计报告/纳税证明/财务报表）。
    #   理由（非事后放水）：考试C 量的是**规模与全卷覆盖**（42 题），
    #   「无规范类型关键词的题」属于**需要模型判定类型**的场景（``--resolve-doc-type``），
    #   它在考试A/B 与第三层（真实模型）里单独验 ⇒ 不混进 C 的理解率口径。
    docs = ["审计报告", "纳税证明", "财务报表"]
    checklist: list[tuple[str, str]] = []
    questions: dict[str, dict] = {}
    made: dict[tuple[str, str, int], str] = {}

    def material(entity: str, doc: str, year: int) -> str:
        key = (entity, doc, year)
        if key in made:
            return made[key]
        rel = f"{entity}/{entity}_{year}年度_{doc}_正文.txt"
        _write(mats / rel, BODY.format(entity=entity, year=year,
                                       doc_cn=doc, part="正文"))
        made[key] = rel
        return rel

    n = 42
    for i in range(1, n + 1):
        item_no = f"3-{i}"
        # ★ 三轴**互不同余** ⇒ 42 题落在**互不相同**的（主体 × 类型 × 年度）组合上
        #   ⇒ 每题有**自己那一份**材料（避免「42 题其实在重复答同几份」的假规模）。
        ent = ents[i % 3]
        doc = docs[(i // 3) % 3]
        year = 2020 + (i // 9)
        # ★ 每 10 题一道**受限类型**题（合同）：材料选得中，但**披露闸不放行**
        #   ⇒ 验证「受限材料不得进正式交付包」（安全闸正向证明）。
        restricted = (i % 10 == 0)
        if restricted:
            doc = "合同"
        # ★ 每 7 题一道**多主体**题（复刻真实考卷里的集团范围要求 ⇒ 分簇）
        multi = (i % 7 == 0) and not restricted
        # ★ 每 9 题一道**库中缺料**题（期望为空 ⇒ 该条应当判 MISSING/EXPECTED_NONE）
        #   ★ 缺料题刻意用**别的题从不用的年度**（2019）⇒ 否则多主体题顺带造出的
        #     同年同型材料会把「缺料」变成「其实有」⇒ 期望与事实对不上（夹具自相矛盾）。
        missing = (i % 9 == 0) and not multi and not restricted
        if missing:
            year = 2019
        if multi:
            raw = f"请提供集团及下属公司{year}年度{doc}"
        else:
            raw = f"请提供{ent}{year}年度{doc}"
        checklist.append((item_no, raw))
        if missing:
            questions[item_no] = {"verdict": "MISSING", "expect_paths": []}
            continue
        if multi:
            paths = [material(e, doc, year) for e in ents]
        else:
            paths = [material(ent, doc, year)]
        questions[item_no] = {"verdict": "MATCH", "expect_paths": paths}
    _write(root / "checklist.tsv",
           "\n".join(f"{no}\t{raw}" for no, raw in checklist) + "\n")
    _write(root / "expectations.json", json.dumps({
        "meta": {
            "note": ("考试C：完整 42 题。★ 复刻真实尽调业务规模（多主体 / 跨年度 / "
                     "缺料 / 受限类型），用于验证**全卷覆盖**与**分层评分**；"
                     "★ 42 题落在互不相同的（主体×类型×年度）组合上 ⇒ 每题有独立材料。"),
            "confirmed_by": "合成测试（非人工批准）",
            "confirmed_at": "2026-10-30T00:00:00+08:00",
        },
        "questions": questions,
    }, ensure_ascii=False, indent=2))
    _write(root / "spec.json", json.dumps(
        _spec("DDV1-SYN-C", "考试C · 完整42题", "LIB-DDVE-C", "合成机构C",
              _ents(), 2024), ensure_ascii=False, indent=2))
    print("C ok", len(checklist), "questions,", len(made), "distinct materials")


def main() -> int:
    EXAMS.mkdir(parents=True, exist_ok=True)
    build_exam_a()
    build_exam_b()
    build_exam_c()
    tmp = EXAMS / "_materials_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    print("done ->", EXAMS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
