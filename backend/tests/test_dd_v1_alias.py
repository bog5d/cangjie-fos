"""WP-A2（G-A2-8）：主体「别名/简称」归一 —— 让「材料库目录名」能被识别为**已登记**主体。

## 为什么需要（G-A2-8 的实测根因）

认知卡 ``card.entity`` 存的是**材料库目录名/简称**（provenance=INFERRED，
evidence.kind=path_segment）。而权威名单 ``dd_v1_entities`` 里登记的是**法定全称**
⇒ 两者**永不相等** ⇒ 哪怕把权威名单填上，主体仍 100% 判「未登记」，
MATCHED 仍出不来（监工第 27 轮实测）。

⇒ 修法（司仓裁定取「甲」路）：**把目录名/简称登记为该主体的别名**，匹配前归一。
目录名从此是「**被登记的简称**」，而不是「冒充主体」。

## 本文件锁死的红线

1. 别名匹配 ⇒ ``ent_ok=1``（不再 100% 未登记）；
2. 别名匹配的 provenance 必须是 **ALIAS / INFERRED**，**不得**是 FACT
   （「目录名对应该法人」是登记事实；「这份材料的主体就是该法人」仍需核实）；
3. **别名不得跨主体复用** —— 一个别名挂两个主体必须能检出并拒绝；
4. 别名必须挂在**已登记**主体上，且 ``source_ref`` 必填；
5. **未登记就是未登记** —— 不得把「空匹配」当通过；
6. 归一后的主体**不在本义务的主体范围内** ⇒ 不算命中（不得跨主体凑证据）；
7. **判定层与桥接层同一口径**（同一份材料两套说法是本轮要消灭的缺陷）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_card_service as cs,
    dd_v1_entity_service as es,
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
)

# 合成夹具：全用虚构名，不含任何真实机构
FULL_NAME = "杭州示例科技有限公司"
DIR_NAME = "杭州示例(1)"          # 材料库目录名（含副本后缀）
OTHER_FULL_NAME = "成都示例实业有限公司"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _setup(tmp_path, files: dict[str, str], lib="lib1"):
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.register_library(lib, str(root), authorized_by="A2", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _audit(year, entity="示例"):
    return f"审计报告\n本报告为{year}年度财务审计结论，由{entity}出具。\n"


def _register(tmp_path, lib, entity_id, name, relation="subsidiary"):
    rq.register_entity(lib, entity_id, name, relation=relation,
                       source_ref="工商登记（合成夹具）", db_path=_db(tmp_path))


def _card_for(tmp_path, lib, rel_path):
    conn = mf._connect(_db(tmp_path))
    row = conn.execute("SELECT * FROM dd_v1_manifest WHERE rel_path=?",
                       (rel_path,)).fetchone()
    assert row is not None, f"材料未入库：{rel_path}"
    return cs.get_card(row["file_id"], db_path=_db(tmp_path)), dict(row)


def _list_entities(tmp_path, lib):
    conn = mf._connect(_db(tmp_path))
    return [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_entities WHERE library_id=?", (lib,)).fetchall()]


# ═══════════════════════════════════════════════════════════════════════
# 1) 别名归一确实让「目录名」被识别为已登记主体
# ═══════════════════════════════════════════════════════════════════════


def test_alias_matches_directory_entity_and_ent_ok_is_true(tmp_path):
    """登记全称 + 登记目录名为别名 ⇒ 卡片 entity（= 目录名）**匹配到主体**。

    走**真实建卡管线**（不手工改写 card.entity）。
    """
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME,
                              source_ref="材料库目录名与法人对应关系（合成夹具）",
                              db_path=_db(tmp_path))

    card, row = _card_for(tmp_path, lib, f"{DIR_NAME}/审计报告2024.txt")
    assert card.get("entity") == DIR_NAME, \
        f"卡片 entity 应仍是目录名（不手工改写）：{card.get('entity')!r}"

    ents = _list_entities(tmp_path, lib)
    ev = ms.evaluate_file({"obligation_id": "T"}, card, row, ents)
    assert ev["entity_ok"] == 1, \
        f"别名登记后目录名必须能命中主体：{ev}"


def test_without_alias_subject_is_not_registered(tmp_path):
    """**反证**：不登记别名 ⇒ 目录名匹配不上 ⇒ 仍判「未登记」。

    这条锁的是「不得把空匹配当通过」：归一必须来自**登记**，不能来自猜。
    """
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)

    card, row = _card_for(tmp_path, lib, f"{DIR_NAME}/审计报告2024.txt")
    ents = _list_entities(tmp_path, lib)
    ev = ms.evaluate_file({"obligation_id": "T"}, card, row, ents)
    assert ev["entity_ok"] == 0, "没有登记别名就不得命中主体"
    m = es.match_entity(DIR_NAME, ents, es.alias_map(lib))
    assert m["matched"] is False
    assert m["basis"] == es.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════
# 2) 别名匹配的 provenance 必须是 ALIAS / INFERRED（不得是 FACT）
# ═══════════════════════════════════════════════════════════════════════


def test_alias_match_basis_is_inferred_not_fact(tmp_path):
    """别名命中 ⇒ basis=INFERRED、matched_by=alias；**不得**标 FACT。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME,
                              source_ref="材料库目录名与法人对应关系（合成夹具）",
                              db_path=_db(tmp_path))

    ents = _list_entities(tmp_path, lib)
    m = es.match_entity(DIR_NAME, ents, es.alias_map(lib))
    assert m["matched"] is True, f"别名应命中：{m}"
    assert m["basis"] == es.INFERRED, f"别名命中不得标 FACT：{m['basis']}"
    assert m["basis"] != es.FACT
    assert m["entity_id"] == "E1"
    assert m["display_name"] == FULL_NAME
    kinds = [e.get("kind") for e in m.get("evidence") or []]
    assert "alias_register" in kinds, f"证据来源应为 alias_register：{kinds}"


