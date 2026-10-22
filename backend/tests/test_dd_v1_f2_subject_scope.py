"""F2（MAJOR）· 主体指名范围 —— 前缀抽取失败时**回落查权威名单**。判别力用例。

## 病

`dd_v1_requirement_service.parse_entity_scope()` 的主体指名**只认一种形态**：
「<主体>：<要求>」（靠 `_SUBJECT_HINT_RE` 取冒号前缀，且前缀**必须含**标记词
公司/集团/银行/厂/所/中心/合作社/事务所/有限/股份/研究院/委员会）。

⇒ **两种形态都抽不出** ⇒ `entity_scope` 为空 ⇒ 主体维度永久不可判定 ⇒ 判 UNCERTAIN：

1. **主体在句中、原文无冒号**（例：「提供甲科技有限公司 2024 年度审计报告」）
   —— ★ 主体名再规范也抽不出（**司仓用本仓合成 fixture 独立复现**）。
2. **有冒号但主体名不含标记词**（例：「甲科技：提供营业执照」）
   —— ★ **独立监工第 35 轮已独立复现**。

★ **别名登记救不了**：失败发生在**抽取阶段**，压根没进查表路径。

## 治（口径：不猜不退化）

前缀口径与 FACT 范围口径都落空时，**回落查权威名单/别名表**：
本库登记的主体全称 + 库内别名（排除 DIRECTORY 型）在义务原文里**逐字**找一次。
只认逐字出现；最长匹配且唯一才取；同等长度指向不同主体 ⇒ **不猜**。

## 本文件锁死的六件事

- **F2-a 句中主体**：无冒号、主体名规范 ⇒ 回落命中 ⇒ scope = `entity_hint:<登记全称>`。
- **F2-b 无标记词别名**：冒号形态 + 别名不含标记词 ⇒ 回落命中（**别名从此才有机会生效**）。
- **F2-c 回落是最后一道**：FACT 范围（各全资子公司…）与文本前缀**优先**，回落不覆盖它们。
- **F2-d 不猜**：原文无登记串 ⇒ 仍 UNKNOWN；同等长度指向**不同主体** ⇒ 仍 UNKNOWN。
- **F2-e DIRECTORY 型别名不进回落词表**（分类目录是分类维度，不是主体标识）。
- **F2-f 端到端**：回落命中后，主体维度**成为门槛**（主体覆盖 = 1），不再 UNCERTAIN。

## 敏感纪律

主体名属客户标识 ⇒ 本文件一律用「甲公司 / 乙公司 / 丙公司 / 甲科技」等**虚构简称**，
且断言判据文案里**不出现原文**（脱敏后统一写「义务指名的主体（简称）」）。

## ★ 判别力（双向）

- 回退生产端（去掉回落路径）⇒ 本文件**必须 FAIL**（否则是「写了没验」的假账）；
- 回落命中时 ⇒ 判定**不得**误伤（合法路径必须照常走通）。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import (
    dd_v1_entity_service as es,
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_card_service as cs,
    dd_v1_requirement_service as rq,
)


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
    mf.register_library(lib, str(root), authorized_by="F2", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _register(tmp_path, lib, eid, name, relation="subsidiary"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _alias(tmp_path, lib, eid, alias, kind=None):
    es.register_entity_alias(lib, eid, alias, source_ref="工商登记",
                              alias_kind=kind, db_path=_db(tmp_path))


def _ingest(tmp_path, lib, raw_text):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    return rq.list_obligations(lib, db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════════
# F2-a 句中主体（无冒号）⇒ 回落命中
# ═══════════════════════════════════════════════════════════════════════════


def test_inline_subject_without_colon_resolves_via_registry(tmp_path):
    """「提供甲科技有限公司 …」—— 主体在句中、无冒号 ⇒ 回落命中。"""
    lib = _setup(tmp_path, {"甲科技有限公司/营业执照.txt": "营业执照 名称：甲科技有限公司"})
    _register(tmp_path, lib, "E1", "甲科技有限公司")
    obl = _ingest(tmp_path, lib, "提供甲科技有限公司 2024 年度审计报告")[0]
    assert obl["entity_scope"] == "entity_hint:甲科技有限公司"
    assert obl["entity_basis"] == rq.INFERRED


def test_inline_subject_resolves_without_registering_alias(tmp_path):
    """回落只认**登记过的**全称 ⇒ 不需要额外登记别名。"""
    lib = _setup(tmp_path, {"甲科技有限公司/营业执照.txt": "营业执照 名称：甲科技有限公司"})
    _register(tmp_path, lib, "E1", "甲科技有限公司")
    _alias(tmp_path, lib, "E1", "甲科技")
    obl = _ingest(tmp_path, lib, "提供甲科技有限公司 2024 年度审计报告")[0]
    # 最长匹配 ⇒ 命中登记全称（比别名长）
    assert obl["entity_scope"] == "entity_hint:甲科技有限公司"


# ═══════════════════════════════════════════════════════════════════════════
# F2-b 无标记词的主体/别名 ⇒ 回落命中（别名从此才有机会生效）
# ═══════════════════════════════════════════════════════════════════════════


def test_alias_without_marker_word_resolves_via_registry(tmp_path):
    """「甲科技：提供营业执照」—— 冒号形态但主体名**不含标记词** ⇒ 回落命中。"""
    lib = _setup(tmp_path, {"甲科技/营业执照.txt": "营业执照 名称：甲科技"})
    _register(tmp_path, lib, "E1", "甲科技集团")
    _alias(tmp_path, lib, "E1", "甲科技")
    obl = _ingest(tmp_path, lib, "甲科技：提供营业执照")[0]
    assert obl["entity_scope"] == "entity_hint:甲科技"
    assert obl["entity_basis"] == rq.INFERRED


def test_registry_fallback_picks_longest_registration(tmp_path):
    """最长匹配 ⇒ 更具体的那个（甲公司 vs 甲公司北京分公司）。"""
    lib = _setup(tmp_path, {"甲公司北京分公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    _register(tmp_path, lib, "E2", "甲公司北京分公司")
    obl = _ingest(tmp_path, lib, "提供甲公司北京分公司 2024 年度审计报告")[0]
    assert obl["entity_scope"] == "entity_hint:甲公司北京分公司"


# ═══════════════════════════════════════════════════════════════════════════
# F2-c 回落是**最后一道**（既有口径优先）
# ═══════════════════════════════════════════════════════════════════════════


def test_fact_scope_wins_over_registry_fallback(tmp_path):
    """FACT 范围（各全资子公司）优先于回落 ⇒ 回落**不得**覆盖它。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    obl = _ingest(tmp_path, lib, "提供各全资子公司的营业执照")[0]
    assert obl["entity_scope"] == "subsidiaries"
    assert obl["entity_basis"] == rq.FACT


