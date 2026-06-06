"""DD 物料架构升级测试：全文精判（阶段1）+ 机器验证（阶段2）+ 跨机构学习（阶段3）。

所有 LLM 调用 mock。遵循 test_dd_bulk_50 的直接服务调用 + 隔离 DB 模式。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from unittest.mock import patch

from cangjie_fos.services.db_base import _connect


# ─── 测试夹具 helper ────────────────────────────────────────────────────────

def _insert_index_row(folder_root: str, file_path: str, filename: str,
                      summary: str = "", content_text: str | None = None) -> None:
    """向 dd_asset_index 插入一行（供 _get_index_for_folder / 精判 JOIN 读取）。"""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary,
                readable, indexed_at, content_text)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (str(uuid.uuid4()), folder_root, file_path, filename,
             Path(filename).suffix.lower(), summary, time.time(), content_text),
        )


def _set_match(session_id: str, item_id: str, file_path: str, filename: str,
               confidence: float, confirmed: int = 0) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE dd_match_items
               SET matched_file_path = ?, matched_filename = ?, confidence = ?,
                   user_confirmed = ?
               WHERE id = ?""",
            (file_path, filename, confidence, confirmed, item_id),
        )


def _get_item(session_id: str, item_id: str) -> dict:
    with _connect() as conn:
        return dict(conn.execute(
            "SELECT * FROM dd_match_items WHERE id = ?", (item_id,)
        ).fetchone())


# ════════════════════════════════════════════════════════════════════════════
# 阶段1：全文精判 —— 全文抽取 + content_text 落库 + 正文核对
# ════════════════════════════════════════════════════════════════════════════

class TestPhase1FullText:

    def test_extract_full_text_reads_more_than_summary(self, tmp_path):
        """extract_full_text 应读到比 extract_text(800字) 更多的正文。"""
        from cangjie_fos.services.dd_file_parser import extract_text, extract_full_text
        body = "审计报告正文内容。" * 300  # 远超 800 字
        f = tmp_path / "审计报告.txt"
        f.write_text(body, encoding="utf-8")

        short, ok1 = extract_text(f)
        full, ok2 = extract_full_text(f)
        assert ok1 and ok2
        assert len(short) <= 800
        assert len(full) > 800
        assert len(full) > len(short)

    def test_unsupported_extension_not_readable(self, tmp_path):
        from cangjie_fos.services.dd_file_parser import extract_full_text
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG fake")
        text, readable = extract_full_text(f)
        assert text == ""
        assert readable is False

    def test_index_stores_content_text(self, tmp_path):
        """扫描后 dd_asset_index.content_text 应落库全文。"""
        (tmp_path / "执照.txt").write_text("营业执照全文内容" * 50, encoding="utf-8")
        with patch("cangjie_fos.services.dd_index_service._llm_summarize",
                   return_value="营业执照"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "t")

        with _connect() as conn:
            row = conn.execute(
                "SELECT content_text FROM dd_asset_index WHERE filename = '执照.txt'"
            ).fetchone()
        assert row is not None
        assert row["content_text"] is not None
        assert "营业执照全文内容" in row["content_text"]

    def test_refine_overrides_confidence_when_not_satisfied(self, tmp_path):
        """精判判定不满足 → confidence 压低到红判，并写入证据。"""
        from cangjie_fos.services.dd_match_service import (
            create_match_session, _refine_session_matches,
        )
        folder = str(tmp_path)
        items = [{"item_no": "1", "category": "财务", "requirement": "2023年审计报告"}]
        sid = create_match_session("t", "c.xlsx", folder, items)
        item_id = _get_first_item_id(sid)

        fpath = str(tmp_path / "wrong.txt")
        _insert_index_row(folder, fpath, "wrong.txt", content_text="这是一份装修合同，与审计无关")
        _set_match(sid, item_id, fpath, "wrong.txt", 0.85)  # 摘要匹配给了高分

        with patch("cangjie_fos.services.dd_match_service._llm_refine_candidate",
                   return_value={"satisfies": False, "confidence": 0.1,
                                 "evidence": "正文是装修合同，非审计报告"}):
            _refine_session_matches(sid)

        item = _get_item(sid, item_id)
        assert item["confidence"] <= 0.3
        assert item["verdict"] == "red"
        assert "装修合同" in (item["evidence"] or "")

    def test_refine_confirms_when_satisfied(self, tmp_path):
        """精判判定满足 → verdict green，证据落库。"""
        from cangjie_fos.services.dd_match_service import (
            create_match_session, _refine_session_matches,
        )
        folder = str(tmp_path)
        items = [{"item_no": "1", "category": "财务", "requirement": "审计报告"}]
        sid = create_match_session("t", "c.xlsx", folder, items)
        item_id = _get_first_item_id(sid)

        fpath = str(tmp_path / "audit.txt")
        _insert_index_row(folder, fpath, "audit.txt",
                          content_text="天健会计师事务所 审计报告 2023年度 标准无保留意见")
        _set_match(sid, item_id, fpath, "audit.txt", 0.6)

        with patch("cangjie_fos.services.dd_match_service._llm_refine_candidate",
                   return_value={"satisfies": True, "confidence": 0.95,
                                 "evidence": "正文含『审计报告 标准无保留意见』"}):
            _refine_session_matches(sid)

        item = _get_item(sid, item_id)
        assert item["confidence"] >= 0.7
        assert item["verdict"] == "green"
        assert "审计报告" in (item["evidence"] or "")


