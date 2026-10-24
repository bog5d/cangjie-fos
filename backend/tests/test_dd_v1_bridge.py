"""WP-A1（G1/G2/G7）：**薄桥**接线测试——规则链接进语义层，且不越权。

这个文件锁住四件事：

1. **接线真的通了**：桥接产出的语义义务**取得到非空证据**
   （``file_id + sha256 + locator`` 齐全）。证据池恒空 = 线没接上。
2. **doc_type 两侧同一 key 空间**：桥接产出的 ``meta[].doc_type`` 必须是
   ``dd_v1_requirement_service._DOC_TYPE_RULES`` 的 10 个英文 key。
   写成中文类型名或扩展名 ⇒ 语义层精确过滤落空 ⇒ 证据池恒空。
3. **不跨法人混桶**：一条义务按主体分簇后，每簇的证据里**只含该主体**的材料。
4. **只作建议**：桥接**不得**改写 ``judge()`` 的硬判定——
   桥接前后 ``dd_v1_obligation_status`` 的 ``verdict`` 必须逐条一致。

另锁两条安全边界：
- 无适配器 ⇒ ``RULE_ONLY`` + ``external_model_calls=0``（零外部调用、零费用）；
- 义务**不被二次切碎**（G7）：桥接显式传 obligations ⇒ 语义层不再用 ``SPLIT_RE`` 重拆。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_bridge_service as br,
    dd_v1_card_service as cs,
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
    dd_v1_semantic_retrieval_service as sem,
)

_REPO = Path(__file__).resolve().parents[2]
FIXTURE_SNAPSHOT = _REPO / "backend" / "tests" / "fixtures" / "dd_v1_fos71_wp04" / "snapshot"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _build_library(tmp_path, root: Path, lib: str, checklist: list[str]):
    """清单 → 认知卡 → 义务，全部落在 tmp 数据面里（材料**不复制**，只读原路径）。"""
    mf.register_library(lib, str(root), authorized_by="A1", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    rq.ingest_checklist(lib, [{"item_no": str(i + 1), "raw_text": t}
                              for i, t in enumerate(checklist)], db_path=_db(tmp_path))
    return lib


def _audit(year, entity="子公司甲"):
    return f"审计报告\n本报告为{year}年度财务审计结论，由{entity}出具。\n"


# ── 1. 接线真的通了：证据池非空 ─────────────────────────────────────────────

def test_bridge_produces_non_empty_evidence_on_repo_fixture(tmp_path):
    """仓库内合成 fixture（**不碰真实材料**，不需要 --allow-real-material）。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "桥接测试库",
                         ["请提供2024年度审计报告", "请提供营业执照"])

    out = br.bridge_library(lib, material_root=FIXTURE_SNAPSHOT, db_path=_db(tmp_path))

    assert out["counts"]["materials"] == 8, out["counts"]
    assert out["counts"]["obligations_out"] >= 2, out["counts"]
    # **证据池非空** = 线接上了
    assert out["counts"]["obligations_with_evidence"] >= 1, \
        f"桥接没取到任何证据：{out['warnings']}"
    assert out["counts"]["evidence_total"] > 0

    # 每条证据都必须可追溯：file_id + sha256 + locator
    seen = 0
    for ob in out["obligations"]:
        for e in ob["evidence"]:
            seen += 1
            assert e["file_id"], e
            assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), e
            assert e["locator"], e
            assert e["relative_path"], e
            # 主体是否权威核验过，必须逐条标出来
            assert e["subject_verified"] == (ob["entity_basis"] == "AUTHORITY")
            assert ob["subject_verified"] == (ob["entity_basis"] == "AUTHORITY")
    assert seen > 0