def test_full_name_match_is_still_fact(tmp_path):
    """**回归红线**：全称逐字相等 ⇒ 仍标 FACT（别名通道不得吞掉全称通道）。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    ents = _list_entities(tmp_path, lib)
    m = es.match_entity(FULL_NAME, ents, es.alias_map(lib))
    assert m["matched"] is True
    assert m["basis"] == es.FACT, f"全称命中必须是 FACT：{m['basis']}"


def test_alias_basis_recorded_as_alias_in_registry(tmp_path):
    """库内别名登记本身记 ``alias_basis=ALIAS`` 且带 ``source_ref``（可审计）。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="材料库目录名对应关系",
                              db_path=_db(tmp_path))
    rows = es.list_aliases(lib, db_path=_db(tmp_path))
    assert len(rows) == 1, f"应有 1 条别名登记：{rows}"
    assert rows[0]["entity_id"] == "E1"
    assert rows[0]["alias_basis"] == "ALIAS"
    assert rows[0]["source_ref"], "别名登记必须有依据出处"


# ═══════════════════════════════════════════════════════════════════════
# 3) 红线：别名不得跨主体复用 / 主体必须已登记 / source_ref 必填
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# F1 · 产品侧守卫（独立监工第 36 轮指出的缺口）：材料分类目录**不得**冒充主体
# ═══════════════════════════════════════════════════════════════════════

CLASSIFICATION_DIR = "1.审计报告"             # 材料分类目录（数字编号打头）
CLASSIFICATION_DIR2 = "10.车辆登记证、行驶证"  # 同形态，编号两位


def _obl_status(tmp_path, raw_text, lib):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


def test_classification_dir_alias_is_classified_as_directory():
    """形态像分类目录 ⇒ 必须是 ``DIRECTORY``（分类维度），不是主体维度。"""
    assert es.is_directory_alias(CLASSIFICATION_DIR)
    assert es.is_directory_alias(CLASSIFICATION_DIR2)
    assert not es.is_directory_alias("杭州示例(1)")
    assert es.classify_alias_kind(CLASSIFICATION_DIR) == es.ALIAS_KIND_DIRECTORY
    # ★ 形态判定**优先于声明** ⇒ 声明也救不了分类目录
    assert es.classify_alias_kind(CLASSIFICATION_DIR, "LEGAL") == es.ALIAS_KIND_DIRECTORY
    assert es.classify_alias_kind("杭州示例(1)", "USCI") == es.ALIAS_KIND_USCI
    assert es.classify_alias_kind("杭州示例(1)") == es.ALIAS_KIND_LEGAL