# ════════════════════════════════════════════════════════════════════════════
# 阶段2：机器验证 —— 红/黄/绿判定
# ════════════════════════════════════════════════════════════════════════════

class TestPhase2Verdict:

    def test_confidence_to_verdict_thresholds(self):
        from cangjie_fos.services.dd_match_service import _confidence_to_verdict
        assert _confidence_to_verdict(0.9) == "green"
        assert _confidence_to_verdict(0.70) == "green"
        assert _confidence_to_verdict(0.55) == "yellow"
        assert _confidence_to_verdict(0.40) == "yellow"
        assert _confidence_to_verdict(0.2) == "red"
        assert _confidence_to_verdict(None) == "red"

    def test_verdict_assigned_without_content_no_llm(self, tmp_path):
        """匹配项无正文（图片/加密件）→ 不调 LLM，按现有置信度给信号。"""
        from cangjie_fos.services.dd_match_service import (
            create_match_session, _refine_session_matches,
        )
        folder = str(tmp_path)
        items = [{"item_no": "1", "category": "基本", "requirement": "营业执照"}]
        sid = create_match_session("t", "c.xlsx", folder, items)
        item_id = _get_first_item_id(sid)

        fpath = str(tmp_path / "scan.pdf")
        _insert_index_row(folder, fpath, "scan.pdf", content_text=None)  # 正文不可读
        _set_match(sid, item_id, fpath, "scan.pdf", 0.55)

        # 若误调 LLM 会抛错——以此断言「无正文不精判」
        with patch("cangjie_fos.services.dd_match_service._llm_refine_candidate",
                   side_effect=AssertionError("不应对无正文文件调用精判")):
            _refine_session_matches(sid)

        item = _get_item(sid, item_id)
        assert item["verdict"] == "yellow"
        assert "未精判" in (item["evidence"] or "")

    def test_unmatched_item_verdict_red(self, tmp_path):
        from cangjie_fos.services.dd_match_service import (
            create_match_session, _refine_session_matches,
        )
        folder = str(tmp_path)
        items = [{"item_no": "1", "category": "基本", "requirement": "找不到的需求"}]
        sid = create_match_session("t", "c.xlsx", folder, items)
        item_id = _get_first_item_id(sid)
        with _connect() as conn:
            conn.execute("UPDATE dd_match_items SET confidence = 0.0 WHERE id = ?", (item_id,))

        _refine_session_matches(sid)
        item = _get_item(sid, item_id)
        assert item["verdict"] == "red"


# ════════════════════════════════════════════════════════════════════════════
# 阶段3：跨机构决策记忆（材料库共享 → 需求→文件 映射全局复用）
# ════════════════════════════════════════════════════════════════════════════

