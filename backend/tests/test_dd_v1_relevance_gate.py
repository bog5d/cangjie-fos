"""A2 · G-A2-12 / G-A2-13 / F3 / F4 —— 判别力用例。

## 这四条是什么

| 编号 | 内容 | 来源 |
|---|---|---|
| **G-A2-12** | **降级闸的适用范围（相关性闸）**：「主体未登记 / 类型认不出 ⇒ 降级 UNCERTAIN」原本挂在**整个候选池**上 ⇒ 池子里一份身份证复印件就能把「营业执照齐备没有」打成 UNCERTAIN ⇒ MATCHED 永远出不来。⇒ 降级只看**可能是本义务要求的那一份**的候选 | 司仓实测定位 |
| **G-A2-13** | **主体简称的角色后缀**：义务里的简称可能带角色后缀（如「<主体>（保证人）」）⇒ 归一后对不上登记简称 ⇒ 主体维度被判「未登记」。⇒ **只在查表路径**逐步剥掉角色括号后缀再试 | 司仓实测定位 |
| **F3** | `need_entities=0` 的义务**不得**产出「同一主体」类断言（该义务未指名主体，主体维度从未参与判定）⇒ 措辞收窄，**事实保留** | 独立监工第 33 轮 |
| **F4** | **MATCHED 必须主体维度确实核对过**（`need_entities ≥ 1`）⇒ 堵死「`ent_cov=1.0` 空洞满分」这条假 MATCHED 路径 | 独立监工第 33 轮（B8b） |

## ★ 本文件的核心：**双向判据**

- **不得误伤**：与本义务要求**确定不同**的候选（类型确定不同 / 全文无该类型关键词）
  ⇒ **不得**把结论打成 UNCERTAIN；
- **不得放松**：候选**可能**是要求的那一份（类型认不出但**全文含**该类型关键词 /
  义务**没**要求类型）⇒ **必须**仍然降级 UNCERTAIN。

只测「不误伤」不测「不放松」= 假绿。

## 敏感纪律

主体简称一律用**虚构名**（甲公司 / 乙公司）；「角色后缀」用「（保证人）」这类
**通用角色词**，不含任何真实客户标识。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_card_service as cs,
    dd_v1_requirement_service as rq,
)


#: 合成用例用的**最小可用披露策略**：
#:   `sendable_doc_types=["license"]` ⇒ 营业执照类可外发（其余类型仍收紧）；
#:   `default_level=RESTRICTED` ⇒ 最严兜底。
#: ★ 策略文件**必须真实存在**：读不到 ⇒ load_policy 返回「全部不可外发」，
#:   那就测不到「可交付 ⇒ MATCHED」这条路径了（不是测试写错，是夹具写错）。
_TEST_POLICY = {
    "policy_version": "test-a2-relevance",
    "default_level": "RESTRICTED",
    "sendable_doc_types": ["license"],
    "levels": {
        "PUBLIC": {"externally_sendable": True, "requires_review": True,
                    "description": "合成用例"},
        "INTERNAL": {"externally_sendable": False, "requires_review": True,
                     "description": ""},
        "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True,
                         "description": ""},
        "RESTRICTED": {"externally_sendable": False, "requires_review": True,
                       "description": ""},
    },
    "rules": [],
}


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    pol = tmp_path / "policy.json"
    pol.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(pol))
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


def _register(tmp_path, lib, eid, name, relation="subsidiary"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _unlock(tmp_path, lib, rel):
    """把指定材料标为可交付（模拟已接入披露政策；否则一律 RESTRICTED）。"""
    fid = mf.get_manifest_entry(lib, rel, db_path=_db(tmp_path))["file_id"]
    conn = mf._connect(_db(tmp_path))
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity='PUBLIC' WHERE file_id=?",
                 (fid,))
    conn.commit()


def _obl_status(tmp_path, raw_text, lib):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
# G-A2-12 · 相关性闸（双向）
# ═══════════════════════════════════════════════════════════════════════

_LICENSE = "营业执照正本复印件，加盖公章。"

#: 全文**不含**任何类型关键词的无关材料（身份证复印件不属于 10 类材料）
_IRRELEVANT = "法定代表人身份证明材料，仅供核对身份使用。"


def test_unrelated_unknown_type_does_not_block_matched(tmp_path):
    """★ 判别力（不误伤）：候选池里另有一份**类型认不出**、且**全文无该类型关键词**的
    无关材料 ⇒ **不得**因此把结论打成 UNCERTAIN ⇒ 应判 MATCHED。"""
    lib = _setup(tmp_path, {
        "甲公司/营业执照.txt": _LICENSE,
        "甲公司/身份证复印件.txt": _IRRELEVANT,
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供甲公司营业执照", lib)
    assert st["verdict"] == "MATCHED", \
        f"无关材料不得阻断结论：{st['verdict']} / {st.get('missing_detail')}"
    assert st["need_entities"] >= 1, "MATCHED 要求主体维度已核对"


def test_unknown_type_with_required_keyword_still_blocks(tmp_path):
    """★ 判别力（不放松）：候选里有一份**类型认不出**、但正文**深处含该类型关键词**的材料
    ⇒ 它**可能**就是要求的那一份 ⇒ **必须**降级 UNCERTAIN。

    （关键词落在正文头部 800 字窗口之外 ⇒ 类型解析认不出，但全文查得到。）
    """
    # ★ 填充长度必须落在**两个窗口之间**：
    #   类型解析看正文前 4000 字（用途扫描）⇒ 关键词要在 4000 之外（否则类型被解析出来，
    #   根本进不了「类型认不出」分支）；
    #   正文缓存留 6000 字 ⇒ 关键词要在 6000 之内（否则全文也看不见，
    #   「它可能就是那一类」这个判断就没有依据了）。
    filler = "本段为合成填充内容，用于验证正文头部窗口之外的情形，不含任何类型词。" * 140
    lib = _setup(tmp_path, {
        "甲公司/营业执照.txt": _LICENSE,
        "甲公司/扫描件.txt": filler + "末尾提到营业执照字样。",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供甲公司营业执照", lib)
    assert st["verdict"] == "UNCERTAIN", \
        f"可能相关且类型认不出 ⇒ 必须降级：{st['verdict']}"
    assert "材料类型认不出" in str(st.get("missing_detail") or "")


def test_obligation_without_required_type_keeps_blocking(tmp_path):
    """★ 判别力（最保守）：义务**没**要求类型 ⇒ 任何候选都可能是 ⇒ 未知类型**仍阻断**。"""
    lib = _setup(tmp_path, {
        "甲公司/材料一.txt": _IRRELEVANT,
        "甲公司/材料二.txt": _IRRELEVANT + "内容不同。",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    st = _obl_status(tmp_path, "请提供甲公司相关材料", lib)
    assert st["verdict"] == "UNCERTAIN", \
        f"义务没要求类型时不得放行：{st['verdict']}"
    assert "材料类型认不出" in str(st.get("missing_detail") or "")


def test_trace_fields_still_reported(tmp_path):
    """★ 留痕**不得**被收窄口径清掉：`unknown_types` / `unknown_entities` 仍须如实报告。"""
    lib = _setup(tmp_path, {
        "甲公司/营业执照.txt": _LICENSE,
        "甲公司/身份证复印件.txt": _IRRELEVANT,
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供甲公司营业执照", lib)
    assert st.get("unknown_types"), "类型认不出的材料必须留痕，不得静默丢弃"
    assert "留痕" in str(st.get("missing_detail") or ""), \
        f"不阻断也要写明留痕：{st.get('missing_detail')}"


def test_unrelated_type_does_not_block_entity_dimension(tmp_path):
    """★ 判别力：主体未登记、但候选类型与要求**确定不同** ⇒ 不阻断主体维度。"""
    lib = _setup(tmp_path, {
        "甲公司/营业执照.txt": _LICENSE,
        "乙目录/劳动合同.txt": "劳动合同与社保花名册材料。",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供甲公司营业执照", lib)
    # 劳动合同候选的主体未登记，但它类型确定不同 ⇒ 不得因此把结论打成 UNCERTAIN
    assert "主体未登记，无法判定是否同一主体" not in str(st.get("missing_detail") or ""), \
        f"类型确定不同的候选不得阻断主体维度：{st.get('missing_detail')}"


# ═══════════════════════════════════════════════════════════════════════
# G-A2-13 · 主体简称的角色后缀
# ═══════════════════════════════════════════════════════════════════════


def test_role_suffix_resolves_to_registered_entity(tmp_path):
    """★ 判别力：义务里的简称带**角色后缀** ⇒ 仍须解析到已登记主体。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": _LICENSE})
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "甲公司（保证人）：请提供营业执照", lib)
    assert st["need_entities"] == 1, \
        f"角色后缀不得导致主体判「未登记」：need_entities={st['need_entities']}"


