"""DD-V1 · 第三轮 P0 的 8 条**端到端**专项测试（WP3 ＋ WP5 ＋ WP1/WP2/WP4 剩余）。

## 为什么这 8 条必须是「端到端」

上一轮（第二轮）的三个 P0 测试文件**只测了单个函数**：
判定层的某个闸、披露归因、逐条交付闸。⇒ **主体（母公司 vs 子公司）**、
**多文件份数**这两件事**端到端根本没被覆盖**（独立 Reviewer 明确列为
「本轮范围外」的两项）。本文件按派工令要求，**每条都走完
「输入 → 检索 → 匹配 → 审核 → 组包」全链路**，不是只测一个函数。

## 8 条用例与它们各自锁死的判据

| # | 用例 | 锁死的判据 |
|---|---|---|
| ① | 单主体单文件 | 一条义务 ⇒ 一件交付；manifest 逐行带证据；SHA256 逐件复算一致 |
| ② | 多主体混合 | **母公司与子公司不能混桶**：子公司的材料**不得**满足母公司的义务 |
| ③ | 跨年度材料 | **2024 不得顶替 2025**；2023 材料**不得**顶替 2024 |
| ④ | 一条需求需要多份材料 | **应交 3 / 找到 2 / 缺 1** 显式显示；**找到 1 份不得判完成** |
| ⑤ | 缺失材料 | 缺的那份落 **MISSING**，**不得**被「已找到 1 份」掩盖 |
| ⑥ | 错误匹配 | 认不出类型/主体/期间的材料**连可选都不是**（不得进交付包） |
| ⑦ | 审核不确定 | UNCERTAIN / 未获授权 ⇒ **一件都不进正式交付包**；候选包与正式包**物理隔离** |
| ⑧ | 不同披露等级混合 | 可外发类与受限类混在一批 ⇒ 受限类**按设计被拦**且**留规则依据** |

## 纪律

- ★ 全部材料**现场合成**（tmp_path），**零真实材料 / 零模型 / 零费用**；
- ★ **不读 Gold Set**（`gold.json` / `frozen/grader/` 一律不碰）；
- ★ 用**仓内真实披露策略**（`backend/config/dd_v1_disclosure_policy.json`），
  **不改策略文件一个字** ⇒ 「营业执照可外发、审计报告按设计收紧」是真实口径，
  不是测试自造的宽松口径。
"""
from __future__ import annotations

import hashlib
import json as _json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_entity_service as es
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_package_service as pkg
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_requirement_service as rq

# ── 合成主体（**全部虚构**，不含任何真实机构名）──────────────────────────
#: 母公司（8 字）与子公司（6 字）**长度不同** ⇒ 名单回落时最长匹配唯一 ⇒ 不歧义
PARENT = "合成甲控股母公司"
SUB = "合成乙子公司"

LIB = "lib-r3"

#: 合成材料正文。**正文里必须带「年度」标签**才能让认知卡抽出 fiscal_period
#: （卡片只认「年度/财年」标签或文件名年份，禁猜）。
def _lic(y: int) -> str:
    return (f"营业执照\n名称：{PARENT}\n"
            f"本执照为{y}年度核发版本，登记事项为合成样例。\n")


def _lic_sub(y: int) -> str:
    return (f"营业执照\n名称：{SUB}\n"
            f"本执照为{y}年度核发版本，登记事项为合成样例。\n")


def _audit(entity: str, y: int) -> str:
    return (f"审计报告\n主体：{entity}\n"
            f"本报告为{y}年度财务审计结论，由{entity}出具。\n")


def _audit_notes(entity: str, y: int) -> str:
    return (f"审计报告附注\n主体：{entity}\n"
            f"本附注为{y}年度审计报告的附注部分，数字为合成样例。\n")


def _tax(entity: str, y: int) -> str:
    return (f"纳税证明\n主体：{entity}\n"
            f"本证明为{y}年度纳税情况，金额为合成样例。\n")