def test_registering_classification_dir_as_legal_alias_is_rejected(tmp_path):
    """★ 硬守卫：把分类目录**显式**登记成法定主体别名 ⇒ 必须被拒（不静默改写）。"""
    lib = _setup(tmp_path, {"杭州示例(1)/某材料.txt": "内容\n"})
    _register(tmp_path, lib, "E1", FULL_NAME)
    with pytest.raises(ValueError) as ei:
        es.register_entity_alias(lib, "E1", CLASSIFICATION_DIR,
                                 source_ref="测试：分类目录冒充主体",
                                 alias_kind="LEGAL", db_path=_db(tmp_path))
    assert "分类目录" in str(ei.value)
    # 拒了之后**没有**落库
    m = es.alias_map(lib, _db(tmp_path))
    assert es.normalize_name(CLASSIFICATION_DIR) not in m


def test_directory_alias_is_registered_but_excluded_from_subject_normalization(tmp_path):
    """分类目录别名**可以**登记（留痕），但**不参与主体归一**。"""
    lib = _setup(tmp_path, {"杭州示例(1)/某材料.txt": "内容\n"})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", CLASSIFICATION_DIR,
                             source_ref="测试：分类目录",
                             alias_kind=es.ALIAS_KIND_DIRECTORY,
                             db_path=_db(tmp_path))
    # 默认（include_directory=False）⇒ 不出现在别名表里 ⇒ 不参与归一
    m = es.alias_map(lib, _db(tmp_path))
    assert es.normalize_name(CLASSIFICATION_DIR) not in m
    # 显式要才有 ⇒ 但那只是「看看登记了什么」，不是拿去归一
    m_all = es.alias_map(lib, _db(tmp_path), include_directory=True)
    assert es.normalize_name(CLASSIFICATION_DIR) in m_all
    # 归一时匹配不上 ⇒ 主体未登记（**不得**用分类目录凑主体）
    hit = es.match_entity(CLASSIFICATION_DIR, [{"entity_id": "E1",
                                                "display_name": FULL_NAME}], m)
    assert hit["matched"] is False


def test_directory_alias_does_not_produce_conflict(tmp_path):
    """★ 回归锁的另一半：分类目录型别名**产不出 CONFLICT**。

    场景：同一个「分类目录」下两份**不同**内容的材料
    ⇒ 若分类目录被当成主体 ⇒ 同主体同期间异哈希 ⇒ 假 CONFLICT。
    ⇒ 加了守卫之后：主体不可判定 ⇒ 走「主体未登记」桶 ⇒ 不报冲突，只留痕。
    """
    lib = _setup(tmp_path, {
        f"{CLASSIFICATION_DIR}/材料一.txt": "第一份内容，内容不同。\n",
        f"{CLASSIFICATION_DIR}/材料二.txt": "第二份内容，内容也不同。\n",
    })
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", CLASSIFICATION_DIR,
                             source_ref="测试：分类目录",
                             alias_kind=es.ALIAS_KIND_DIRECTORY,
                             db_path=_db(tmp_path))
    st = _obl_status(tmp_path, "请提供年度审计报告", lib)
    assert st["verdict"] != "CONFLICT", \
        f"分类目录不得造出「同一主体」桶 ⇒ 不得报 CONFLICT：{st}"
    assert st.get("has_conflict") is False
    # ★ 但**必须留痕**（不静默丢弃）
    assert st.get("unknown_entities"), "分类目录材料仍须记入「主体未登记」留痕"


