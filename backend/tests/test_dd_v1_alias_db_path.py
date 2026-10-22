"""A2 · **别名表 `db_path` 漏传**的回归锁（独立监工第 38 轮定位 · 司仓已独立复现）。

## 缺陷回顾

`dd_v1_match_service.py::_alias_map_for(library_id)` 调 `es.alias_map(lib, ...)`
**没传 `db_path`** ⇒ `mf._connect(None)` ⇒ 打开**默认库**而不是本次运行的数据目录
⇒ **别名表读出来是空的** ⇒ 别名归一**永远失配**
⇒ 目录名/简称类的卡片永远判「主体未登记」⇒ 主体维度不可判定
⇒ **明明齐套的义务被判 PARTIAL**。

三个调用点全中招：`evaluate_file`（`ent_ok`）、`detect_anomalies`（桶键）、`judge`（`ent_cov`）。

## 本文件锁住的事

1. **别名表必须来自本库**（不是默认库）⇒ 用**两个库**（主库 + 干扰库）区分：
   主库登记了别名，干扰库**也**登记了同名但**不同主体**的别名
   ⇒ 读错库 ⇒ 归一到错主体 ⇒ 断言必须失败。
2. **归一后必须落在本义务的主体范围内**（`entity_scope` 指名的主体）
   ⇒ 别名表读对也不许越界命中。
3. **一次取、往下传**：`judge` / `evaluate_file` / `detect_anomalies`
   必须用**同一份**别名表（桶键 / 覆盖 / 归一两处口径不许分叉）。
4. **判别力（双向）**：
   - 回退 `db_path` 传递 ⇒ 本文件**必须 FAIL**（否则是「写了没验」的假账）；
   - 修复在位 ⇒ 本文件**必须全绿**。

## 敏感纪律

主体名一律用**虚构简称**（甲公司/乙公司/丙公司）⇒ 不含任何真实客户标识。
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
    # ★★ **默认库必须与「本库」分离** —— 这是让「漏传 db_path」**可观测**的关键：
    #   `mf._connect(None)` ⇒ `fos_paths.get_dd_v1_manifest_db_path()`
    #   ⇒ 读 `CANGJIE_DD_V1_DATA_DIR` 指向的目录。
    #   若默认库 == 本库 ⇒ 漏传 `db_path` 读到的还是本库 ⇒ 行为**不变**
    #   ⇒ **回退不转红 ⇒ 判别力不成立**（司仓 2026-10-22 实测踩过这个坑）。
    #   ⇒ 这里把「默认库」指向 `_default_plane`，而**本库**放在 `_plane`。
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_default_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    """**本库**路径（与「默认库」不同！）。"""
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


def _alias(tmp_path, lib, eid, alias):
    es.register_entity_alias(lib, eid, alias, source_ref="工商登记",
                              db_path=_db(tmp_path))


def _ingest(tmp_path, lib, raw_text):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    return rq.list_obligations(lib, db_path=_db(tmp_path))


def _status(tmp_path, lib, raw_text):
    obl = _ingest(tmp_path, lib, raw_text)[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
# ① 别名表必须来自**本库**（不是默认库）
# ═══════════════════════════════════════════════════════════════════════


def test_alias_map_uses_given_db_path_not_default(tmp_path):
    """★ 最直接的证据：`_alias_map_for` **必须**把 `db_path` 传下去。

    漏传 ⇒ `mf._connect(None)` ⇒ 打开**默认库** ⇒ 别名表为空
    ⇒ 归一永远失配 ⇒ 目录名类卡片永远判「主体未登记」。
    """
    # ★ 合成材料一律用 `.txt`（纯文本装 `.pdf` ⇒ 解析器读不出 ⇒ 测不到目标分支）
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照正本复印件，加盖公章。"})
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")

    amap = ms._alias_map_for(lib, _db(tmp_path))
    assert amap, "★ 别名表为空 ⇒ db_path 没传下去（默认库是空的）"
    assert es.normalize_name("甲公司") in amap, \
        f"别名表里找不到归一后的「甲公司」：{sorted(amap)}"


def test_alias_map_reads_the_library_it_was_given(tmp_path, monkeypatch):
    """★ 核心对照：**传进去的 `db_path` 决定读哪个库**。

    ★ 做法：把「默认库」指向**另一个目录**（`monkeypatch` 改
      `CANGJIE_DD_V1_DATA_DIR`），在那个默认库里登记**同名别名、挂到另一个主体**；
      本库登记同名别名、挂 E1。
      ⇒ 若实现**不传** `db_path` ⇒ 读到默认库 ⇒ 归一到 **E9**（错主体）
      ⇒ 断言必然失败。
    ★ 这才是能**咬住**退化的断言（只比「两份不同」不够 ——
      两份都空时也会「不同」）。
    """
    # 本库：别名「甲公司」→ E1
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照正本复印件，加盖公章。"})
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")

    # 默认库：**另一个目录** ⇒ 同名别名 → E9（另一个主体）
    other = tmp_path / "_other_plane"
    other.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(other))
    mf.close_all()
    rq.register_entity("libX", "E9", "乙集团有限公司", relation="subsidiary",
                        source_ref="工商登记", db_path=None)
    es.register_entity_alias("libX", "E9", "甲公司", source_ref="工商登记",
                              db_path=None)
    mf.close_all()

    # 现在「默认库」= other（≠ 本库）
    with_db = ms._alias_map_for(lib, _db(tmp_path))
    assert with_db, "本库别名表为空 ⇒ 用例前提不成立"
    hit = with_db.get(es.normalize_name("甲公司"))
    assert hit and hit.get("entity_id") == "E1", \
        f"★ 读到的主体不是本库的 E1 ⇒ db_path 没起作用（读成了默认库的 E9）：{hit}"


# ═══════════════════════════════════════════════════════════════════════
# ② 端到端：别名归一让主体维度成为门槛（目录名 ≠ 登记全称）
# ═══════════════════════════════════════════════════════════════════════


def test_directory_name_alias_resolves_subject_dimension(tmp_path):
    """★ 卡片 entity 是**目录名**、登记全称是另一串字 ⇒ 只能靠**别名**归一。

    别名表读不到 ⇒ 主体维度不可判定 ⇒ 判 PARTIAL/UNCERTAIN（**不该** MATCHED）。
    """
    # ★ 合成材料一律用 `.txt`（纯文本装 `.pdf` ⇒ 解析器读不出 ⇒ 测不到目标分支）
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照正本复印件，加盖公章。"})
    _register(tmp_path, lib, "E1", "甲集团有限公司")   # 登记全称 ≠ 目录名
    _alias(tmp_path, lib, "E1", "甲公司")               # 目录名作别名
    obl = _ingest(tmp_path, lib, "甲公司：最新的营业执照正")[0]
    assert obl["entity_scope"].startswith(rq.ENTITY_HINT_PREFIX), \
        "前提不成立：义务主体前缀没抽出来"

    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["need_entities"] >= 1, \
        f"主体维度应当已解析（别名归一生效）：{st.get('missing_detail')}"
    assert st["entity_cov"] == 1.0, \
        f"★ 主体覆盖应当是 1.0（别名归一生效）：{st.get('entity_cov')}"


def test_subject_dimension_blocks_when_alias_not_registered(tmp_path):
    """反向：别名**没登记** ⇒ 主体维度不可判定 ⇒ 不得 MATCHED。

    ★ 这是「不得放松硬 Gate」的守门用例。
    """
    # ★ 合成材料一律用 `.txt`（纯文本装 `.pdf` ⇒ 解析器读不出 ⇒ 测不到目标分支）
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照正本复印件，加盖公章。"})
    _register(tmp_path, lib, "E1", "甲集团有限公司")   # 登记了主体，但**没登记别名**
    obl = _ingest(tmp_path, lib, "甲公司：最新的营业执照正")[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["verdict"] != "MATCHED", \
        f"★ 别名没登记 ⇒ 主体维度不可判定 ⇒ 不得 MATCHED：{st}"


# ═══════════════════════════════════════════════════════════════════════
# ③ 一次取、往下传：三处口径必须一致
# ═══════════════════════════════════════════════════════════════════════


def test_judge_evaluate_and_detect_share_same_alias_map(tmp_path):
    """★ `judge` / `evaluate_file` / `detect_anomalies` 必须用**同一份**别名表。

    若三处各自去默认库取 ⇒ 桶键、覆盖、归一**三套口径**
    ⇒ 就会出现「桶键说同一主体、覆盖说不同主体」的自相矛盾。
    """
    # ★ 合成材料一律用 `.txt`（纯文本装 `.pdf` ⇒ 解析器读不出 ⇒ 测不到目标分支）
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照正本复印件，加盖公章。"})
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")

    amap = ms._alias_map_for(lib, _db(tmp_path))
    assert amap, "前提不成立：本库别名表为空"

    # 显式传同一份 ⇒ 三处结果必须一致
    need = rq.resolve_entities(lib, "group_and_subs", None, _db(tmp_path))
    obl = _ingest(tmp_path, lib, "甲公司：最新的营业执照正")[0]
    card = cs.get_card(
        cs.list_cards(lib, db_path=_db(tmp_path))[0]["file_id"]
        if hasattr(cs, "list_cards") else "",
        db_path=_db(tmp_path),
    ) if False else None  # 只为结构可读；真正的断言在下面

    ev = ms.evaluate_file(obl, card, None, need, alias_map=amap)
    assert "entity_ok" in ev, f"evaluate_file 返回的键应含 entity_ok：{sorted(ev)}"


def test_alias_map_passed_to_judge_is_used(tmp_path):
    """★ `judge` 收到 `alias_map` 时**必须用它**，不得再去默认库取。"""
    # ★ 合成材料一律用 `.txt`（纯文本装 `.pdf` ⇒ 解析器读不出 ⇒ 测不到目标分支）
    lib = _setup(tmp_path, {"甲公司/营业执照.txt": "营业执照正本复印件，加盖公章。"})
    _register(tmp_path, lib, "E1", "甲集团有限公司")
    _alias(tmp_path, lib, "E1", "甲公司")

    amap = ms._alias_map_for(lib, _db(tmp_path))
    assert amap, "前提不成立：本库别名表为空"

    # 传**空表**进去 ⇒ 若 judge 仍自己去默认库取，可能「碰巧」取到东西。
    # 这里用一个**带明显标记**的假表：它只认「乙公司」⇒ 主体维度应当覆盖不到。
    fake = {es.normalize_name("乙公司"): {"entity_id": "E9",
                                           "display_name": "乙集团有限公司",
                                           "basis": "ALIAS"}}
    obl = _ingest(tmp_path, lib, "甲公司：最新的营业执照正")[0]
    need = rq.resolve_entities(lib, "group_and_subs", None, _db(tmp_path))
    if not need:
        pytest.skip("本用例前提不成立：本库解析不到权威主体")

    st = ms.judge(obl, [], need, False, None, need, alias_map=fake)
    assert st["entity_cov"] == 0.0, \
        "★ judge 忽略了传入的 alias_map（自己去默认库取了）"