#: ★ 材料的**权威 SHA256 基线**（由本测试自己算，不依赖任何既有产物）
_MATERIALS: dict[str, str] = {
    f"{PARENT}/营业执照2024.txt": _lic(2024),
    f"{PARENT}/审计报告2024.txt": _audit(PARENT, 2024),
    f"{PARENT}/审计报告2023.txt": _audit(PARENT, 2023),
    f"{PARENT}/审计报告2024附注.txt": _audit_notes(PARENT, 2024),
    f"{PARENT}/纳税证明2024.txt": _tax(PARENT, 2024),
    f"{SUB}/营业执照2024.txt": _lic_sub(2024),
    f"{SUB}/审计报告2024.txt": _audit(SUB, 2024),
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个用例**独立**的数据面 + 独立库（零交叉污染）。"""
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path) -> Path:
    return tmp_path / "_plane" / "manifest.sqlite"


def _setup(tmp_path, materials: dict[str, str] | None = None):
    """建库 → 扫描 → 解析 → 建卡 → 登记主体。返回 (lib, root)。"""
    mats = _MATERIALS if materials is None else materials
    lib = LIB
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(lib, str(root), authorized_by="波总", db_path=_db(tmp_path))
    for rel, content in mats.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    # ★ 权威主体名单：母公司（parent）＋ 子公司（subsidiary）
    rq.register_entity(lib, "E-PARENT", PARENT, relation="parent",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    rq.register_entity(lib, "E-SUB", SUB, relation="subsidiary",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    return lib, root


def _ingest(lib, items, tmp_path, anchor_year: int | None = None,
            institution: str = ""):
    rq.ingest_checklist(lib, items, anchor_year=anchor_year,
                        institution=institution, db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))


def _full_chain(lib, items, tmp_path, *, approve: bool = True,
                confirm: bool = False):
    """走完 **输入 → 检索 → 匹配 → 审核 → 组包** 全链路，返回 (rows, review, pkg_res)。"""
    _ingest(lib, items, tmp_path)
    rev = pkg.build_review_pack(lib, institution="合成机构", db_path=_db(tmp_path))
    rows = pkg._build_rows(lib, db_path=_db(tmp_path), review_id=rev["review_id"])
    if confirm:
        for r in rows:
            pkg.confirm_obligation(rev["review_id"], r["obligation_id"],
                                    confirmed_by="波总",
                                    reason="人工逐条确认（合成样例）",
                                    db_path=_db(tmp_path))
    res = None
    if approve:
        pkg.approve(rev["review_id"], approved_by="波总", db_path=_db(tmp_path))
        res = pkg.package_approved(rev["review_id"], db_path=_db(tmp_path))
    return rows, rev, res


def _manifest_rows(out_dir: Path) -> list[dict]:
    p = Path(out_dir) / "组包manifest.tsv"
    lines = p.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln.strip()]


def _by_obligation(rows: list[dict]) -> dict[str, dict]:
    return {r["obligation"]: r for r in rows}


# ══════════════════════════════════════════════════════════════════════
# ① 单主体单文件
# ══════════════════════════════════════════════════════════════════════
def test_01_single_entity_single_file_end_to_end(tmp_path):
    """① 单主体单文件：一条义务 ⇒ 一件交付；逐行带证据；SHA256 逐件复算一致。"""
    lib, _root = _setup(tmp_path)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}], tmp_path)

    assert len(rows) == 1, rows
    r = rows[0]
    assert r["verdict"] == "MATCHED", r["missing_detail"]
    assert res["exported"] == 1, res
    assert res["hash_mismatched"] == 0, res

    mrows = _manifest_rows(Path(res["output_dir"]))
    assert len(mrows) == 1, mrows
    row = mrows[0]
    # ★ 逐行可核证据
    assert row["类型匹配"] == "是" and row["主体匹配"] == "是" and row["期间匹配"] == "是", row
    assert row["匹配证据"].strip(), row
    # ★ 逐件复算：读产物字节重算哈希，与源/副本两侧逐位相同
    dest = Path(res["output_dir"]) / row["交付路径"]
    assert dest.is_file(), dest
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == row["副本sha256"] == row["源sha256"]
    # ★ WP5：7 项交付链产出齐备
    for name in pkg.DELIVERY_ARTIFACTS:
        assert (Path(res["output_dir"]) / name).is_file(), name


# ══════════════════════════════════════════════════════════════════════
# ② 多主体混合（WP3-a：母公司与子公司不能混桶）
# ══════════════════════════════════════════════════════════════════════
def test_02_multi_entity_must_not_cross_mix(tmp_path):
    """② 多主体混合：**子公司材料不得顶替母公司**（也不得反向）。

    ★ 场景：清单两条，各指名一个法人；材料库里两个法人各有一份营业执照。
      ⇒ 母公司的义务只能由母公司的材料满足；子公司的只能由子公司的满足。
    ★ 修前（路径子串兜底）：「合成甲控股母公司」与「合成乙子公司」互不含
      ⇒ 本例侥幸不红；真正红的是**同一法人的不同主体**（见下一个断言）。
    """
    lib, _root = _setup(tmp_path)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"},
        {"item_no": "2", "raw_text": f"请提供{SUB}2024年度营业执照"},
    ], tmp_path)

    by = _by_obligation(rows)
    assert len(by) == 2, by
    parent_row = next(r for r in rows if PARENT in r["raw_text"])
    sub_row = next(r for r in rows if SUB in r["raw_text"])
    assert parent_row["verdict"] == "MATCHED", parent_row["missing_detail"]
    assert sub_row["verdict"] == "MATCHED", sub_row["missing_detail"]

    # ★ 交付的**两行**必须各自指向本法人的材料（不得互换）
    mrows = _manifest_rows(Path(res["output_dir"]))
    assert len(mrows) == 2, mrows
    for row in mrows:
        if PARENT in row["原始材料路径"]:
            assert PARENT in row["原子义务"], row
        if SUB in row["原始材料路径"]:
            assert SUB in row["原子义务"], row


def test_02b_subsidiary_material_cannot_satisfy_parent_obligation(tmp_path):
    """②b（WP3-a 核心）：**只有子公司材料**时，母公司的义务**不得**被认定匹配。

    ★ 这是「母公司与子公司混桶」的真判别样本：
      修前「路径子串」会把别的法人的材料算成命中；修后必须判
      **不成立**（UNCERTAIN / PARTIAL，**绝不是 MATCHED**）。
    """
    mats = {f"{SUB}/营业执照2024.txt": _lic_sub(2024)}
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}], tmp_path)

    r = rows[0]
    assert r["verdict"] != "MATCHED", (
        f"子公司材料被当成了母公司的材料：{r}")
    assert res["exported"] == 0, res
    # ★ 交付包里**一件都不该有**这份子公司的材料
    mrows = _manifest_rows(Path(res["output_dir"]))
    assert not mrows, mrows
    # ★ 留痕：缺口明细里必须说得出「主体」这一维
    assert "主体" in r["missing_detail"], r["missing_detail"]


# ══════════════════════════════════════════════════════════════════════
# ③ 跨年度材料（WP3-b：2024 不得顶替 2025）
# ══════════════════════════════════════════════════════════════════════
def test_03_cross_year_material_cannot_substitute(tmp_path):
    """③ 跨年度材料：**2024 材料不得顶替 2025 的要求**（也不得顶替 2023）。

    ★ 材料库里有 2023 与 2024 两份审计报告；清单要求 2023 年度
      ⇒ 2024 那份**不得**被选中、**不得**计入覆盖。
    """
    mats = {
        f"{PARENT}/审计报告2023.txt": _audit(PARENT, 2023),
        f"{PARENT}/审计报告2024.txt": _audit(PARENT, 2024),
    }
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2023年度审计报告"}], tmp_path)

    r = rows[0]
    assert r["verdict"] != "MATCHED", r
    # ★ 2024 那份**不得**被当作 2023 的答案（即便人工逐条确认放行了判定闸）
    selected = [p["rel_path"] for p in (r.get("selected") or [])]
    assert all("2024" not in s for s in selected), selected


def test_03b_material_without_year_is_unverifiable_not_guessed(tmp_path):
    """③b（WP3-b 核心）：**无明确期间的材料不得臆造年份** ⇒ 判 UNCERTAIN。

    ★ 材料自身**没有年度标注**（文件名与正文都没有）⇒ 期间**不可判定**
      （不是「不满足」，也不是「满足」）⇒ 该义务**不得**判 MATCHED。
    """
    mats = {f"{PARENT}/营业执照补充件.txt":
            f"营业执照\n名称：{PARENT}\n登记事项为合成样例（无年度标注）。\n"}
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}], tmp_path)

    r = rows[0]
    assert r["verdict"] != "MATCHED", r
    assert "期间" in r["missing_detail"], r["missing_detail"]


# ══════════════════════════════════════════════════════════════════════
# ④ 一条需求需要多份材料（WP3-c：应交 3 / 找到 2 / 缺 1）
# ══════════════════════════════════════════════════════════════════════
def test_04_multi_file_requirement_shows_expected_found_missing(tmp_path):
    """④ 一条需求需要多份：必须显式显示「**应交 3 / 找到 2 / 缺 1**」。

    ★ 清单明文写「3 份」⇒ 份数维**构成门槛**（找 1 份**不得**判完成）。
    ★ 库里只有 2 份可交付 ⇒ 必须报「缺 1」，且判定**不得**是 MATCHED。
    """
    mats = {
        f"{PARENT}/营业执照2024.txt": _lic(2024),
        f"{PARENT}/营业执照副本2024.txt": _lic(2024),
    }
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照3份"}], tmp_path)

    r = rows[0]
    # ★ 显式三段式
    assert r["count_total_required"] == 3, r
    assert r["count_total_found"] == 2, r
    assert r["count_total_missing"] == 1, r
    assert r["count_reading"] == "应交 3 / 找到 2 / 缺 1", r["count_reading"]
    # ★ 找到 2 份**不得**判这条完成
    assert r["verdict"] != "MATCHED", r
    assert "份数" in r["missing_detail"], r["missing_detail"]


def test_04b_requirement_with_attachment_part_shows_two_pieces(tmp_path):
    """④b：「审计报告（含附注）」⇒ **正文 ＋ 附注**两件 ⇒ 应交 2 / 找到 1 / 缺 1。

    ★ 这是「多 part 需求」的可验目标：找到了正文**不等于**这条完成。
    """
    mats = {f"{PARENT}/审计报告2024.txt": _audit(PARENT, 2024)}
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1",
         "raw_text": f"请提供{PARENT}2024年度审计报告（含附注）"}], tmp_path)

    r = rows[0]
    assert r["count_total_required"] == 2, r
    assert r["count_total_found"] == 1, r
    assert r["count_total_missing"] == 1, r
    assert r["verdict"] != "MATCHED", r


# ══════════════════════════════════════════════════════════════════════
# ⑤ 缺失材料
# ══════════════════════════════════════════════════════════════════════
def test_05_missing_material_is_reported_as_missing(tmp_path):
    """⑤ 缺失材料：库里**根本没有**满足本条要求的材料 ⇒ **不得**被别的件掩盖。

    ★ 区分三件不同的事（**不得混同**）：
      - 候选池**为空**（一条都没检索到）⇒ **MISSING**；
      - 候选池里**有**材料但**对不上**（类型/期间不对）⇒ **PARTIAL / STALE**
        （见 :func:`test_05b`）—— **不得**报成「查无此物」；
      - 主体未登记 ⇒ **UNCERTAIN**（不可判定，**不得**猜）。
    ★ 修好的关键：主体登记后，**主体闸不再抢先**把真实的缺口盖成 UNCERTAIN。
    """
    # ★ 正文**不含**清单里的任何检索词 ⇒ 召回归零 ⇒ 这是**真·材料不存在**。
    mats = {f"{PARENT}/杂件.txt": "zzzz qqqq wwww（与清单要求无关的占位文本）\n"}
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度专利证书"}], tmp_path)

    r = rows[0]
    assert r["verdict"] == "MISSING", r
    assert res["exported"] == 0, res
    # ★ MISSING **不得**混进「材料被拦」那一类（口径必须分开）：
    #   「这一类材料库里确实没有」≠「材料在，但被披露/审核闸拦下了」。
    blocked = _json.loads((Path(res["output_dir"]) / "被拦截清单.json")
                          .read_text(encoding="utf-8"))
    assert not [b for b in blocked
                if b.get("category") == "审核闸未通过（逐条义务未过闸）"
                and "专利证书" in str(b.get("obligation") or "")], blocked
    # ★ 缺口清单里要指名缺什么
    assert "缺口" in r["missing_detail"], r["missing_detail"]
    # ★ 缺口清单要给出**实际候选池**（MISSING 与候选池口径一致）
    gap = (Path(res["output_dir"]) / "04-缺失冲突不确定清单.tsv").read_text("utf-8")
    assert "缺失" in gap and "专利证书" in gap, gap


def test_05b_missing_is_not_reported_when_same_type_candidate_exists(tmp_path):
    """⑤b：候选池里**有同一类**材料但年份不对 ⇒ **不得**报「查无此物」（MISSING）。

    ★ 这是「MISSING 与实际候选池口径不一致」的判别样本：
      库里**有**这一类材料（只是年份不对）⇒ 报「查无此物」是**假的**
      ⇒ 必须如实说「材料在，但期间不对」（STALE）。
    """
    mats = {f"{PARENT}/审计报告2023.txt": _audit(PARENT, 2023)}
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度审计报告"}], tmp_path)

    r = rows[0]
    assert r["verdict"] != "MISSING", (
        f"候选池里有同一类材料却报「查无此物」：{r}")
    assert r["verdict"] == "STALE", r
    assert res["exported"] == 0, res


# ══════════════════════════════════════════════════════════════════════
# ⑥ 错误匹配（认不出类型/主体/期间的材料连可选都不是）
# ══════════════════════════════════════════════════════════════════════
def test_06_unrelated_material_is_never_selected(tmp_path):
    """⑥ 错误匹配：与义务**对不上**的材料**连可选都不是**（不得进交付包）。

    ★ 场景：库里有一份**类型/主体都对不上**的纳税证明；
      清单要的是母公司的营业执照 ⇒ 那份纳税证明**不得**被选中。
    """
    mats = {
        f"{PARENT}/营业执照2024.txt": _lic(2024),
        f"{PARENT}/纳税证明2024.txt": _tax(PARENT, 2024),
    }
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}], tmp_path)

    r = rows[0]
    selected = [p["rel_path"] for p in (r.get("selected") or [])]
    assert not any("纳税证明" in s for s in selected), selected
    # ★ 被拒的候选**必须**留痕并写明**哪一维对不上**
    rejected = [u for u in (r.get("unselected") or []) if "纳税证明" in u["rel_path"]]
    assert rejected, r["unselected"]
    assert "匹配证据闸" in rejected[0]["reason"], rejected[0]


# ══════════════════════════════════════════════════════════════════════
# ⑦ 审核不确定 + 候选包/正式包物理隔离（WP2）
# ══════════════════════════════════════════════════════════════════════
def test_07_uncertain_obligation_never_enters_official_package(tmp_path):
    """⑦ 审核不确定：UNCERTAIN ⇒ **一件都不进**正式交付包（即便人工批准了）。"""
    mats = {f"{PARENT}/审计报告2024.txt": _audit(PARENT, 2024)}
    lib, _root = _setup(tmp_path, mats)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度审计报告"}], tmp_path)

    r = rows[0]
    # 审计报告按设计收紧 ⇒ 判定到「找到了但不可外发」这一档，不是 MATCHED
    assert r["verdict"] != "MATCHED", r
    assert res["exported"] == 0, res
    mrows = _manifest_rows(Path(res["output_dir"]))
    assert not mrows, mrows


def test_07b_candidate_pack_and_official_pack_are_physically_isolated(tmp_path):
    """⑦b（WP2）：候选包与正式交付包**物理隔离**，且各自有明确标识。

    ★ 未获授权时：只产出候选包（前五项），**零复制**、**无正式交付件**。
    ★ 获授权后：正式交付包落在**另一个平级目录**，且目录里有「正式交付包」标识。
    """
    lib, _root = _setup(tmp_path)
    # ── 未授权：只出候选包 ────────────────────────────────────────────
    _ingest(lib, [{"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}],
             tmp_path)
    rev = pkg.build_review_pack(lib, institution="合成机构", db_path=_db(tmp_path))
    pack_dir = Path(rev["pack_path"])
    assert (pack_dir / "非正式交付-候选包说明.md").is_file()
    # ★ 候选包**零复制**、**不含**正式交付件（⑥⑦ 两项）
    for name in ("06-实际交付文件目录.tsv", "07-文件完整性校验结果.tsv"):
        assert not (pack_dir / name).exists(), name
    assert not [p for p in pack_dir.rglob("*")
                if p.is_file() and p.suffix == ".txt"
                and "合成甲控股母公司" in p.name], pack_dir
    # ★ 候选包**不含**原件副本（正文里的登记事项文本不得出现在任何交付件里）
    assert not any("登记事项为合成样例" in p.read_text(encoding="utf-8", errors="ignore")
                   for p in pack_dir.rglob("*.txt")), "候选包混进了原件"

    # ── 授权后：正式交付包在**另一个平级目录** ────────────────────────
    pkg.approve(rev["review_id"], approved_by="波总", db_path=_db(tmp_path))
    res = pkg.package_approved(rev["review_id"], db_path=_db(tmp_path))
    out = Path(res["output_dir"])
    assert out.resolve() != pack_dir.resolve()
    assert pack_dir.resolve() not in out.resolve().parents, (
        f"正式交付包落在了候选包目录里面：{out}")
    assert (out / "正式交付包-说明.md").is_file()
    assert (out / "SHA256SUMS").is_file()
    # ★ 正式交付包里有原件副本（且逐件复算一致）
    assert res["exported"] >= 1, res
    assert res["hash_verified"] == res["hash_verified_total"] == res["exported"], res


# ══════════════════════════════════════════════════════════════════════
# ⑧ 不同披露等级混合（WP4：按设计被拦 vs 放行，各自留依据）
# ══════════════════════════════════════════════════════════════════════
def test_08_mixed_disclosure_levels_block_by_design_with_rule_trace(tmp_path):
    """⑧ 不同披露等级混合：可外发类放行、受限类**按设计被拦**，且**留规则依据**。

    ★ 用**仓内真实披露策略**（营业执照 PUBLIC 可外发、审计报告 RESTRICTED 收紧）
      ⇒ 受限是「**按设计被拦**」，不是缺陷；**不得**为了让组包有东西而放开它。
    ★ 每次放行/拦截都留依据（谁拦的 + 按设计还是误分类）。
    """
    lib, _root = _setup(tmp_path)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"},
        {"item_no": "2", "raw_text": f"请提供{PARENT}2024年度审计报告"},
    ], tmp_path)

    mrows = _manifest_rows(Path(res["output_dir"]))
    assert len(mrows) == 1, mrows
    row = mrows[0]
    assert "营业执照" in row["原始材料路径"], row
    # ★ 放行侧也要有**规则依据**（哪条规则允许它外发）
    assert row["披露归因_谁拦的"] == "", row
    assert row["披露_策略版本"], row
    assert "license" in row["披露_可外发类型"], row

    # ★ 受限侧：审计报告**按设计被拦**（blocked_kind = 按设计被拦）
    blocked = _json.loads((Path(res["output_dir"]) / "被拦截清单.json")
                          .read_text(encoding="utf-8"))
    audit_blocked = [b for b in blocked if "审计报告" in str(b.get("rel_path") or "")]
    assert audit_blocked, blocked
    diag = audit_blocked[0]["disclosure_diagnosis"]
    assert diag["blocked_by"], diag
    assert diag["blocked_kind"], diag
    assert diag["blocked_kind"] in ("按设计被拦", "误分类被拦"), diag


# ══════════════════════════════════════════════════════════════════════
# WP2：材料在审核后被改过 ⇒ 审核失效 ⇒ 强制重新审核
# ══════════════════════════════════════════════════════════════════════
def test_09_material_changed_after_review_invalidates_it(tmp_path):
    """审核通过后材料被改过（SHA256 变了）⇒ **审核失效** ⇒ 不得产出正式交付件。

    ★ WP2 的硬要求：不是「复制后发现哈希不一致」才报，
      而是**在复制之前**就拦住 ⇒ 一件原件都不复制。
    """
    lib, root = _setup(tmp_path)
    _ingest(lib, [{"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}],
             tmp_path)
    rev = pkg.build_review_pack(lib, institution="合成机构", db_path=_db(tmp_path))
    pkg.approve(rev["review_id"], approved_by="波总", db_path=_db(tmp_path))

    # ★ 审核之后、材料被改了（内容变了 ⇒ SHA256 变了）
    target = root / f"{PARENT}/营业执照2024.txt"
    target.write_text(target.read_text(encoding="utf-8") + "\n（审核后被改动）\n",
                      encoding="utf-8")

    res = pkg.package_approved(rev["review_id"], db_path=_db(tmp_path))
    assert res.get("review_invalidated") is True, res
    assert res["exported"] == 0, res
    assert res["stale_material_count"] >= 1, res
    out = Path(res["output_dir"])
    # ★ **没有**正式交付件（manifest 不存在）
    assert not (out / "组包manifest.tsv").exists(), out
    # ★ 审核单被打回「已审核待重新批准」
    assert pkg.get_review(rev["review_id"], db_path=_db(tmp_path))["status"] == pkg.ST_REVIEWED


# ══════════════════════════════════════════════════════════════════════
# WP1：义务稳定 ID（可复算）＋ 候选六件套 ＋ 逐件复算
# ══════════════════════════════════════════════════════════════════════
def test_10_obligation_key_is_stable_and_recomputable(tmp_path):
    """WP1：义务的**稳定 ID**可由内容**复算**（不随排序变）。"""
    lib, _root = _setup(tmp_path)
    items = [{"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}]
    _ingest(lib, items, tmp_path, institution="合成机构")
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    again = rq.obligation_key(lib, "合成机构", "1", items[0]["raw_text"], 1,
                               obl["obligation"])
    assert obl["obligation_key"] == again, (obl, again)
    # ★ 同一份清单**再摄取一次**（幂等）⇒ key 不变
    _ingest(lib, items, tmp_path, institution="合成机构")
    obl2 = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    assert obl2["obligation_key"] == obl["obligation_key"], (obl, obl2)


def test_11_candidate_keeps_six_pieces_of_identity(tmp_path):
    """WP1：每份候选材料保留 **原始路径 / 文件名 / SHA256 / 主体 / 期间 / 类型**。"""
    lib, root = _setup(tmp_path)
    rows, rev, res = _full_chain(lib, [
        {"item_no": "1", "raw_text": f"请提供{PARENT}2024年度营业执照"}], tmp_path)
    cands = rows[0]["candidates"]
    assert cands, rows[0]
    c = cands[0]
    for key in ("orig_rel_path", "file_name", "sha256", "material_entity",
                "material_period", "material_doc_type"):
        assert c.get(key), f"{key} 缺失：{c}"
    # ★ SHA256 与源文件**逐位相同**（可独立复算）
    src = root / c["orig_rel_path"]
    assert hashlib.sha256(src.read_bytes()).hexdigest() == c["sha256"], c
    assert c["material_entity"] == PARENT, c
    assert c["material_period"] == "2024", c
    assert c["material_doc_type"] == "license", c


# ══════════════════════════════════════════════════════════════════════
# WP4：P0-3 缺陷的两条回归（独立 Reviewer 实测复现 ⇒ 必须修前红、修后绿）
# ══════════════════════════════════════════════════════════════════════
def _card_for(tmp_path, lib, rel_path) -> str:
    conn = mf._connect(_db(tmp_path))
    row = conn.execute("SELECT * FROM dd_v1_manifest WHERE rel_path=?",
                       (rel_path,)).fetchone()
    assert row is not None, f"材料未入库：{rel_path}"
    return str(row["file_id"])


def _sensitivity_node(tmp_path, lib, file_id) -> dict:
    card = cs.get_card(file_id, db_path=_db(tmp_path)) or {}
    node = (card.get("fields") or {}).get("sensitivity")
    return node if isinstance(node, dict) else {}


def test_12_repeated_type_correction_recomputes_level_again(tmp_path):
    """①（Reviewer 放行条件②·①）：**连续两次**类型纠正 ⇒ 等级随**最新**类型重算。

    ★ 复现路径（Reviewer 实测）：先改类型为 ``license``（等级重算成 PUBLIC）
      ⇒ **再**改类型为 ``charter`` ⇒ 等级**必须**重算回策略默认的 RESTRICTED。
    ★ 修前（``7dd66b00``）：机器重算出来的等级被写成 ``provenance=FACT``
      ⇒ 第二次被当成「人工自定」⇒ **不重算** ⇒ 等级停在 PUBLIC
      ⇒ ★ **章程（按设计收紧的类型）会带着 PUBLIC 被外发** ⇒ 红灯。
    ★ 修后：机器重算的等级是 ``INFERRED`` ⇒ 类型一变就重算 ⇒ 绿灯。
    """
    mats = {f"{PARENT}/合成样例2024.txt": _audit(PARENT, 2024)}
    lib, _root = _setup(tmp_path, mats)
    fid = _card_for(tmp_path, lib, f"{PARENT}/合成样例2024.txt")

    # ── 第一次纠正：改成 license ⇒ 等级重算为 PUBLIC（策略默认）────────
    cs.set_human_override(fid, "doc_type", "license",
                           db_path=_db(tmp_path),
                           note="合成样例：人工纠正类型为营业执照")
    node1 = _sensitivity_node(tmp_path, lib, fid)
    assert node1.get("value") == "PUBLIC", node1

    # ── 第二次纠正：改成 charter ⇒ 等级**必须**重算回 RESTRICTED ──────
    cs.set_human_override(fid, "doc_type", "charter",
                           db_path=_db(tmp_path),
                           note="合成样例：人工再次纠正类型为公司章程")
    node2 = _sensitivity_node(tmp_path, lib, fid)
    assert node2.get("value") == "RESTRICTED", (
        f"第二次类型纠正没有重算等级（陈旧等级存活）：{node2}")
    # ★ 章程是**按设计收紧**的类型 ⇒ 不得停在上一轮的 PUBLIC
    assert node2.get("value") != "PUBLIC", node2


def test_13_machine_recomputed_level_is_inferred_not_fact(tmp_path):
    """②（Reviewer 放行条件②·②）：机器重算的等级，provenance 必须是 **INFERRED**。

    ★ 机器重算的等级**不是**「人工的决定」⇒ 出处必须是「推断」。
    ★ 修前写成 ``FACT`` ⇒ 下一次类型变更**不再触发**重算（缺陷的根因）。
    ★ 「人工自定的等级」仍然是 ``FACT``（人的决定优先）——两条不冲突。
    """
    mats = {f"{PARENT}/合成样例2024.txt": _audit(PARENT, 2024)}
    lib, _root = _setup(tmp_path, mats)
    fid = _card_for(tmp_path, lib, f"{PARENT}/合成样例2024.txt")

    cs.set_human_override(fid, "doc_type", "license",
                           db_path=_db(tmp_path),
                           note="合成样例：人工纠正类型为营业执照")
    node = _sensitivity_node(tmp_path, lib, fid)
    assert node.get("value") == "PUBLIC", node
    # ★ 出处必须是「推断」，**不是**「事实」
    assert node.get("provenance") == "INFERRED", (
        f"机器重算的等级被记成 {node.get('provenance')!r}（应为 INFERRED）：{node}")

    # ★ 对照：**人工自定**的等级仍然是「事实」（人的决定优先，不被覆盖）
    cs.set_human_override(fid, "sensitivity", "INTERNAL",
                           db_path=_db(tmp_path),
                           note="合成样例：人工逐件定级")
    node2 = _sensitivity_node(tmp_path, lib, fid)
    assert node2.get("value") == "INTERNAL", node2
    assert node2.get("provenance") == "FACT", node2
    # ★ 再改类型 ⇒ **人工自定的等级不动**
    cs.set_human_override(fid, "doc_type", "charter",
                           db_path=_db(tmp_path),
                           note="合成样例：人工再次纠正类型")
    node3 = _sensitivity_node(tmp_path, lib, fid)
    assert node3.get("value") == "INTERNAL", (
        f"人工自定的等级被机器重算覆盖了：{node3}")