def test_bridge_flags_unverified_subject_when_no_clue(tmp_path):
    """没有任何主体线索时，证据**必须**标 subject_verified=false（不得默认「已核验」）。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "主体未核验库",
                         ["请提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=FIXTURE_SNAPSHOT, db_path=_db(tmp_path))
    hit = [ob for ob in out["obligations"] if ob["evidence_count"]]
    assert hit, "应当取到证据"
    for ob in hit:
        assert ob["entity_basis"] == "UNKNOWN"
        assert ob["subject_verified"] is False
        assert all(e["subject_verified"] is False for e in ob["evidence"])
    assert any("横跨多个法人" in w or "subject_verified" in w for w in out["warnings"]), \
        out["warnings"]


def test_bridge_meta_doc_type_is_in_the_same_key_space(tmp_path):
    """桥接产出的 meta[].doc_type 必须落在那 10 个英文 key 里（不是中文、不是扩展名）。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "key空间库",
                         ["请提供2024年度审计报告"])
    meta, stats = br.build_meta(lib, db_path=_db(tmp_path))
    assert meta
    for m in meta:
        assert m["doc_type"] == "" or m["doc_type"] in br.DOC_TYPE_KEYS, m
        assert m["doc_type"] != "txt", "卡片 doc_type 是文件扩展名，不得当材料类型用"
    # 至少解析出一份审计报告（证明 purpose 关键词真的被读到了）
    assert any(m["doc_type"] == "audit_report" for m in meta), \
        f"没有材料解析出 audit_report：{[(m['relative_path'], m['doc_type']) for m in meta]}"
    assert stats["doc_type_unknown"] >= 1, "备忘录类材料应老实标 UNKNOWN"


# ── 2. 不跨法人混桶 ─────────────────────────────────────────────────────────

