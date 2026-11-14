"""证据自证能力的回归（独立 Reviewer 第 3 轮 MINOR-1 / MINOR-2）。

★ **要防的坑**：
- **MINOR-2**：`gold_fingerprint` 此前把 ``obligation_id``（**uuid4，每次建库都变**）一起 hash
  ⇒ **同一份 Gold 每次指纹都不同** ⇒ 该字段**自证不了**「用的是同一份标准答案」（假信号）。
- **MINOR-1**：运行清单的 ``model.degrade_reason`` 恒为空 ⇒ 施工令 §6 要求的「降级原因」
  在**门禁读的那份**里看不到。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

from cangjie_fos.services import dd_v1_gold_service as gold_svc  # noqa: E402


def _manifest(oid: str, key: str, sha: str) -> dict:
    return {
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-FP-01",
        "exam_id": "EX-FP",
        "confirmed_by": "测试员",
        "confirmed_at": "2026-10-30T00:00:00+08:00",
        "items": [{"obligation_id": oid, "obligation_key": key, "item_no": "1-1",
                   "expected_verdict": "MATCH",
                   "expected_files": [{"sha256": sha, "entity": "主体甲", "period": "2024"}]}],
    }


def test_gold_fingerprint_is_stable_across_uuid_churn():
    """★ 同一份 Gold（只是 ``obligation_id`` 变了）⇒ **指纹必须相同**。"""
    a = _manifest("uuid-1111", "OBL-STABLE-1", "a" * 64)
    b = _manifest("uuid-2222", "OBL-STABLE-1", "a" * 64)
    assert gold_svc.gold_fingerprint(a) == gold_svc.gold_fingerprint(b), \
        "指纹仍随 uuid 变化 ⇒ 自证不了「同一份 Gold」"


def test_gold_fingerprint_changes_when_content_changes():
    """★ 内容变了（期望材料不同）⇒ 指纹**必须变**（否则是反向失效）。"""
    a = _manifest("uuid-1111", "OBL-STABLE-1", "a" * 64)
    c = _manifest("uuid-1111", "OBL-STABLE-1", "b" * 64)
    assert gold_svc.gold_fingerprint(a) != gold_svc.gold_fingerprint(c)


def test_gold_fingerprint_changes_when_obligation_key_changes():
    """★ 稳定键变了 ⇒ 指纹**必须变**（不同义务 ⇒ 不是同一份标准答案）。"""
    a = _manifest("uuid-1111", "OBL-A", "a" * 64)
    b = _manifest("uuid-1111", "OBL-B", "a" * 64)
    assert gold_svc.gold_fingerprint(a) != gold_svc.gold_fingerprint(b)


def test_gold_fingerprint_is_deterministic():
    """★ 同一份 manifest 连续算两次 ⇒ 相同（无随机性、无时间戳）。"""
    a = _manifest("uuid-1111", "OBL-STABLE-1", "a" * 64)
    assert gold_svc.gold_fingerprint(a) == gold_svc.gold_fingerprint(a)


def test_manifest_carries_degrade_reason_key():
    """★ MINOR-1：门禁读的那份（运行清单的 model 块）**必须**带 ``degrade_reason`` 字段。"""
    src = (REPO / "tools" / "dd_v1_exam_suite.py").read_text("utf-8")
    # ⇒ 取「运行清单的 model 块」那一段（从 model_participation = { 到它结束的 dict）
    start = src.index("model_participation = {")
    block = src[start:start + 3000]
    assert '"degrade_reason"' in block, "运行清单的 model 块缺 degrade_reason"
    # ⇒ 且它**不是**写死的空串（要有真实来源：成绩单的 run_provenance / 答卷）
    seg = block[block.index('"degrade_reason"'):block.index('"degrade_reason"') + 200]
    assert "run_provenance" in seg and "degrade_reason_from_sheet" in seg, seg[:200]