def test_alias_cannot_be_reused_across_entities(tmp_path):
    """**红线**：一个别名挂两个主体 ⇒ 必须能检出并**拒绝**（不覆盖、不静默改写）。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    _register(tmp_path, lib, "E2", OTHER_FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))
    with pytest.raises(ValueError) as exc:
        es.register_entity_alias(lib, "E2", DIR_NAME, source_ref="对应关系",
                                 db_path=_db(tmp_path))
    assert "跨主体复用" in str(exc.value), f"必须明确报跨主体复用：{exc.value}"
    rows = es.list_aliases(lib, db_path=_db(tmp_path))
    assert len(rows) == 1 and rows[0]["entity_id"] == "E1", \
        f"被拒绝的登记不得写入：{rows}"


def test_alias_requires_registered_entity(tmp_path):
    """**红线**：别名不能凭空存在 —— 主体必须先登记。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    with pytest.raises(ValueError) as exc:
        es.register_entity_alias(lib, "E-不存在", DIR_NAME, source_ref="对应关系",
                                 db_path=_db(tmp_path))
    assert "主体未登记" in str(exc.value), f"必须报主体未登记：{exc.value}"


def test_alias_requires_source_ref(tmp_path):
    """**红线**：别名也要有依据出处 —— ``source_ref`` 必填。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    with pytest.raises(ValueError) as exc:
        es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="  ",
                                 db_path=_db(tmp_path))
    assert "source_ref" in str(exc.value), f"必须要求依据出处：{exc.value}"


# ═══════════════════════════════════════════════════════════════════════
# 4) 归一后的主体必须在本义务范围内（不得跨主体凑证据）
# ═══════════════════════════════════════════════════════════════════════


def test_alias_outside_obligation_scope_is_not_counted(tmp_path):
    """别名归一后主体**不在本义务范围** ⇒ 不算命中。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    _register(tmp_path, lib, "E2", OTHER_FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))

    ents = _list_entities(tmp_path, lib)
    scope = [e for e in ents if e["entity_id"] == "E2"]     # 本义务只要求 E2
    m = ms._match_subject(DIR_NAME, scope, es.alias_map(lib))
    assert m["matched"] is False, "范围外的主体不得算命中"
    kinds = [e.get("kind") for e in m.get("evidence") or []]
    assert "subject_out_of_scope" in kinds, f"必须留痕：{kinds}"


def test_canonical_subject_folds_alias_to_display_name(tmp_path):
    """``canonical_subject``：目录名 ⇒ 权威显示名（**归一后同一主体落进同一个桶**）。"""
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))
    ents = _list_entities(tmp_path, lib)
    amap = es.alias_map(lib)
    assert es.canonical_subject(DIR_NAME, ents, amap) == FULL_NAME
    assert es.canonical_subject(FULL_NAME, ents, amap) == FULL_NAME
    assert es.canonical_subject("完全不存在的目录", ents, amap) == ""


def test_copy_suffix_is_normalized_conservatively(tmp_path):
    """副本后缀归一是**保守**的：只去尾部的 ``(1)`` 之类，不动中间字符。"""
    assert es.normalize_name("杭州示例(1)") == es.normalize_name("杭州示例")
    assert es.normalize_name("杭州示例科技有限公司") == "杭州示例科技有限公司"
    assert es.normalize_name("  A B  ") == "a b"


# ═══════════════════════════════════════════════════════════════════════
# 5) 判定层与桥接层同一口径（监工第 27 轮附带发现）
# ═══════════════════════════════════════════════════════════════════════