def test_bridge_does_not_mix_entities(tmp_path):
    """一条义务按主体分簇后，**每簇证据只含该主体**的材料。

    材料放在**测试自建的合成目录**里（甲公司 / 乙公司 两个子目录，
    认知卡 entity 由目录名推导 ⇒ 两个不同主体）。
    显式开 ``allow_real_material`` 只是为了绕过「非 fixture 目录需显式授权」的保护，
    **本测试用的是测试自己造的合成文件，不涉及任何真实客户材料**。
    """
    root = tmp_path / "materials"
    (root / "甲公司").mkdir(parents=True)
    (root / "乙公司").mkdir(parents=True)
    (root / "甲公司" / "审计报告2024.txt").write_text(_audit(2024, "甲公司"), encoding="utf-8")
    (root / "乙公司" / "审计报告2024.txt").write_text(_audit(2024, "乙公司"), encoding="utf-8")

    lib = _build_library(tmp_path, root, "多主体库", ["请提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=root, db_path=_db(tmp_path),
                            allow_real_material=True)

    assert out["counts"]["obligations_out"] == 2, \
        f"两个主体应分成两簇：{out['counts']}"
    assert out["counts"]["entity_basis"]["CARD_INFERRED"] == 2

    # 每簇只含自己主体的材料
    file_owner = {}
    for ob in out["obligations"]:
        ents = {e["entity"] for e in ob["evidence"]}
        assert ents <= {ob["entity"]}, f"证据里混进了别的主体：{ob['entity']} / {ents}"
        for e in ob["evidence"]:
            assert e["entity"] == ob["entity"]
            # 同一份材料不得同时出现在两簇里
            assert e["file_id"] not in file_owner, "同一材料被放进两个主体簇"
            file_owner[e["file_id"]] = ob["entity"]
    assert len(file_owner) == 2, file_owner


def test_bridge_reports_entity_basis_honestly(tmp_path):
    """主体档位必须标出来：**卡片主体是目录名线索，不是法律事实**。"""
    root = tmp_path / "materials"
    (root / "合成法人甲").mkdir(parents=True)
    (root / "合成法人甲" / "审计报告2024.txt").write_text(_audit(2024, "合成法人甲"),
                                                        encoding="utf-8")
    lib = _build_library(tmp_path, root, "主体档位库", ["请提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=root, db_path=_db(tmp_path),
                            allow_real_material=True)
    assert out["counts"]["entity_basis"]["CARD_INFERRED"] == 1
    assert any("路径" in w or "目录名" in w or "path_segment" in w or "线索" in w
               for w in out["warnings"]), out["warnings"]


# ── 3. 义务不被二次切碎（G7）───────────────────────────────────────────────

def test_bridge_does_not_resplit_obligations(tmp_path):
    """桥接显式传 obligations ⇒ 语义层**不再**用 SPLIT_RE 二次切碎。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "不切碎库",
                         ["请提供2024年度审计报告及营业执照"])
    src = rq.list_obligations(lib, db_path=_db(tmp_path))
    assert src, "清单应当拆出义务"

    out = br.bridge_library(lib, material_root=FIXTURE_SNAPSHOT, db_path=_db(tmp_path))

    # 语义义务的正文 = 原文，**没有**被再切一刀
    src_texts = {o["obligation"] for o in src}
    for ob in out["obligations"]:
        assert ob["text"] in src_texts, f"义务正文被改写了：{ob['text']!r}"
    # 未拆条目为空（没有走 split_items）
    assert out["unsplit_items"] == [], out["unsplit_items"]
    # 义务条数不被放大（分簇数 ≤ 主体数 × 原义务数，且每个 source_obligation_id 可追溯）
    for ob in out["obligations"]:
        assert ob["obligation_id"].startswith(ob["source_obligation_id"])


# ── 4. 只作建议：不得改写硬判定 ───────────────────────────────────────────

def test_bridge_does_not_change_hard_verdicts(tmp_path):
    """桥接前后 ``dd_v1_obligation_status`` 的 verdict 必须**逐条一致**。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "不改判定库",
                         ["请提供2024年度审计报告", "请提供营业执照"])
    ms.match_library(lib, db_path=_db(tmp_path))
    before = {o["obligation_id"]: (o["verdict"], o["missing_detail"])
              for o in _statuses(lib, tmp_path)}

    br.bridge_library(lib, material_root=FIXTURE_SNAPSHOT, db_path=_db(tmp_path))

    after = {o["obligation_id"]: (o["verdict"], o["missing_detail"])
             for o in _statuses(lib, tmp_path)}
    assert before == after, "桥接改写了硬判定"


def _statuses(lib, tmp_path):
    conn = mf._connect(_db(tmp_path))
    return [dict(r) for r in conn.execute(
        "SELECT obligation_id, verdict, missing_detail FROM dd_v1_obligation_status")]


# ── 5. 降级与安全边界 ─────────────────────────────────────────────────────

def test_bridge_degrades_to_rule_only_without_adapter(tmp_path):
    """没有适配器 ⇒ RULE_ONLY + 零外部调用；不得抛错、不得影响入口 A。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "降级库",
                         ["请提供2024年度审计报告"])
    out = br.bridge_library(lib, material_root=FIXTURE_SNAPSHOT, db_path=_db(tmp_path))
    assert out["mode"] == "RULE_ONLY", out["mode"]
    assert out["external_model_calls"] == 0
    assert out["degrade_reason"], "降级必须说明原因"
    assert out["advisory_only"] is True
    assert out["hard_verdict_touched"] is False
    for ob in out["obligations"]:
        assert ob["review_required"] is True
        assert ob["advisory_only"] is True
        assert ob["hard_verdict_touched"] is False


def test_bridge_on_empty_library_does_not_raise(tmp_path):
    """空材料库 / 空义务 ⇒ 如实报空，不抛错。"""
    lib = _build_library(tmp_path, FIXTURE_SNAPSHOT, "空库", [])
    out = br.bridge_library(lib, material_root=FIXTURE_SNAPSHOT, db_path=_db(tmp_path))
    assert out["counts"]["obligations_out"] == 0
    assert out["external_model_calls"] == 0
