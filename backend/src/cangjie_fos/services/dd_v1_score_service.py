"""DD-V1 错误分类服务（cangjie-fos#71 A4a · G-A4a-4 评分口径与错误分类）。

**不改** ``dd_v1_semantic_retrieval_service.assert_gold_isolated`` /
``score_against_gold`` 的隔离与评分语义——本模块只做三件事：

1. 追加「Gold 不在任何 Git 工作树内」的检测（``assert_gold_isolated`` 只查 forbidden_dirs，
   不查 Git 仓 ⇒ A4-3 判据必须由本模块补齐）。
2. 校验每条 Gold 的 ``confirmed_by`` + ``confirmed_at``：**缺失 ⇒ NOT_SCORABLE**
   （不是「空值当已确认」）。
3. **包装** ``score_against_gold`` 的输出，产出错误分类
   （TP / FP / FN / WRONG_ENTITY / WRONG_PERIOD / WRONG_FILE_SET / CONFIDENT_MISMATCH /
   UNCERTAIN 单列 / UNDETERMINED），并把每条错误回指到
   ``run_record_path`` + ``obligation_id`` + ``file_id`` + ``locator``。

红线：
- **不得**把 UNCERTAIN 计入 FN（单列，既不计入 FN 也不计入 TP）。
- **不得**把「没查」算成「查了没有」（NO_ANSWER 与 MISSING 分开记）。
"""
from __future__ import annotations

SCORE_IMPL_BEGIN = "GM:A4A:SCORE:IMPL:BEGIN"

import json
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

#: 分类口径（任务书第 1 段 G-A4a-4 表格，执行者不得自创）
CATEGORIES = ("TP", "FP", "FN", "WRONG_ENTITY", "WRONG_PERIOD", "WRONG_FILE_SET",
              "CONFIDENT_MISMATCH", "UNCERTAIN", "UNDETERMINED")
#: 「有货」判定：期望 / 答卷 报出证据的三种 verdict
GOODS_VERDICTS = ("MATCH", "PARTIAL", "OUTDATED")
#: 「没查」判定：**不得**把「没查」算成「查了没有」
NO_ANSWER_VERDICTS = ("MISSING", "NO_ANSWER")
HIGH_CONFIDENCE_DEFAULT = 0.8
#: 人工确认标记缺失时的 blocked_by 前缀
BLOCK_NOT_CONFIRMED = "GOLD_NOT_HUMAN_CONFIRMED"


class GoldIsolationError(PermissionError):
    """Gold 落在禁止位置（材料目录 / 运行目录 / Git 工作树内）。"""


def find_git_worktree(path: Path) -> Path | None:
    """向上找 ``.git``（目录或文件：worktree / submodule 的 .git 是文件）⇒ 工作树根。

    ``sem.assert_gold_isolated`` 只查 forbidden_dirs，**不查 Git 仓** ⇒ 本函数是 A4-3 的新增检测。
    """
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def assert_gold_not_in_git_worktree(gold_path: Path) -> None:
    """Gold 不得落在任何 Git 工作树内（**新增**检测，A4-3 判据要求）。"""
    wt = find_git_worktree(gold_path)
    if wt is not None:
        raise GoldIsolationError(f"GOLD_INSIDE_GIT_WORKTREE:{wt}")


def assert_gold_isolated(gold_path: Path, *forbidden_dirs: Path) -> None:
    """材料目录 / 运行目录隔离（**复用** sem.assert_gold_isolated，语义不改）+ Git 工作树隔离（新增）。"""
    sem.assert_gold_isolated(gold_path, *forbidden_dirs)
    assert_gold_not_in_git_worktree(gold_path)


def missing_confirmations(gold: list[dict[str, Any]] | None) -> list[str]:
    """缺 ``confirmed_by`` / ``confirmed_at`` 的 obligation_id。

    **缺失 ⇒ NOT_SCORABLE**（不是「空值当已确认」）。
    """
    out: list[str] = []
    for g in gold or []:
        oid = str(g.get("obligation_id") or "<no-obligation-id>")
        if not str(g.get("confirmed_by") or "").strip() or not str(g.get("confirmed_at") or "").strip():
            out.append(oid)
    return out


def _file_index(meta: list[dict[str, Any]] | None) -> dict[str, dict[str, str]]:
    idx: dict[str, dict[str, str]] = {}
    for m in meta or []:
        idx[str(m.get("file_id"))] = {
            "entity": str(m.get("entity") or ""),
            "period": str(m.get("period") or ""),
            "relative_path": str(m.get("relative_path") or ""),
        }
    return idx


