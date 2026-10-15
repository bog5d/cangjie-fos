"""DD-V1 抽取适配层与认知卡测试（WP2）。

核心不变量：
1. **截断必须显式标记**（对治 D5：旧预热静默砍断，截断与扫描件不可区分）。
2. **失败必须有原因**，不可读就明说不可读，不返回半截正文冒充成功。
3. **认知卡每字段带出处**；FACT / INFERRED / UNKNOWN 三分，取不到证据一律 UNKNOWN。
   签章状态、敏感等级、所属集团在无权威依据时**必须**留 UNKNOWN，不得臆测。
4. Docling 为可选依赖，未安装时全链路必须照常工作。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_parser_service as ps


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _lib(tmp_path: Path):
    root = tmp_path / "materials"
    root.mkdir()
    mf.register_library("lib1", str(root), authorized_by="波总", db_path=_db(tmp_path))
    return "lib1", root


# ── 1. 抽取链：降级 / 截断 / 失败原因 ──────────────────────────────────────
def test_extract_plain_text_marks_method(tmp_path):
    f = tmp_path / "审计报告.txt"
    f.write_text("审计报告正文" * 50, encoding="utf-8")
    r = ps.extract_content(f)
    assert r.readable
    assert r.method
    assert not r.truncated


def test_truncation_is_explicit_not_silent(tmp_path):
    """超长正文必须 truncated=True 并记录原始长度（对治 D5）。"""
    f = tmp_path / "长报告.txt"
    f.write_text("甲" * 5000, encoding="utf-8")
    r = ps.extract_content(f, max_chars=1000)
    assert r.readable
    assert r.truncated is True
    assert len(r.text) == 1000
    assert r.original_chars == 5000, "必须记录被砍掉前的真实长度"


def test_unreadable_file_reports_reason_not_empty_success(tmp_path):
    f = tmp_path / "坏文件.xyz"
    f.write_bytes(b"\x00\x01\x02\xff" * 100)
    r = ps.extract_content(f)
    if not r.readable:
        assert r.method in (ps.M_UNREADABLE, ps.M_EMPTY)
        assert r.error, "不可读必须有原因，不能静默返回空串当成功"


def test_missing_file_marked_missing(tmp_path):
    r = ps.extract_content(tmp_path / "不存在.txt")
    assert r.method == ps.M_MISSING
    assert not r.readable


def test_docling_optional_absence_does_not_break_chain(tmp_path):
    """未装 docling 时必须自动跳过该层，链路照常工作（低成本可逆）。"""
    if not ps.docling_available():
        f = tmp_path / "正文.txt"
        f.write_text("正文内容" * 20, encoding="utf-8")
        r = ps.extract_content(f, allow_docling=True)
        assert r.readable, "docling 缺席不得影响抽取"
    else:
        f = tmp_path / "正文.txt"
        f.write_text("正文内容" * 20, encoding="utf-8")
        assert ps.extract_content(f).readable


def test_allow_docling_false_bypasses_optional_layer(tmp_path):
    f = tmp_path / "正文.txt"
    f.write_text("正文内容" * 20, encoding="utf-8")
    r = ps.extract_content(f, allow_docling=False)
    assert r.readable and r.method != ps.M_DOCLING


def test_extract_and_record_writes_status_fields(tmp_path):
    lib, root = _lib(tmp_path)
    f = root / "审计报告.txt"
    f.write_text("审计报告正文" * 30, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    entry = mf.get_manifest_entry(lib, "审计报告.txt", db_path=_db(tmp_path))

    out = ps.extract_and_record(lib, entry["file_id"], db_path=_db(tmp_path))
    assert out["parse_status"] == mf.PARSE_OK
    row = mf.get_manifest_entry(lib, "审计报告.txt", db_path=_db(tmp_path))
    assert row["parse_method"] == out["method"]
    assert row["parse_error"] == ""


def test_truncated_record_marked_partial_not_ok(tmp_path):
    lib, root = _lib(tmp_path)
    f = root / "超长.txt"
    f.write_text("乙" * 3000, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    entry = mf.get_manifest_entry(lib, "超长.txt", db_path=_db(tmp_path))

    out = ps.extract_and_record(lib, entry["file_id"], db_path=_db(tmp_path),
                                max_chars=500)
    assert out["truncated"] is True
    assert out["parse_status"] == mf.PARSE_PARTIAL, "截断必须标 partial，不得标 ok"


# ── 2. 认知卡：出处三分，不得臆造 ─────────────────────────────────────────
def _build(tmp_path, name, content=None):
    lib, root = _lib(tmp_path)
    f = root / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content or "内容", encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    row = mf.get_manifest_entry(lib, name, db_path=_db(tmp_path))
    return lib, row


def test_card_fields_all_have_provenance(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/审计报告2023.txt")
    card = cs.build_card(row, db_path=_db(tmp_path))
    assert set(card.keys()) == set(cs.CARD_FIELDS)
    for k, v in card.items():
        assert v["provenance"] in (cs.FACT, cs.INFERRED, cs.UNKNOWN), k
        if v["value"] == "" or v["value"] == []:
            assert v["provenance"] == cs.UNKNOWN, f"{k} 空值却标了 {v['provenance']}"


def test_entity_from_path_is_inferred_not_fact(tmp_path):
    """主体来自目录名，必须 INFERRED，不能冒充 FACT。"""
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt")
    card = cs.build_card(row, db_path=_db(tmp_path))
    assert card["entity"]["value"] == "子公司甲"
    assert card["entity"]["provenance"] == cs.INFERRED
    assert card["entity"]["evidence"], "INFERRED 必须写明推导规则"


def test_seal_and_sensitivity_never_guessed(tmp_path):
    """签章状态/敏感等级无依据时必须 UNKNOWN，且注明原因。"""
    lib, row = _build(tmp_path, "子公司甲/盖章版审计报告.pdf")
    card = cs.build_card(row, text="审计报告正文", db_path=_db(tmp_path))
    for k in ("seal_status", "sensitivity", "group"):
        assert card[k]["value"] == ""
        assert card[k]["provenance"] == cs.UNKNOWN, f"{k} 不得臆测"
        assert card[k]["evidence"], f"{k} 应说明为何 UNKNOWN"


def test_labeled_values_are_fact_with_evidence(tmp_path):
    text = "签署日期：2023-06-15\n生效日期：2023-07-01\n本报告为2023年度财务审计。"
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt", content=text)
    card = cs.build_card(row, text=text, db_path=_db(tmp_path))
    assert card["sign_date"]["provenance"] == cs.FACT
    assert "2023" in str(card["sign_date"]["value"])
    assert card["fiscal_period"]["provenance"] == cs.FACT
    assert card["fiscal_period"]["value"] == "2023"


def test_empty_value_forces_unknown_not_fake_fact(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/无标签.txt", content="随便一段没有标签的正文")
    card = cs.build_card(row, text="随便一段没有标签的正文", db_path=_db(tmp_path))
    assert card["sign_date"]["provenance"] == cs.UNKNOWN
    assert card["sign_date"]["value"] == ""


def test_version_hint_is_inferred(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/审计报告2023最终版.txt")
    card = cs.build_card(row, db_path=_db(tmp_path))
    assert card["version"]["provenance"] == cs.INFERRED


def test_card_is_persisted_and_readable(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt")
    cs.build_card(row, db_path=_db(tmp_path))
    got = cs.get_card(row["file_id"], db_path=_db(tmp_path))
    assert got is not None
    assert got["entity"] == "子公司甲"
    assert got["fields"]["entity"]["provenance"] == cs.INFERRED


def test_card_build_is_idempotent(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt")
    cs.build_card(row, db_path=_db(tmp_path))
    cs.build_card(row, db_path=_db(tmp_path))
    got = cs.get_card(row["file_id"], db_path=_db(tmp_path))
    assert got is not None, "重复建卡不得产生重复行"


def test_build_cards_for_library_and_coverage(tmp_path):
    lib, root = _lib(tmp_path)
    for sub in ("子公司甲", "子公司乙"):
        (root / sub).mkdir()
        (root / sub / "审计报告.txt").write_text("正文", encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    res = cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    assert res["built"] == 2
    cov = cs.card_coverage(lib, db_path=_db(tmp_path))
    assert cov["cards"] == 2
    assert cov["by_provenance"][cs.FACT] > 0


# ── 3. FTS5 索引 ───────────────────────────────────────────────────────────
def test_fts_index_created_and_searchable(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt",
                      content="本报告涉及知识产权与专利布局的核心结论。")
    cs.build_card(row, text="本报告涉及知识产权与专利布局的核心结论。",
                  db_path=_db(tmp_path))
    hits = cs.search_materials("lib1", "专利", db_path=_db(tmp_path))
    assert len(hits) == 1, "FTS5 应能检索到"
    assert hits[0]["file_id"] == row["file_id"]


def test_chinese_two_char_query_works(tmp_path):
    """中文 2 字查询必须可用——unicode61 原生会把整段汉字当一个 token，搜不到。"""
    lib, root = _lib(tmp_path)
    (root / "专利说明.txt").write_text("本报告涉及专利与商标", encoding="utf-8")
    (root / "审计说明.txt").write_text("本报告涉及审计与税务", encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    for name in ("专利说明.txt", "审计说明.txt"):
        r = mf.get_manifest_entry(lib, name, db_path=_db(tmp_path))
        cs.build_card(r, text=(root / name).read_text(encoding="utf-8"),
                      db_path=_db(tmp_path))

    assert len(cs.search_materials("lib1", "专利", db_path=_db(tmp_path))) == 1
    assert len(cs.search_materials("lib1", "审计", db_path=_db(tmp_path))) == 1
    assert len(cs.search_materials("lib1", "商标", db_path=_db(tmp_path))) == 1
    assert len(cs.search_materials("lib1", "完全不存在", db_path=_db(tmp_path))) == 0


def test_chinese_long_query_phrase(tmp_path):
    """多字词必须命中——需 bigram 索引 + 查询侧短语，二者缺一不可。"""
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt",
                      content="本报告涉及知识产权与专利布局的核心结论。")
    cs.build_card(row, text="本报告涉及知识产权与专利布局的核心结论。",
                  db_path=_db(tmp_path))
    assert len(cs.search_materials("lib1", "知识产权", db_path=_db(tmp_path))) == 1
    assert len(cs.search_materials("lib1", "知识产权与专利", db_path=_db(tmp_path))) == 1


def test_bigram_helpers():
    assert cs.bigram_expand("专利") == "专利"
    assert cs.bigram_expand("知识产权") == "知识 识产 产权"
    assert cs.bigram_expand("") == ""
    assert cs.to_fts_query("知识产权").startswith('"')
    assert cs.to_fts_query("") == '""'


def test_parse_then_cards_indexes_body_text(tmp_path):
    """端到端：抽取 → 正文缓存 → 建卡 → 全文可搜到**正文里**的词。

    这是本轮实跑抓到的缺口：正文未缓存时 FTS 只能搜标题，
    材料内容等于没进索引。
    """
    lib, root = _lib(tmp_path)
    (root / "子公司甲").mkdir()
    (root / "子公司甲" / "说明.txt").write_text(
        "本文件正文讨论商标注册证与发明专利的归属。", encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    row = mf.get_manifest_entry(lib, "子公司甲/说明.txt", db_path=_db(tmp_path))

    out = ps.extract_and_record(lib, row["file_id"], db_path=_db(tmp_path))
    assert out["parse_status"] == mf.PARSE_OK

    assert cs.get_cached_text(row["file_id"], db_path=_db(tmp_path)), "正文应已缓存"
    res = cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    assert res["with_cached_text"] == 1

    hits = cs.search_materials("lib1", "商标", db_path=_db(tmp_path))
    assert len(hits) == 1, "正文中的词必须可检索"
    assert hits[0]["rel_path"] == "子公司甲/说明.txt", "rel_path 必须是真值而非 bigram 展开串"


def test_search_returns_real_rel_path_not_bigram(tmp_path):
    lib, row = _build(tmp_path, "子公司甲/审计报告.txt", content="正文内容")
    cs.build_card(row, text="正文内容", db_path=_db(tmp_path))
    hits = cs.search_materials("lib1", "审计", db_path=_db(tmp_path))
    assert hits and hits[0]["rel_path"] == "子公司甲/审计报告.txt"


def test_card_without_text_keeps_fields_unknown(tmp_path):
    """没有正文缓存时，依赖正文的字段必须留 UNKNOWN，不得臆造。"""
    lib, root = _lib(tmp_path)
    (root / "子公司甲").mkdir()
    (root / "子公司甲" / "无缓存.txt").write_text("签署日期：2020-01-01", encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    row = mf.get_manifest_entry(lib, "子公司甲/无缓存.txt", db_path=_db(tmp_path))
    card = cs.build_card(row, text="", db_path=_db(tmp_path))
    assert card["sign_date"]["provenance"] == cs.UNKNOWN
    assert card["fiscal_period"]["provenance"] == cs.UNKNOWN


def test_fts_is_fts5_real_engine(tmp_path):
    """确认 FTS5 真装了——不是回落到普通表（旧仓库曾有「BM25 只是注释」的假象）。"""
    lib, row = _build(tmp_path, "子公司甲/a.txt")
    cs.build_card(row, text="x", db_path=_db(tmp_path))
    conn = mf._connect(_db(tmp_path))
    r = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='dd_v1_material_fts'"
    ).fetchone()
    assert r and "VIRTUAL TABLE" in r["sql"] and "fts5" in r["sql"]
    conn.close()
