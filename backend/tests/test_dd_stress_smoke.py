"""DD 物料架构压力基准的「快测固化版」——把压测脚本的核心不变量锁进 CI。

完整压测见 backend/bench/dd_stress.py（可手动按 scale 放大 + 出图）。
本文件用最小规模跑通同一套真实流水线（LLM mock），断言关键不变量不回归：
  全文落库覆盖率 / 验证判定齐全 / 跨机构记忆锁定 / 并发零错误 / 各项延迟>0。
"""
from __future__ import annotations
import sys
from pathlib import Path

# 让 bench 包可被导入（backend/ 加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench.dd_stress import run_benchmark  # noqa: E402


def test_stress_benchmark_invariants():
    """小规模跑通整条流水线 + 基准工具自身，断言核心不变量。"""
    m = run_benchmark(scale="small", checklist_n=16, seed_mem=100, concurrency=3)

    # 索引：全部文件入库，全文落库覆盖率应满（可读 txt/docx/xlsx）
    assert m["indexed"] == m["file_count"]
    assert m["content_coverage"] >= 0.99, m["content_coverage"]

    # 机器验证：每条需求都拿到 verdict（绿+黄+红 = 清单数），且有绿（相关匹配）
    assert m["verdict_green"] + m["verdict_yellow"] + m["verdict_red"] == 16
    assert m["verdict_green"] >= 1

    # 跨机构记忆：A 确认 → B（LLM 返空）自动锁定
    assert m["cross_inst_ok"] == 1

    # 并发：全部成功，无 SQLite 锁错误
    assert m["concurrency_ok"] == m["concurrency_total"]
    assert not m["concurrency_errors"]

    # 延迟指标产出正常（>0）
    assert m["prefilter_ms"] > 0
    assert m["mem_lookup_us"] > 0
    assert m["index_throughput"] > 0
    assert m["match_throughput"] > 0