def _expected_dimension(gold_rec: dict[str, Any], expected_files: set[str],
                        file_index: dict[str, dict[str, str]], key: str) -> tuple[str | None, str]:
    """期望主体 / 期间来源优先级：Gold 字段 → expected_files 对应件的**唯一值** → 推不出（None）。"""
    gval = str(gold_rec.get(f"expected_{key}") or "").strip()
    if gval:
        return gval, "GOLD_FIELD"
    vals = {file_index[f][key] for f in sorted(expected_files)
            if f in file_index and file_index[f].get(key)}
    if len(vals) == 1:
        return next(iter(vals)), "DERIVED_FROM_EXPECTED_FILES"
    return None, "UNDETERMINED"


def _answered_dimension(answer: dict[str, Any] | None, file_index: dict[str, dict[str, str]],
                        key: str) -> str | None:
    """答卷选中件的 entity / period（多值 ⇒ 推不出）。"""
    vals: set[str] = set()
    for c in ((answer or {}).get("candidate_files") or []):
        v = str(c.get(key) or "").strip()
        if not v:
            v = str((file_index.get(str(c.get("file_id"))) or {}).get(key) or "").strip()
        if v:
            vals.add(v)
    if len(vals) == 1:
        return next(iter(vals))
    return None


def _classify_row(row: dict[str, Any], gold_rec: dict[str, Any], answer: dict[str, Any] | None,
                  file_index: dict[str, dict[str, str]], high_conf: float) -> dict[str, Any]:
    """单条 Gold × 答卷 ⇒ 分类（**口径照任务书表格**，不另造）。"""
    exp_v = str(row.get("expected_verdict") or "")
    a_v = str(row.get("agent_verdict") or "")
    exp_files = set(row.get("expected_files") or [])
    ans_files = set(row.get("agent_files") or [])
    conf = row.get("agent_confidence")
    exp_entity, exp_entity_src = _expected_dimension(gold_rec, exp_files, file_index, "entity")
    exp_period, exp_period_src = _expected_dimension(gold_rec, exp_files, file_index, "period")
    ans_entity = _answered_dimension(answer, file_index, "entity")
    ans_period = _answered_dimension(answer, file_index, "period")
    exp_has_goods = exp_v in GOODS_VERDICTS
    ans_has_goods = a_v in GOODS_VERDICTS
    extra = ans_files - exp_files
    missing = exp_files - ans_files
    if a_v == "UNCERTAIN":
        category, note = "UNCERTAIN", "答卷 verdict=UNCERTAIN ⇒ 单列（不计入 FN，也不计入 TP）"
    elif exp_has_goods and a_v in NO_ANSWER_VERDICTS:
        category, note = "FN", "期望有货，答卷 MISSING / NO_ANSWER"
    elif ans_has_goods and exp_v in ("MISSING", "UNCERTAIN"):
        category, note = "FP", "期望 MISSING / UNCERTAIN，答卷报了有货"
    elif a_v == exp_v and ans_files == exp_files:
        category, note = "TP", "verdict 对 + 文件集相等"
    elif ans_has_goods and exp_has_goods:
        if exp_entity and ans_entity and exp_entity != ans_entity:
            category, note = "WRONG_ENTITY", "答卷选中件的 entity ≠ 期望主体"
        elif exp_period and ans_period and exp_period != ans_period:
            category, note = "WRONG_PERIOD", "答卷选中件的 period ≠ 期望期间"
        elif a_v == exp_v and extra and missing:
            category, note = "WRONG_FILE_SET", "verdict / 主体 / 期间都对，但文件集错选"
        elif extra:
            category, note = "FP", "文件集多出非期望件"
        elif a_v == exp_v:
            category, note = "WRONG_FILE_SET", "文件集与期望不一致"
        else:
            category, note = "UNDETERMINED", "verdict 不一致且主体 / 期间无差异 ⇒ 不强行归类"
    else:
        category, note = "UNDETERMINED", "期望 / 答卷组合不在分类表内 ⇒ 不强行归类"
    confident = isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf >= high_conf
    flags: list[str] = []
    if confident and category not in ("TP", "UNCERTAIN"):
        flags.append("CONFIDENT_MISMATCH")
    return {
        "obligation_id": str(row.get("obligation_id")),
        "category": category,
        "flags": flags,
        "confident_mismatch": "CONFIDENT_MISMATCH" in flags,
        "expected_verdict": exp_v,
        "agent_verdict": a_v,
        "expected_files": sorted(exp_files),
        "agent_files": sorted(ans_files),
        "expected_entity": exp_entity,
        "expected_entity_source": exp_entity_src,
        "expected_period": exp_period,
        "expected_period_source": exp_period_src,
        "answer_entity": ans_entity,
        "answer_period": ans_period,
        "confidence_or_uncertain": conf,
        "note": note,
    }