def test_existing_prefix_form_unchanged(tmp_path):
    """既有前缀口径**一字不改**：无回落时也要照旧抽出。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    obl = _ingest(tmp_path, lib, "甲公司：最新的营业执照")[0]
    assert obl["entity_scope"] == "entity_hint:甲公司"
    assert obl["entity_basis"] == rq.INFERRED


# ═══════════════════════════════════════════════════════════════════════════
# F2-d 不猜（回落**不得**变成猜测器）
# ═══════════════════════════════════════════════════════════════════════════


def test_unregistered_subject_stays_unknown(tmp_path):
    """原文里的主体**没登记** ⇒ 仍 UNKNOWN ⇒ 不猜。"""
    lib = _setup(tmp_path, {"乙公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    obl = _ingest(tmp_path, lib, "提供丙公司 2024 年度审计报告")[0]
    assert obl["entity_scope"] == ""
    assert obl["entity_basis"] == rq.UNKNOWN


def test_ambiguous_same_length_does_not_guess(tmp_path):
    """同等长度、指向**不同主体**的两个登记串同时出现 ⇒ 不知该指谁 ⇒ 不猜。"""
    lib = _setup(tmp_path, {"甲乙公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲乙公司")
    _register(tmp_path, lib, "E2", "丙丁公司")
    obl = _ingest(tmp_path, lib, "提供甲乙公司与丙丁公司的审计报告")[0]
    assert obl["entity_scope"] == ""
    assert obl["entity_basis"] == rq.UNKNOWN


def test_empty_library_registry_does_not_degrade(tmp_path):
    """库里**没有**权威主体 ⇒ 回落词表为空 ⇒ 行为与修复前完全一致。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照"})
    obl = _ingest(tmp_path, lib, "提供甲公司 2024 年度审计报告")[0]
    assert obl["entity_scope"] == ""
    assert obl["entity_basis"] == rq.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# F2-e DIRECTORY 型别名不进回落词表
# ═══════════════════════════════════════════════════════════════════════════


