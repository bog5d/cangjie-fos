"""DD-V1 WP3-2：候选**分批扩展**与停止条件 · `#108` 实测 P0-3。

**这个文件锁死的红线**：

1. ★ 候选超出上限时**不得**静默漏检 —— 必须报出
   **找到多少 / 实际检查多少 / 还有多少未看 / 为什么停**；
2. 分批扩展**不得**取消所有上限（资源失控）⇒ 必须有**预算**；
3. 停止条件必须**显式可复核**（``VERDICT_STABLE`` / ``BUDGET_EXHAUSTED`` /
   ``STEPS_EXHAUSTED`` / ``SINGLE_STEP``）；
4. ★ 结论**只覆盖已检查部分** —— 未看部分**不得**当作「不存在」；
5. ★ 扩展**只改「看多少」，不改「怎么判」** —— 判定逻辑与安全闸一字不动
   （复用既有 ``match_obligation`` 的 ``candidate_cap`` 参数）。

★ 夹具为合成数据。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import dd_v1_candidate_expansion_service as cx
from cangjie_fos.services import dd_v1_match_service as ms


def _fake_match(spec: dict[int, dict]):
    """按 cap 返回预置结果（记录被调用过哪些 cap）。"""
    calls: list[int] = []

    def _match(library_id, obligation_id, candidate_cap=20, db_path=None):
        calls.append(candidate_cap)
        return spec.get(candidate_cap, spec[min(spec)])

    _match.calls = calls          # type: ignore[attr-defined]
    return _match


def _res(verdict: str, files: list[str], found: int, used: int, trunc: int) -> dict:
    return {
        "verdict": verdict,
        "candidate_count": found,
        "candidates_seen": used,
        "truncated_candidate_count": trunc,
        "capped": trunc > 0,
        "candidate_cap_note": f"已达候选上限，还有 {trunc} 份候选未看" if trunc else "",
        "candidates": [{"file_id": f, "deliverable": True} for f in files],
        "missing_detail": [],
    }


class TestExpansionReadouts:
    def test_reports_found_checked_unchecked_and_stop_reason(self, monkeypatch):
        """★ 四个读数必须齐：找到多少 / 检查多少 / 未看多少 / 为什么停。"""
        spec = {
            20: _res("MATCHED", ["F1"], found=116, used=20, trunc=96),
            60: _res("MATCHED", ["F1"], found=116, used=60, trunc=56),
            180: _res("MATCHED", ["F1"], found=116, used=116, trunc=0),
        }
        fake = _fake_match(spec)
        monkeypatch.setattr(ms, "match_obligation", fake)
        out = cx.match_with_expansion("LIB", "O1")
        assert out["candidates_found"] == 116
        assert out["candidates_checked"] == 116
        assert out["candidates_unchecked"] == 0
        assert out["stop_reason"] in cx.STOP_REASONS
        assert fake.calls == [20, 60, 180], fake.calls

    def test_unread_candidates_are_never_called_missing(self, monkeypatch):
        """★ 触顶时必须写明「未看部分不得当作不存在」。"""
        spec = {20: _res("UNCERTAIN", [], found=116, used=20, trunc=96)}
        fake = _fake_match(spec)
        monkeypatch.setattr(ms, "match_obligation", fake)
        out = cx.match_with_expansion("LIB", "O1", steps=(20,))
        assert out["candidates_unchecked"] == 96
        assert "未看" in out["note"]
        assert "不存在" in out["note"]

    def test_single_step_reason(self, monkeypatch):
        monkeypatch.setattr(ms, "match_obligation",
                            _fake_match({20: _res("MATCHED", ["F1"], 5, 5, 0)}))
        out = cx.match_with_expansion("LIB", "O1", steps=(20,))
        assert out["stop_reason"] == "SINGLE_STEP"
        assert out["expanded"] is False

    def test_verdict_stable_but_pool_not_exhausted_keeps_going(self, monkeypatch):
        """★ 只看「结论稳定」是**巧合式停止**：正确答案可能排在窗口之外。

        ⇒ 候选池**没穷尽**就必须继续扩批（哪怕两批结论一样）。
        """
        spec = {
            20: _res("MATCHED", ["F1"], 116, 20, 96),
            60: _res("MATCHED", ["F1"], 116, 60, 56),
            180: _res("MATCHED", ["F1"], 116, 116, 0),
        }
        fake = _fake_match(spec)
        monkeypatch.setattr(ms, "match_obligation", fake)
        out = cx.match_with_expansion("LIB", "O1", steps=(20, 60, 180))
        assert fake.calls == [20, 60, 180], fake.calls
        assert out["stop_reason"] == "VERDICT_STABLE"
        assert out["candidates_unchecked"] == 0

    def test_stable_verdict_with_truncation_continues(self, monkeypatch):
        spec = {
            20: _res("MATCHED", ["F1"], 116, 20, 96),
            60: _res("MATCHED", ["F1"], 116, 60, 56),
        }
        fake = _fake_match(spec)
        monkeypatch.setattr(ms, "match_obligation", fake)
        out = cx.match_with_expansion("LIB", "O1", steps=(20, 60))
        assert out["stop_reason"] == "STEPS_EXHAUSTED"
        assert fake.calls == [20, 60]

    def test_unstable_verdict_keeps_going(self, monkeypatch):
        spec = {
            20: _res("MATCHED", ["F1"], 116, 20, 96),
            60: _res("PARTIAL", ["F1"], 116, 60, 56),
        }
        fake = _fake_match(spec)
        monkeypatch.setattr(ms, "match_obligation", fake)
        out = cx.match_with_expansion("LIB", "O1", steps=(20, 60))
        assert out["stop_reason"] == "STEPS_EXHAUSTED"
        assert fake.calls == [20, 60]

    def test_budget_exhausted(self, monkeypatch):
        spec = {20: _res("MATCHED", ["F1"], 200, 20, 180)}
        fake = _fake_match(spec)
        monkeypatch.setattr(ms, "match_obligation", fake)
        out = cx.match_with_expansion("LIB", "O1", steps=(20, 60, 180), max_candidates=20)
        assert out["stop_reason"] == "BUDGET_EXHAUSTED"
        assert fake.calls == [20]

    def test_stop_reasons_are_a_closed_enum(self):
        assert cx.STOP_REASONS == ("VERDICT_STABLE", "BUDGET_EXHAUSTED",
                                   "STEPS_EXHAUSTED", "SINGLE_STEP")


class TestExpansionDoesNotChangeJudgement:
    """红线 5：扩展只改「看多少」，不改「怎么判」。"""

    def test_same_cap_gives_same_verdict_as_plain_match(self, monkeypatch):
        spec = {20: _res("MATCHED", ["F1"], 30, 20, 10)}
        monkeypatch.setattr(ms, "match_obligation", _fake_match(spec))
        out = cx.match_with_expansion("LIB", "O1", steps=(20,))
        assert out["verdict"] == "MATCHED"
        assert out["files"] == ["F1"]

    def test_candidate_cap_is_only_knob_used(self, monkeypatch):
        """扩展**只**通过 candidate_cap 调参，不改判定参数。"""
        seen = {}

        def _match(library_id, obligation_id, candidate_cap=20, db_path=None):
            seen["cap"] = candidate_cap
            return _res("MATCHED", ["F1"], 30, candidate_cap, max(0, 30 - candidate_cap))

        monkeypatch.setattr(ms, "match_obligation", _match)
        cx.match_with_expansion("LIB", "O1", steps=(20, 60))
        assert seen["cap"] == 60