def _primary_file_ref(row: dict[str, Any], answer: dict[str, Any] | None,
                      file_index: dict[str, dict[str, str]]) -> tuple[str, str, str]:
    """错误回指：优先答卷选中件；locator 取 ``candidate_files[].locator``，
    为空则由 meta 的 ``relative_path`` 派生并标 ``locator_source=RULE_ONLY_DERIVED``。"""
    for c in ((answer or {}).get("candidate_files") or []):
        fid = str(c.get("file_id") or "")
        loc = str(c.get("locator") or "").strip()
        if loc:
            return fid, loc, "ANSWER_CANDIDATE"
        rel = (file_index.get(fid) or {}).get("relative_path") or str(c.get("relative_path") or "")
        return fid, rel, "RULE_ONLY_DERIVED"
    for f in sorted(row.get("expected_files") or []):
        rel = (file_index.get(str(f)) or {}).get("relative_path") or ""
        return str(f), rel, "RULE_ONLY_DERIVED"
    return "", "", "NONE"


def _collect_answers(run_records: list[dict[str, Any]] | None, record_paths: list[str] | None,
                     run_dir: Path | None) -> tuple[dict[str, Any], dict[str, str]]:
    answers: dict[str, Any] = {}
    paths: dict[str, str] = {}
    for i, rec in enumerate(run_records or []):
        layer = rec.get(rec.get("authoritative_validation", "semantic_validation"), {}) or {}
        for r in layer.get("accepted", []) or []:
            oid = str(r.get("obligation_id"))
            answers[oid] = r
            if record_paths and i < len(record_paths) and record_paths[i]:
                p = Path(record_paths[i])
                if run_dir is not None:
                    try:
                        p = p.relative_to(Path(run_dir))
                    except ValueError:
                        pass
                paths[oid] = p.as_posix()
    return answers, paths


def score_with_classification(run_records: list[dict[str, Any]] | None,
                               gold: list[dict[str, Any]] | None, *,
                               meta: list[dict[str, Any]] | None = None,
                               record_paths: list[str] | None = None,
                               run_dir: Path | None = None,
                               min_obligations: int = 30,
                               high_conf: float = HIGH_CONFIDENCE_DEFAULT,
                               require_confirmed: bool = True,
                               provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """包装 ``sem.score_against_gold``：加 Gold 人工确认校验 + 错误分类 + 错误回指。

    **不改** ``score_against_gold`` 的隔离与评分语义（``base`` 是它的原样输出）。
    """
    prov = dict(provenance or {})
    if not gold:
        base = sem.score_against_gold(run_records, gold, min_obligations=min_obligations,
                                      high_conf=high_conf)
        return {**base, "base": base, "classification": None, "provenance": prov}
    missing = missing_confirmations(gold) if require_confirmed else []
    if missing:
        return {
            "status": "NOT_SCORABLE",
            "blocked_by": [f"{BLOCK_NOT_CONFIRMED}:" + ",".join(sorted(missing))],
            "scores": None,
            "base": None,
            "classification": None,
            "provenance": prov,
            "note": "每条 Gold 都必须有 confirmed_by + confirmed_at；缺失 ⇒ NOT_SCORABLE（不是当已确认）",
        }
    base = sem.score_against_gold(run_records, gold, min_obligations=min_obligations,
                                  high_conf=high_conf)
    file_index = _file_index(meta)
    gold_by_oid = {str(g.get("obligation_id")): g for g in gold}
    answers, paths = _collect_answers(run_records, record_paths, run_dir)
    rows: list[dict[str, Any]] = []
    counts = {c: 0 for c in CATEGORIES}
    for r in base.get("rows") or []:
        oid = str(r.get("obligation_id"))
        g = gold_by_oid.get(oid, {})
        ans = answers.get(oid)
        classified = _classify_row(r, g, ans, file_index, high_conf)
        fid, loc, lsrc = _primary_file_ref(r, ans, file_index)
        classified.update({"run_record_path": paths.get(oid, ""),
                           "file_id": fid, "locator": loc, "locator_source": lsrc})
        rows.append(classified)
        counts[classified["category"]] += 1
        if classified["confident_mismatch"]:
            counts["CONFIDENT_MISMATCH"] += 1
    errors = [r for r in rows if r["category"] != "TP"]
    return {
        "status": base.get("status"),
        "n_obligations": base.get("n_obligations"),
        "agent": base.get("agent"),
        "rule_only_baseline": base.get("rule_only_baseline"),
        "base": base,
        "classification": {
            "categories": list(CATEGORIES),
            "counts": counts,
            "fn_count": counts["FN"],
            "uncertain_count": counts["UNCERTAIN"],
            "confident_mismatch_count": counts["CONFIDENT_MISMATCH"],
            "rows": rows,
            "errors": errors,
            "note": "UNCERTAIN 单列（不计入 FN）；每条错误回指 run_record_path + obligation_id + file_id + locator",
        },
        "provenance": prov,
    }


def classification_table(classification: dict[str, Any] | None) -> list[dict[str, Any]]:
    """错误分类表（一行一条义务；TP 也留行，便于核对类别覆盖）。"""
    if not classification:
        return []
    return list(classification.get("rows") or [])
SCORE_IMPL_END = "GM:A4A:SCORE:IMPL:END"