def test_bridge_and_judgment_use_same_subject_basis(tmp_path):
    """同一份材料，**判定层与桥接层**的主体口径必须一致。

    缺陷原貌：桥接侧 100% ``CARD_INFERRED``，判定层查名单 ⇒ 同一份材料两套说法。
    修法后：两边都归一到同一权威主体，且**都标明是别名归一**（INFERRED，不是 FACT）。
    """
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))

    card, _row = _card_for(tmp_path, lib, f"{DIR_NAME}/审计报告2024.txt")
    ents = _list_entities(tmp_path, lib)
    amap = es.alias_map(lib)

    # 判定层：目录名归一后命中的主体
    j = ms._match_subject(card.get("entity") or "", ents, amap)
    assert j.get("matched") is True, f"判定层应命中：{j}"

    # 桥接层：同一口径（build_meta 逐材料给出 entity + entity_basis）
    from cangjie_fos.services import dd_v1_bridge_service as bs
    meta, _stats = bs.build_meta(lib, db_path=_db(tmp_path))
    item = next(m for m in meta if m.get("relative_path") == f"{DIR_NAME}/审计报告2024.txt")

    assert item["entity"] == j["display_name"], \
        f"两侧主体必须一致：判定={j['display_name']} 桥接={item['entity']}"
    assert item["entity_basis"] == "ALIAS_RESOLVED", \
        f"桥接侧必须标明是别名归一：{item['entity_basis']}"
    assert _stats["entity_alias_resolved"] == 1, \
        f"桥接侧应记 1 条别名归一：{_stats}"


def test_bridge_entity_basis_alias_resolved(tmp_path):
    """桥接层命中别名时，主体档必须是 ``ALIAS_RESOLVED``，**不得**升格成 ``AUTHORITY``。

    （别名命中**不等于**材料主体已核实 —— 红线：不得把候选当成「这一家的材料」。
    桥接层据此把 ``subject_verified`` 置为 False。）
    """
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))
    from cangjie_fos.services import dd_v1_bridge_service as bs
    meta, _stats = bs.build_meta(lib, db_path=_db(tmp_path))
    item = next(m for m in meta if m.get("relative_path") == f"{DIR_NAME}/审计报告2024.txt")
    assert item["entity_basis"] == "ALIAS_RESOLVED"
    assert item["entity_basis"] != "AUTHORITY", \
        "别名归一不得升格为权威直命中（subject_verified 的依据就是这一档）"


def test_bridge_obligations_subject_verified_false_for_alias(tmp_path):
    """义务侧：别名归一 ⇒ ``entity_basis=ALIAS_RESOLVED`` ⇒ 证据 ``subject_verified=False``。

    走完整的 ``bridge_library``（RULE_ONLY，零外部调用）。
    """
    lib = _setup(tmp_path, {f"{DIR_NAME}/审计报告2024.txt": _audit(2024)})
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2024年度审计报告"}],
                        db_path=_db(tmp_path))

    from cangjie_fos.services import dd_v1_bridge_service as bs
    res = bs.bridge_library(lib, db_path=_db(tmp_path), allow_real_material=True)
    obl = res.get("obligations") or []
    assert obl, "应产出语义义务"
    bases = {o.get("entity_basis") for o in obl}
    assert "ALIAS_RESOLVED" in bases, f"义务侧主体档应体现别名归一：{bases}"
    for o in obl:
        assert o.get("subject_verified") is False, \
            f"别名归一不得算「主体已核实」：{o.get('entity_basis')}"


# ═══════════════════════════════════════════════════════════════════════
# 6) 权威名单非空时不再 100% 未登记（判据④）
# ═══════════════════════════════════════════════════════════════════════


def test_registered_entities_plus_alias_no_longer_100_percent_unregistered(tmp_path):
    """**判据④**：登记主体 + 别名后，「主体未登记」不再 100%。"""
    lib = _setup(tmp_path, {
        f"{DIR_NAME}/审计报告2024.txt": _audit(2024),
        f"{DIR_NAME}/审计报告2023.txt": _audit(2023),
    })
    _register(tmp_path, lib, "E1", FULL_NAME)
    es.register_entity_alias(lib, "E1", DIR_NAME, source_ref="对应关系",
                              db_path=_db(tmp_path))
    ents = _list_entities(tmp_path, lib)
    amap = es.alias_map(lib)

    total = 0
    unregistered = 0
    for rel in (f"{DIR_NAME}/审计报告2024.txt", f"{DIR_NAME}/审计报告2023.txt"):
        card, _row = _card_for(tmp_path, lib, rel)
        total += 1
        if not es.match_entity(card.get("entity") or "", ents, amap)["matched"]:
            unregistered += 1
    assert total == 2
    assert unregistered == 0, \
        f"登记别名后不应再有未登记：{unregistered}/{total}"