class TestPhase3CrossInstitutionMemory:

    def test_normalize_requirement_stable(self):
        from cangjie_fos.services.dd_match_service import normalize_requirement
        a = normalize_requirement("（请提供）2023年 审计报告。")
        b = normalize_requirement("审计报告")
        assert a == b
        assert normalize_requirement("") == ""

    def test_record_and_lookup_memory(self, tmp_path):
        from cangjie_fos.services.dd_match_service import (
            create_match_session, record_session_decisions, lookup_decision_memory,
        )
        folder = str(tmp_path)
        items = [{"item_no": "1", "category": "财务", "requirement": "审计报告"}]
        sid = create_match_session("t", "c.xlsx", folder, items, institution_name="机构A")
        item_id = _get_first_item_id(sid)
        fpath = str(tmp_path / "审计报告.pdf")
        _set_match(sid, item_id, fpath, "审计报告.pdf", 0.9, confirmed=1)

        n = record_session_decisions(sid)
        assert n == 1
        mem = lookup_decision_memory("审计报告")
        assert mem is not None
        assert mem["file_path"] == fpath
        assert mem["confirm_count"] == 1

    def test_memory_applies_across_institutions(self, tmp_path):
        """机构A确认的「需求→文件」，机构B同类需求应被自动锁定（核心场景）。"""
        from cangjie_fos.services.dd_match_service import (
            create_match_session, record_session_decisions, run_matching,
            MEMORY_REASON_PREFIX,
        )
        folder = str(tmp_path)
        fpath = str(tmp_path / "审计报告2023.pdf")
        _insert_index_row(folder, fpath, "审计报告2023.pdf",
                          content_text="审计报告 标准无保留意见")

        # 机构A：确认 审计报告 → 该文件
        items_a = [{"item_no": "1", "category": "财务", "requirement": "近三年审计报告"}]
        sid_a = create_match_session("t", "a.xlsx", folder, items_a, institution_name="机构A")
        item_a = _get_first_item_id(sid_a)
        _set_match(sid_a, item_a, fpath, "审计报告2023.pdf", 0.9, confirmed=1)
        record_session_decisions(sid_a)

        # 机构B：同样的需求，全新 session。batch 匹配 mock 成「无匹配」，
        # 证明锁定纯粹来自跨机构记忆。
        items_b = [{"item_no": "1", "category": "财务", "requirement": "近三年审计报告"}]
        sid_b = create_match_session("t", "b.xlsx", folder, items_b, institution_name="机构B")
        item_b = _get_first_item_id(sid_b)

        with patch("cangjie_fos.services.dd_match_service._llm_batch_match",
                   return_value={}):
            run_matching(sid_b, folder)

        item = _get_item(sid_b, item_b)
        assert item["matched_file_path"] == fpath
        assert item["match_reason"].startswith(MEMORY_REASON_PREFIX)
        assert item["verdict"] == "green"
        assert item["confidence"] >= 0.9

    def test_memory_skipped_when_file_absent_from_library(self, tmp_path):
        """记忆文件已不在当前材料库 → 不强行套用。"""
        from cangjie_fos.services.dd_match_service import (
            create_match_session, record_session_decisions, _apply_decision_memory,
        )
        folder = str(tmp_path)
        gone = str(tmp_path / "已删除.pdf")
        items_a = [{"item_no": "1", "category": "财务", "requirement": "审计报告"}]
        sid_a = create_match_session("t", "a.xlsx", folder, items_a, institution_name="机构A")
        item_a = _get_first_item_id(sid_a)
        _set_match(sid_a, item_a, gone, "已删除.pdf", 0.9, confirmed=1)
        record_session_decisions(sid_a)

        # 当前库里没有这个文件
        items_b = [{"id": "x", "requirement": "审计报告"}]
        hits = _apply_decision_memory("sid_b", items_b, index_rows=[
            {"file_path": str(tmp_path / "别的.pdf")},
        ])
        assert hits == 0


def _get_first_item_id(session_id: str) -> str:
    with _connect() as conn:
        return conn.execute(
            "SELECT id FROM dd_match_items WHERE session_id = ? ORDER BY item_no",
            (session_id,),
        ).fetchone()[0]