def test_numeric_copy_suffix_not_stripped_by_role_path():
    """★ 保守性：**纯数字**的括号后缀是副本号，不属角色后缀 ⇒ 角色路径不得剥它。

    （副本号归 `normalize_name` 管；这里锁的是「角色后缀剥离」这条路径的边界。）
    """
    assert rq._strip_trailing_paren("甲公司(2)") == "甲公司(2)"
    assert rq._strip_trailing_paren("甲公司（保证人）") == "甲公司"
    assert rq._strip_trailing_paren("甲公司") == "甲公司"


def test_hint_lookup_keys_order_is_strict_first():
    """★ 查表键必须**由严到宽**：先原样归一（命中带角色后缀的登记别名）。"""
    keys = rq._hint_lookup_keys("甲公司（保证人）")
    assert len(keys) >= 2, f"应给出多个候选键：{keys}"
    assert "甲公司（保证人）" in keys[0], f"第一个键必须是原样归一：{keys}"


# ═══════════════════════════════════════════════════════════════════════
# F3 · 主体维度断言收窄（措辞收窄，事实保留）
# ═══════════════════════════════════════════════════════════════════════


def test_conflict_message_scoped_when_no_subject_named(tmp_path):
    """★ F3：义务**未指名主体** ⇒ 冲突文案**不得**断言「同一主体/期间存在 …」。"""
    lib = _setup(tmp_path, {
        "甲公司/审计报告2023.txt": "审计报告\n本报告为2023年度财务审计结论，由甲公司出具。\n",
        "甲公司/审计报告2023修订.txt":
            "审计报告\n本报告为2023年度财务审计结论，由甲公司出具。补充说明，内容不同。\n",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _register(tmp_path, lib, "E2", "乙公司")
    st = _obl_status(tmp_path, "请提供2023年度审计报告", lib)
    detail = str(st.get("missing_detail") or "")
    assert not detail.startswith("同一主体/期间存在"), \
        f"未指名主体时不得作主体维度断言：{detail}"
    assert "该义务未指名主体" in detail, f"须写明这是材料层发现：{detail}"
    # ★ F3 的**确切措辞**必须断言 ——
    #   只断言上面两句的话，回退措辞用例仍然绿（判别力实测已实测到这一点）
    #   ⇒ 那两句在改前改后都成立，**咬不住** F3 真正新增的部分。
    assert "材料层" in detail, f"须写明这是材料层发现：{detail}"
    assert "不构成该义务的主体维度断言" in detail, \
        f"须写明不构成该义务的主体维度断言：{detail}"


def test_conflict_finding_is_not_swallowed(tmp_path):
    """★ F3 的另一半：措辞收窄**不得**把冲突这一事实吞掉 ⇒ CONFLICT 判定保留。"""
    lib = _setup(tmp_path, {
        "甲公司/审计报告2023.txt": "审计报告\n本报告为2023年度财务审计结论，由甲公司出具。\n",
        "甲公司/审计报告2023修订.txt":
            "审计报告\n本报告为2023年度财务审计结论，由甲公司出具。补充说明，内容不同。\n",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    _register(tmp_path, lib, "E2", "乙公司")
    st = _obl_status(tmp_path, "请提供2023年度审计报告", lib)
    assert st["verdict"] == "CONFLICT", \
        f"冲突必须仍然报出来：{st['verdict']} / {st.get('missing_detail')}"


# ═══════════════════════════════════════════════════════════════════════
# F4 · MATCHED 必须主体维度已核对
# ═══════════════════════════════════════════════════════════════════════


def test_matched_requires_subject_dimension_checked(tmp_path):
    """★ F4：库里**没**登记任何主体 + 义务未指名主体 ⇒ 主体维度无从核对
    ⇒ **不得** MATCHED（`ent_cov=1.0` 只是「无约束」，不是「已核对」）。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": _LICENSE})
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供营业执照", lib)
    assert st["need_entities"] == 0
    assert st["verdict"] != "MATCHED", f"主体维度未核对不得 MATCHED：{st['verdict']}"
    detail = str(st.get("missing_detail") or "")
    assert "主体维度未经核对" in detail or "主体未登记" in detail, \
        f"须写明主体维度未经核对：{detail}"


def test_single_entity_library_gets_implicit_requirement(tmp_path):
    """★ F4 的配套：**库里恰好一个主体**时，主体维度并不空洞 ⇒ `need_entities = 1`。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": _LICENSE})
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供营业执照", lib)
    assert st["need_entities"] == 1, \
        f"单主体库的隐含要求必须计入：need_entities={st['need_entities']}"


def test_multi_entity_library_without_subject_stays_uncertain(tmp_path):
    """★ F4 的边界：库里 **≥2 个**主体 + 义务未指名 ⇒ 主体维度**不可判定**
    ⇒ 不得 MATCHED（`need_entities` 仍为 0）。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": _LICENSE})
    _register(tmp_path, lib, "E1", "甲公司")
    _register(tmp_path, lib, "E2", "乙公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "请提供营业执照", lib)
    assert st["need_entities"] == 0
    assert st["verdict"] != "MATCHED", f"多主体库不得 MATCHED：{st['verdict']}"
    assert "主体维度不可判定" in str(st.get("missing_detail") or "")


def test_f4_guard_present_and_positioned():
    """★ F4 白盒断言：守卫**存在**且**位置正确**。

    ★ **诚实说明**（司仓判别力实测结论，不是猜测）：
      F4 守卫在**当前调用图**下**不作为决定性闸** ——
      `n_ent == 0` 的情形已被三道机制**先行拦截**：
        (i) G-A2-11 闸（库里登记 ≥2 个主体 ⇒ 主体维度不可判定）；
        (ii) `not n_ent and entity_scope` 分支（义务指名了主体但没登记上）；
        (iii) unknown-entity 闸（库里 0 个主体 ⇒ 候选主体全部未登记）。
        （第 4 种「恰好登记 1 个主体」已被 F4 配套的隐含要求消化 ⇒ `n_ent = 1`。）
      ⇒ **回退 F4 本身不改变任何判定结果** ⇒ 这是**设计使然**（冗余防线），
        不是缺陷；但也**不能**把「回退 F4 ⇒ 用例转红」当成验收证据。
      ⇒ 本条改用**白盒断言**锁住两件真正可证伪的事：
        守卫**在**（符号存在）；守卫**排在初始判定之后**（位置正确 ——
        它兜的正是「已经判成 MATCHED」那一刻）。
      ★ 可观测契约（「`n_ent == 0` ⇒ 不得 MATCHED」）由
        `test_matched_requires_subject_dimension_checked` /
        `test_multi_entity_library_without_subject_stays_uncertain` 守住，
        那两条的判别力来自**实际拦下它的那道闸**（G-A2-11 闸 / unknown-entity 闸），
        **不是**来自 F4。
    """
    # ★ 读**实际被导入的模块**的文件（不是 `Path(__file__).resolve()` 拼出来的路径）：
    #   判别力探针在「符号链接农场」里跑时，`tests/` 是**指向原目录的符号链接**
    #   ⇒ `resolve()` 会解析回原路径 ⇒ 白盒断言读到的是**原文件**、看不见副本上的回退
    #   ⇒ **探针假绿**。`cangjie_fos....__file__` 就是**正在跑的这份代码**。
    from cangjie_fos.services import dd_v1_match_service as _ms_mod
    src = Path(_ms_mod.__file__).read_text(encoding="utf-8")
    guard = "if verdict == V_MATCHED and n_ent == 0:"
    assert guard in src, "F4 守卫不存在（回退生产端）"
    gi = src.index(guard)
    # 初始判定：最后的 `else: verdict = V_MATCHED` —— 守卫必须排在它**之后**
    init_idx = src.rindex("verdict = V_MATCHED", 0, gi)
    assert "else" in src[max(0, init_idx - 40):init_idx], \
        "F4 守卫必须排在「最后 else: verdict = V_MATCHED」之后"
    body = src[gi:gi + 400]
    assert "主体维度未经核对" in body, "F4 守卫必须写明「主体维度未经核对」"
    assert "V_UNCERTAIN" in body, "F4 守卫必须把 MATCHED 降级为 UNCERTAIN"


def test_named_subject_not_registered_stays_zero(tmp_path):
    """★ 红线：义务指名了主体但**没登记上** ⇒ `need_entities` **不得**回落成隐含单主体。"""
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": _LICENSE})
    _register(tmp_path, lib, "E1", "甲公司")
    _unlock(tmp_path, lib, "甲公司/营业执照.txt")
    st = _obl_status(tmp_path, "乙公司（保证人）：请提供营业执照", lib)
    assert st["need_entities"] == 0, \
        f"未登记主体不得回落成隐含要求：need_entities={st['need_entities']}"
    assert st["verdict"] != "MATCHED"