def test_directory_alias_excluded_from_registry_tokens(tmp_path):
    """分类目录（DIRECTORY 型别名）是分类维度，不是主体标识 ⇒ 不进回落词表。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    _alias(tmp_path, lib, "E1", "01-资质证照", kind="DIRECTORY")
    conn = mf._connect(_db(tmp_path))
    rq._ensure_schema(conn)
    tokens = rq.entity_registry_tokens(lib, conn, _db(tmp_path))
    assert any(t == "甲公司" for t, _e in tokens)
    assert not any(t == "01-资质证照" for t, _e in tokens)


# ═══════════════════════════════════════════════════════════════════════════
# F2-f 端到端：回落命中 ⇒ 主体维度成为门槛（不再 UNCERTAIN）
# ═══════════════════════════════════════════════════════════════════════════


def test_fallback_makes_subject_dimension_a_real_gate(tmp_path):
    """命中后主体维度有实证（主体覆盖 = 1）⇒ 不再「主体维度不可判定」。"""
    lib = _setup(tmp_path, {"甲科技有限公司/营业执照.txt": "营业执照 名称：甲科技有限公司"})
    _register(tmp_path, lib, "E1", "甲科技有限公司")
    obl = _ingest(tmp_path, lib, "提供甲科技有限公司 2024 年度审计报告")[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert float(st["entity_cov"]) == 1.0
    assert "主体维度不可判定" not in str(st.get("missing_detail") or "")


def test_fallback_scope_label_is_desensitized(tmp_path):
    """回落命中的 scope 对外仍是**脱敏标签** ⇒ 原文不落判据文案。"""
    lib = _setup(tmp_path, {"甲科技有限公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲科技有限公司")
    obl = _ingest(tmp_path, lib, "提供甲科技有限公司 2024 年度审计报告")[0]
    label = rq.entity_scope_value(obl["entity_scope"])
    assert label == rq.ENTITY_HINT_LABEL
    assert "甲科技有限公司" not in label


# ═══════════════════════════════════════════════════════════════════════════
# F-1 守卫（独立 Reviewer 实测出的回归：假 MATCHED）
#   名单回落口径**不得跨片段继承** ⇒ 片段自己的 FACT 范围**不得**被覆盖
# gm-fix-f2-tests-parallel-scope: 三条守卫（前缀传播行为不变 + FACT 范围不被覆盖
#   + 端到端主体维度不被收窄）
# ═══════════════════════════════════════════════════════════════════════════


def test_parallel_fragment_keeps_its_own_fact_scope(tmp_path):
    """并列片段自己的 FACT 范围（「各全资子公司」）不被回落口径覆盖。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    obl = _ingest(tmp_path, lib, "甲公司提供营业执照、各全资子公司提供审计报告")
    assert len(obl) == 2, "同一条清单项应切出两个并列义务"
    # 片段 2：自己的 FACT 范围必须保住
    assert obl[1]["entity_scope"] == "subsidiaries"
    assert obl[1]["entity_basis"] == rq.FACT


def test_prefix_hint_still_propagates_to_parallel_fragments(tmp_path):
    """A2（G-A2-11 11d）的**前缀传播**行为**一字不变**（冒号前缀形态）。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照"})
    _register(tmp_path, lib, "E1", "甲公司")
    obl = _ingest(tmp_path, lib, "甲公司：提供营业执照、各全资子公司提供审计报告")
    assert len(obl) == 2
    assert obl[0]["entity_scope"] == "entity_hint:甲公司"
    # ★ 前缀形态下片段 2 继承前缀口径 —— 这是 A2 **既有**行为（基线即如此）
    assert obl[1]["entity_scope"] == "entity_hint:甲公司"
    assert obl[1]["entity_basis"] == rq.INFERRED


def test_parallel_fallback_does_not_shrink_subject_dimension(tmp_path):
    """端到端：并列片段的主体维度**不得**被收窄（不得出现假 MATCHED）。

    ★ 复现 Reviewer 的 F-1 实测：库内只有母公司的审计报告，
      「各全资子公司分别提供审计报告」必须仍然要求**全部子公司**。
    """
    lib = _setup(tmp_path, {
        "甲公司/审计报告2024.txt": "甲公司 2024 年度审计报告 标准无保留意见",
    })
    # ★ 登记 **3 个** subsidiary 主体：
    #   FACT 范围「subsidiaries」⇒ 展开成 3 个；名单回落（命中「甲公司」）⇒ 只有 1 个。
    #   ⇒ 断言 3 ⇒ **被收窄成 1 就会转红**（断言有判别力，不是 `>= 1` 的假绿）。
    _register(tmp_path, lib, "E1", "甲公司")
    _register(tmp_path, lib, "E2", "甲子公司一")
    _register(tmp_path, lib, "E3", "甲子公司二")
    obl = _ingest(tmp_path, lib, "甲公司提供2024年度审计报告、各全资子公司分别提供2024年度审计报告")
    assert len(obl) == 2
    subs = obl[1]
    assert subs["entity_scope"] == "subsidiaries"
    assert subs["entity_basis"] == rq.FACT
    # ★ 主体维度：FACT 范围「各全资子公司」必须展开成**全部 3 个**主体
    # gm-fix-f2-tests-harden-shrink-guard: 断言必须能抓住「收窄成 1 个」
    ents = rq.resolve_entities(lib, subs["entity_scope"], None, _db(tmp_path))
    assert len(ents) == 3, f"主体维度被收窄成 {len(ents)} 个（应 3 个）⇒ 回落口径跨片段继承了"
