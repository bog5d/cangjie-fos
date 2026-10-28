"""DD-V1 考场预检服务（开考前 Gate）· cangjie-fos#85。

**要回答的问题只有一个**：*现在能不能开考？*

开考前必须自动确认三件事是否**正确关联**：

1. **考卷** —— 投资机构真实下发的尽调清单；
2. **图书馆** —— 允许访问的基础材料库（固定快照 + 指纹）；
3. **标准答案** —— 历史上人工实际交付的材料包（已映射 + 人工已确认）。

**「未接入」≠「不存在」**（`#85` 明文要求）：

- ``NOT_PROVIDED`` ＝ 业务方**从未交付**这份标准答案；
- ``NOT_MAPPED``   ＝ 交付了，但**没映射**到本考卷 / 本图书馆；
- ``NOT_CONFIRMED``＝ 映射了，但缺人工确认；
- ``BROKEN``       ＝ 映射了，但与考卷 / 图书馆指纹**冲突**。

本模块**只读**，不建库、不摄取、不调用模型、不复制原件。

另外，本模块会**在开考前**把「主体范围未声明」这类**必然导致全盘 UNCERTAIN** 的坑
直接顶到台面上（`#108` 实测 P0-1）——**跑完才发现**是失败，
**开考前就拦下来**才算预检。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_gold_service as gold_svc

EXAM_CONTRACT_SCHEMA = "dd_v1_exam_contract.v1"

#: 主体范围的三种声明形态
SCOPE_MODES = ("SINGLE_ENTITY", "GROUP", "UNSCOPED")


class ExamContractError(ValueError):
    """考场契约结构非法。"""


# ── 契约读取 ─────────────────────────────────────────────────────────────────

def load_exam_contract(path: str | Path) -> dict[str, Any]:
    """读考场契约；结构非法 ⇒ 抛 ``ExamContractError``。"""
    p = Path(path)
    if not p.is_file():
        raise ExamContractError(f"EXAM_CONTRACT_NOT_FOUND:{p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExamContractError(f"EXAM_CONTRACT_UNREADABLE:{p}:{exc}") from exc
    validate_exam_contract(raw)
    return raw


def validate_exam_contract(raw: dict[str, Any]) -> None:
    if not isinstance(raw, dict):
        raise ExamContractError("EXAM_CONTRACT_NOT_OBJECT")
    if str(raw.get("schema_version") or "") != EXAM_CONTRACT_SCHEMA:
        raise ExamContractError(
            f"EXAM_CONTRACT_SCHEMA_MISMATCH:{raw.get('schema_version')!r}!={EXAM_CONTRACT_SCHEMA!r}")
    if not str(raw.get("exam_id") or "").strip():
        raise ExamContractError("EXAM_CONTRACT_MISSING_EXAM_ID")
    for key in ("checklist", "library", "gold"):
        if not isinstance(raw.get(key), dict):
            raise ExamContractError(f"EXAM_CONTRACT_MISSING_SECTION:{key}")
    scope = raw.get("entity_scope")
    if scope is not None:
        if not isinstance(scope, dict):
            raise ExamContractError("EXAM_CONTRACT_BAD_SECTION:entity_scope")
        mode = str(scope.get("scope_mode") or "")
        if mode and mode not in SCOPE_MODES:
            raise ExamContractError(f"EXAM_CONTRACT_BAD_SCOPE_MODE:{mode}")
        if mode == "GROUP" and not str(scope.get("group_root_id") or "").strip():
            raise ExamContractError("EXAM_CONTRACT_GROUP_SCOPE_WITHOUT_ROOT")


# ── 指纹 ─────────────────────────────────────────────────────────────────────

def library_fingerprint(meta: list[dict[str, Any]] | None) -> str:
    """图书馆快照指纹：``sha256( 排序后的 "file_id:sha256" 行 )``。

    与材料**路径无关**（同一批材料换个目录，指纹不变）⇒ 可跨机比较。
    """
    h = hashlib.sha256()
    rows = sorted(f"{m.get('file_id')}:{m.get('sha256')}" for m in (meta or [])
                  if str(m.get("file_id") or ""))
    for r in rows:
        h.update(r.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


# ── 各项检查 ────────────────────────────────────────────────────────────────

def _check_checklist(contract: dict[str, Any], library: dict[str, Any] | None,
                     obligations: list[dict[str, Any]] | None,
                     actual_sha256: str = "") -> dict[str, Any]:
    """考卷（投资机构清单）检查。"""
    c = contract.get("checklist") or {}
    declared_sha = str(c.get("sha256") or "").strip().lower()
    problems: list[str] = []
    if library is None:
        return {"state": "NOT_FOUND", "detail": "契约声明的图书馆未登记 ⇒ 考卷无从读取",
                "problems": ["CHECKLIST_LIBRARY_NOT_REGISTERED"], "item_count": 0,
                "obligation_count": 0, "declared_sha256": declared_sha,
                "actual_sha256": "", "checklist_id": str(c.get("checklist_id") or "")}
    obs = obligations or []
    if declared_sha and actual_sha256 and declared_sha != str(actual_sha256).lower():
        problems.append("CHECKLIST_FINGERPRINT_MISMATCH:契约记的考卷指纹与库内当前清单摘要不一致")
    return {
        "state": "FOUND",
        "detail": f"库内清单已登记，拆出 {len(obs)} 条原子义务",
        "problems": problems,
        "item_count": int(c.get("item_count") or 0),
        "obligation_count": len(obs),
        "declared_sha256": declared_sha,
        "actual_sha256": actual_sha256,
        "checklist_id": str(c.get("checklist_id") or ""),
        "institution": str(c.get("institution") or contract.get("institution") or ""),
    }


def _check_library(contract: dict[str, Any], library: dict[str, Any] | None,
                   material_root: Path | None, meta: list[dict[str, Any]] | None) -> dict[str, Any]:
    """图书馆（基础材料库）检查。"""
    c = contract.get("library") or {}
    declared = str(c.get("fingerprint") or "").strip().lower()
    if library is None:
        return {"state": "NOT_FOUND", "detail": "契约声明的图书馆未登记", "problems": ["LIBRARY_NOT_REGISTERED"],
                "material_count": 0, "declared_fingerprint": declared, "actual_fingerprint": "",
                "material_root": str(c.get("material_root") or "")}
    problems: list[str] = []
    root_str = str(c.get("material_root") or "")
    if root_str and material_root is not None and not material_root.exists():
        problems.append(f"LIBRARY_ROOT_UNREACHABLE:{root_str}")
    actual = library_fingerprint(meta)
    if declared and declared != actual:
        problems.append("LIBRARY_FINGERPRINT_MISMATCH:契约记的图书馆指纹与当前快照不一致")
    return {
        "state": "FOUND",
        "detail": f"图书馆已登记，快照 {len(meta or [])} 份材料",
        "problems": problems,
        "library_id": str(library.get("library_id") or c.get("library_id") or ""),
        "material_count": len(meta or []),
        "declared_fingerprint": declared,
        "actual_fingerprint": actual,
        "material_root": root_str,
    }


def _check_gold(contract: dict[str, Any], library_index: dict[str, dict[str, Any]] | None,
                forbidden_dirs: tuple[Path, ...] = (),
                *, library_fingerprint: str = "", checklist_sha256: str = "") -> dict[str, Any]:
    """标准答案（历史人工交付包）检查 —— **区分「未接入」与「不存在」**。"""
    g = contract.get("gold") or {}
    promised = bool(g.get("provided", False))
    manifest_path = str(g.get("manifest_path") or "").strip()
    out: dict[str, Any] = {
        "state": "NOT_PROVIDED",
        "detail": "契约未声明标准答案已提供 ⇒ 未接入评分基准（**不等于历史上没有标准答案**）",
        "problems": [],
        "gold_pack_id": str(g.get("gold_pack_id") or ""),
        "manifest_path": manifest_path,
        "confirmed_by": "",
        "confirmed_at": "",
        "resolution": None,
    }
    if not promised:
        return out
    if not manifest_path:
        out["state"] = "NOT_MAPPED"
        out["detail"] = "契约声明已提供标准答案，但没给清单路径 ⇒ 未映射"
        out["problems"].append("GOLD_MANIFEST_PATH_MISSING")
        return out
    mp = Path(manifest_path)
    if not mp.is_file():
        out["state"] = "NOT_PROVIDED"
        out["detail"] = (f"标准答案清单路径不存在（{mp}）⇒ 本机拿不到标准答案"
                         "（**未接入**；不等于历史人工交付包不存在）")
        out["problems"].append("GOLD_MANIFEST_FILE_MISSING")
        return out
    try:
        manifest = gold_svc.load_gold_manifest(mp)
    except gold_svc.GoldManifestError as exc:
        out["state"] = "BROKEN"
        out["detail"] = f"标准答案清单结构非法：{exc}"
        out["problems"].append(f"GOLD_MANIFEST_INVALID:{exc}")
        return out
    # 隔离闸：Gold 不得落在材料目录 / 运行目录 / Git 工作树内
    try:
        gold_svc.assert_gold_isolated(mp, *forbidden_dirs)
    except PermissionError as exc:
        out["state"] = "BROKEN"
        out["detail"] = f"标准答案未与考生隔离：{exc}"
        out["problems"].append(f"GOLD_NOT_ISOLATED:{exc}")
        return out

    resolved = gold_svc.resolve_gold_files(manifest, library_index or {"by_id": {}, "by_sha": {}})
    corr = gold_svc.check_correspondence(manifest, resolved,
                                         library_fingerprint=library_fingerprint,
                                         checklist_sha256=checklist_sha256)
    state, reason = gold_svc.gold_state(manifest, corr, provided=True)
    out.update({
        "state": state,
        "detail": reason,
        "problems": list(corr.get("problems") or []),
        "gold_pack_id": str(manifest.get("gold_pack_id") or ""),
        "confirmed_by": str(manifest.get("confirmed_by") or ""),
        "confirmed_at": str(manifest.get("confirmed_at") or ""),
        "resolution": resolved.get("summary"),
        "correspondence": corr,
        "gold_fingerprint": gold_svc.gold_fingerprint(manifest),
    })
    return out


def _check_entity_scope(contract: dict[str, Any], entities_registered: int,
                        obligations: list[dict[str, Any]] | None) -> dict[str, Any]:
    """**主体范围**检查 —— `#108` 实测 P0-1 的根因，开考前必须拦住。

    义务**没有指名主体**时，只有在**主体范围被明确声明**（单主体 / 集团）的前提下
    才可判定；未声明 ⇒ 必然全盘 UNCERTAIN（实测 42 题 91 义务全 UNCERTAIN、0 交付）。
    """
    scope = contract.get("entity_scope") or {}
    mode = str(scope.get("scope_mode") or "UNSCOPED")
    problems: list[str] = []
    notes: list[str] = []
    unnamed = 0
    for ob in obligations or []:
        if str(ob.get("entity") or "").strip():
            continue
        # ★ 原文里已经指名了（`entity_hint:主体甲`）⇒ **算「已指名」**：
        #   否则会把「已指名」的义务算成「未指名」⇒ 默认模板下**误拦**。
        scope_hint = str(ob.get("entity_scope") or "").strip()
        if scope_hint.startswith("entity_hint:") and scope_hint.split(":", 1)[1].strip():
            continue
        unnamed += 1
    if mode == "UNSCOPED":
        if entities_registered > 1 and unnamed:
            problems.append(
                f"ENTITY_SCOPE_UNDECLARED:登记了 {entities_registered} 个主体，"
                f"其中 {unnamed} 条义务未指名主体 ⇒ 该部分必然判「无法判定」⇒ 0 交付。"
                "须在契约里声明 scope_mode=SINGLE_ENTITY 或 GROUP（含 group_root_id）。")
        else:
            # ★ 只登记 0/1 个主体、或**没有**未指名主体的义务 ⇒ **不构成阻塞**，
            #   只作提醒（提醒 ≠ 阻塞：阻塞会把「本来没问题」也拦下来）。
            notes.append(
                f"主体范围未声明；当前登记 {entities_registered} 个主体、"
                f"未指名主体的义务 {unnamed} 条 ⇒ 暂不构成阻塞"
                "（多主体库 + 未指名主体时必须声明 scope_mode）")
    elif mode == "GROUP" and not str(scope.get("group_root_id") or "").strip():
        problems.append("ENTITY_SCOPE_GROUP_WITHOUT_ROOT:GROUP 模式必须给 group_root_id")
    return {
        "state": "DECLARED" if mode != "UNSCOPED" else "UNDECLARED",
        "scope_mode": mode,
        "group_root_id": str(scope.get("group_root_id") or ""),
        "entity_ids": list(scope.get("entity_ids") or []),
        "declared_by": str(scope.get("declared_by") or ""),
        "declared_at": str(scope.get("declared_at") or ""),
        "entities_registered": entities_registered,
        "unnamed_obligations": unnamed,
        "problems": problems,
        "notes": notes,
    }


# ── 主入口 ───────────────────────────────────────────────────────────────────

def run_preflight(contract: dict[str, Any], *,
                  library: dict[str, Any] | None = None,
                  meta: list[dict[str, Any]] | None = None,
                  obligations: list[dict[str, Any]] | None = None,
                  material_root: Path | None = None,
                  forbidden_dirs: tuple[Path, ...] = (),
                  entities_registered: int = 0,
                  ) -> dict[str, Any]:
    """跑考场预检 ⇒ 报告 + 是否具备正式评分条件。

    ``library``：``dd_v1_manifest_service.get_library`` 的返回（可为 None）。
    ``meta``：``dd_v1_bridge_service.build_meta`` 的结果（用于指纹与内容寻址）。
    ``obligations``：库内义务行（用于主体范围检查）。
    """
    validate_exam_contract(contract)
    idx = gold_svc.index_from_snapshot((library or {}).get("snapshot") or {}, meta)
    lib_fp = library_fingerprint(meta)
    checklist_fp = ""
    if library:
        try:
            from cangjie_fos.services import dd_v1_requirement_service as rq
            checklist_fp = rq.checklist_digest(str(library.get("library_id") or ""))
        except Exception:  # noqa: BLE001
            checklist_fp = ""
    checklist = _check_checklist(contract, library, obligations, actual_sha256=checklist_fp)
    lib = _check_library(contract, library, material_root, meta)
    gold = _check_gold(contract, idx, forbidden_dirs,
                       library_fingerprint=lib_fp,
                       checklist_sha256=str(checklist.get("actual_sha256") or ""))
    scope = _check_entity_scope(contract, entities_registered, obligations)

    blockers: list[dict[str, Any]] = []
    if checklist["state"] != "FOUND":
        blockers.append({"code": "CHECKLIST_NOT_FOUND", "detail": checklist["detail"],
                         "owner": "业务方 / 开发席", "remedy": "登记并摄取该机构的真实尽调清单"})
    if lib["state"] != "FOUND":
        blockers.append({"code": "LIBRARY_NOT_FOUND", "detail": lib["detail"],
                         "owner": "开发席", "remedy": "登记材料库并完成摄取"})
    if gold["state"] == "NOT_PROVIDED":
        blockers.append({"code": "TEST_BLOCKED_GOLD_NOT_PROVIDED",
                         "detail": gold["detail"], "owner": "业务方（#74 交办）",
                         "remedy": "交付历史清单 + 人工实际交付包；在此之前**只能做诊断试跑**"})
    elif gold["state"] == "NOT_MAPPED":
        blockers.append({"code": "TEST_BLOCKED_GOLD_NOT_MAPPED", "detail": gold["detail"],
                         "owner": "开发席", "remedy": "把标准答案映射到本考卷与本图书馆"})
    elif gold["state"] == "NOT_CONFIRMED":
        blockers.append({"code": "TEST_BLOCKED_GOLD_NOT_CONFIRMED", "detail": gold["detail"],
                         "owner": "业务方", "remedy": "补 confirmed_by / confirmed_at 人工确认"})
    elif gold["state"] == "BROKEN":
        blockers.append({"code": "TEST_BLOCKED_GOLD_BROKEN", "detail": gold["detail"],
                         "owner": "开发席 + 业务方", "remedy": "核对考卷/图书馆指纹与标准答案包"})
    for p in scope.get("problems") or []:
        blockers.append({"code": p.split(":")[0], "detail": p, "owner": "业务方 + 开发席",
                         "remedy": "在考场契约里声明 entity_scope（单主体 / 集团）"})

    ready = (checklist["state"] == "FOUND" and lib["state"] == "FOUND"
             and gold["state"] == "FOUND" and not blockers)
    # ★ 四态**一一对应**：`TEST_BLOCKED_GOLD_<STATE>`（`#85` 要求「四种状态分开报」）。
    #   旧写法把 `NOT_PROVIDED`（业务方**从未交付**）与 `NOT_MAPPED`（交付了但没对上）
    #   合并成 `TEST_BLOCKED_GOLD_NOT_MAPPED` ⇒ **把「没提供」说成「没映射」**（同类反向问题）。
    status = ("READY_FOR_FORMAL_SCORING" if ready
              else (f"TEST_BLOCKED_GOLD_{gold['state']}"
                    if str(gold.get("state") or "") in
                    ("NOT_PROVIDED", "NOT_MAPPED", "NOT_CONFIRMED", "BROKEN")
                    else "TEST_BLOCKED"))
    return {
        "schema_version": "dd_v1_exam_preflight.v1",
        "exam_id": str(contract.get("exam_id") or ""),
        "exam_name": str(contract.get("name") or ""),
        "institution": str(contract.get("institution") or ""),
        "status": status,
        "scoring_ready": ready,
        "checklist": checklist,
        "library": lib,
        "gold": gold,
        "entity_scope": scope,
        "blockers": blockers,
        "blocked_by": [b["code"] for b in blockers],
        "terms": {
            "not_provided": ["标准答案未提供"] if gold["state"] == "NOT_PROVIDED" else [],
            "not_mapped": ["标准答案未映射"] if gold["state"] == "NOT_MAPPED" else [],
            "not_confirmed": ["标准答案未人工确认"] if gold["state"] == "NOT_CONFIRMED" else [],
            "broken": ["标准答案与本次考场对不上"] if gold["state"] == "BROKEN" else [],
        },
        "note": ("预检通过 ⇒ 可开正式可评分业务考试"
                 if ready else
                 "预检未通过 ⇒ 只能做诊断试跑，且结果必须标「非正式评分」"),
    }


def preflight_markdown(rep: dict[str, Any]) -> str:
    """预检报告的人读版（可直接贴 Issue / 交接文档）。"""
    def _mark(state: str) -> str:
        return {"FOUND": "已找到 ✅", "NOT_FOUND": "未找到 ❌",
                "NOT_PROVIDED": "未提供 ⛔", "NOT_MAPPED": "未映射 ⚠️",
                "NOT_CONFIRMED": "未人工确认 ⚠️", "BROKEN": "冲突 ❌"}.get(state, state)

    lines = [
        f"# 考场预检报告 · {rep.get('exam_id')}",
        "",
        f"- 机构：{rep.get('institution') or '（未声明）'}",
        f"- 状态：**{rep.get('status')}**",
        f"- 是否具备正式评分条件：**{'是' if rep.get('scoring_ready') else '否'}**",
        "",
        "| 项 | 状态 | 说明 |",
        "|---|---|---|",
        f"| 考卷 | {_mark((rep.get('checklist') or {}).get('state', ''))} | "
        f"{(rep.get('checklist') or {}).get('detail', '')} |",
        f"| 图书馆 | {_mark((rep.get('library') or {}).get('state', ''))} | "
        f"{(rep.get('library') or {}).get('detail', '')} |",
        f"| 标准答案 | {_mark((rep.get('gold') or {}).get('state', ''))} | "
        f"{(rep.get('gold') or {}).get('detail', '')} |",
        f"| 对应关系 | {(rep.get('gold') or {}).get('correspondence', {}).get('state', '—')} | "
        f"{'；'.join((rep.get('gold') or {}).get('correspondence', {}).get('problems', []) or []) or '—'} |",
        f"| 主体范围 | {(rep.get('entity_scope') or {}).get('state', '—')} | "
        f"scope_mode={(rep.get('entity_scope') or {}).get('scope_mode', '—')}；"
        f"登记主体 {(rep.get('entity_scope') or {}).get('entities_registered', 0)} 个；"
        f"未指名主体义务 {(rep.get('entity_scope') or {}).get('unnamed_obligations', 0)} 条 |",
        "",
    ]
    if rep.get("blockers"):
        lines += ["## 阻塞原因", ""]
        for b in rep["blockers"]:
            lines.append(f"- **{b['code']}**：{b['detail']}\n  - 责任人：{b.get('owner', '')}\n"
                         f"  - 修复动作：{b.get('remedy', '')}")
        lines.append("")
    lines.append(f"> {rep.get('note', '')}")
    return "\n".join(lines)


def exam_contract_template() -> dict[str, Any]:
    """考场契约模板（供操作员填写；**不含任何真实业务内容**）。"""
    return {
        "schema_version": EXAM_CONTRACT_SCHEMA,
        "exam_id": "EX-<YYYYMMDD>-<NN>",
        "name": "<机构> 尽调清单 <年份>",
        "institution": "Institution_XX",
        "checklist": {
            "checklist_id": "CL-<id>",
            "library_id": "LIB-<id>",
            "sha256": "<考卷指纹>",
            "item_count": 0,
            "institution": "Institution_XX",
        },
        "library": {
            "library_id": "LIB-<id>",
            "material_root": "<受控本地路径>",
            "fingerprint": "<图书馆快照指纹>",
            "material_count": 0,
        },
        "gold": {
            "gold_pack_id": "GOLD-<id>",
            "manifest_path": "<受控本地路径>/gold_manifest.json",
            "provided": False,
        },
        "entity_scope": {
            "scope_mode": "UNSCOPED",
            "group_root_id": "",
            "entity_ids": [],
            "declared_by": "",
            "declared_at": "",
        },
    }
