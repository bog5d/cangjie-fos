"""DD-V1 标准答案包（Gold Manifest）服务 · cangjie-fos#85（永久验收红线）。

**为什么单独成模块**：``#85`` 要求「历史人工交付包」成为**可被机器验证的评分基准**，
而不是「业务方口头说交付过」。本模块负责三件事：

1. **标准答案包清单**（``dd_v1_gold_manifest.v1``）：考卷 ID、标准答案包 ID、
   图书馆快照 ID、题目↔人工交付材料映射、材料指纹、人工确认状态。
2. **内容指纹解析**：人工交付包里的文件与图书馆里的文件**名称不同、路径不同**
   但**内容相同**时，必须能对上 ⇒ 匹配只用 **SHA256**，**禁**用文件名判定。
3. **状态语义分离**（本模块最要紧的一条）：

   ==================  ==========================================================
   状态                 含义
   ==================  ==========================================================
   ``FOUND``            找到了、映射完整、人工已确认 ⇒ 可正式评分
   ``NOT_PROVIDED``     **业务方从未交付**这份标准答案（例：#74 已暂停交付）
   ``NOT_MAPPED``       **拿到了，但没映射**到本考卷/本图书馆（未接入 ≠ 不存在）
   ``NOT_CONFIRMED``    映射了，但缺 ``confirmed_by`` / ``confirmed_at``
   ``BROKEN``           映射了，但与考卷/图书馆指纹**冲突**（对不上）
   ==================  ==========================================================

红线：
- **不得**把「未接入」写成「不存在」——两者在 ``gold.state`` 里是**不同取值**。
- **不得**用文件名认定答案正确；文件名只作 ``relative_path`` 留痕。
- Gold 不得落在材料目录 / 运行目录 / **Git 工作树**内（复用既有隔离闸）。
- 本模块**只读**；不得改写人工标准答案（改答案提分是禁止行为）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_score_service as sc

#: 标准答案包清单版本
GOLD_MANIFEST_SCHEMA = "dd_v1_gold_manifest.v1"
#: 允许的 Gold 状态（**闭枚举**；新增取值必须同步改本模块与测试）
GOLD_STATES = ("FOUND", "NOT_PROVIDED", "NOT_MAPPED", "NOT_CONFIRMED", "BROKEN")
#: 单份材料的解析状态
FILE_RESOLUTION_STATES = ("RESOLVED", "MISSING_IN_LIBRARY", "AMBIGUOUS_CONTENT", "NO_FINGERPRINT")


class GoldManifestError(ValueError):
    """标准答案包清单结构非法。"""


# ── 读取与结构校验 ────────────────────────────────────────────────────────────

def load_gold_manifest(path: str | Path) -> dict[str, Any]:
    """读标准答案包清单；结构不合法 ⇒ 抛 ``GoldManifestError``（不静默降级）。"""
    p = Path(path)
    if not p.is_file():
        raise GoldManifestError(f"GOLD_MANIFEST_NOT_FOUND:{p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldManifestError(f"GOLD_MANIFEST_UNREADABLE:{p}:{exc}") from exc
    validate_gold_manifest(raw)
    return raw


def validate_gold_manifest(raw: dict[str, Any]) -> None:
    """清单结构校验。**只查结构，不查业务正确性**（业务正确性由人工确认背书）。"""
    if not isinstance(raw, dict):
        raise GoldManifestError("GOLD_MANIFEST_NOT_OBJECT")
    if str(raw.get("schema_version") or "") != GOLD_MANIFEST_SCHEMA:
        raise GoldManifestError(
            f"GOLD_MANIFEST_SCHEMA_MISMATCH:{raw.get('schema_version')!r}!={GOLD_MANIFEST_SCHEMA!r}")
    for key in ("gold_pack_id", "items"):
        if not str(raw.get(key) or "").strip() and key != "items":
            raise GoldManifestError(f"GOLD_MANIFEST_MISSING_FIELD:{key}")
    items = raw.get("items")
    if not isinstance(items, list):
        raise GoldManifestError("GOLD_MANIFEST_ITEMS_NOT_LIST")
    seen: set[str] = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise GoldManifestError(f"GOLD_ITEM_NOT_OBJECT:{i}")
        oid = str(it.get("obligation_id") or "").strip()
        if not oid:
            raise GoldManifestError(f"GOLD_ITEM_MISSING_OBLIGATION_ID:{i}")
        if oid in seen:
            raise GoldManifestError(f"GOLD_ITEM_DUPLICATE_OBLIGATION_ID:{oid}")
        seen.add(oid)
        verdict = str(it.get("expected_verdict") or "").strip()
        if verdict not in ("MATCH", "PARTIAL", "OUTDATED", "CONFLICT", "MISSING", "UNCERTAIN"):
            raise GoldManifestError(f"GOLD_ITEM_BAD_VERDICT:{oid}:{verdict}")
        files = it.get("expected_files")
        if files is None:
            files = []
        if not isinstance(files, list):
            raise GoldManifestError(f"GOLD_ITEM_FILES_NOT_LIST:{oid}")
        for f in files:
            if not isinstance(f, dict):
                raise GoldManifestError(f"GOLD_FILE_NOT_OBJECT:{oid}")
            if not str(f.get("sha256") or "").strip():
                # 允许没有指纹（记为 NO_FINGERPRINT），但**不允许**只有文件名就当答案
                if not str(f.get("relative_path") or "").strip():
                    raise GoldManifestError(f"GOLD_FILE_NO_FINGERPRINT_NO_PATH:{oid}")


# ── 图书馆索引 ───────────────────────────────────────────────────────────────

def build_library_index(meta: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """由材料 meta 建索引：``file_id`` → 指纹/路径/主体/期间/类型。

    同时建一张 **sha256 → [file_id]** 的反查表（**内容寻址**），
    这是「人工包文件名不同、路径不同但内容相同也能对上」的唯一依据。
    """
    by_id: dict[str, dict[str, Any]] = {}
    by_sha: dict[str, list[str]] = {}
    # ★★ WP3（#108 波总裁定 · 2026-10-30）：**诊断用反查表**（路径／文件名）
    #   ⇒ 「11 份缺失 / 4 份歧义」必须能区分：**真缺料** vs **路径解析错** vs
    #   **文件名错** vs **哈希识别错** vs **主体/期间范围错** ⇒ ⇒ 只按内容寻址
    #   只会答「不在库里」，**答不出该怎么修**。
    #   ★ 这两张表**只用于诊断**，**不参与**内容寻址判定（判定仍只认 sha256）。
    by_path: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for m in meta or []:
        fid = str(m.get("file_id") or "").strip()
        if not fid:
            continue
        sha = str(m.get("sha256") or "").strip().lower()
        rel = str(m.get("relative_path") or "").strip().replace("\\", "/")
        if rel:
            by_path.setdefault(rel.lower(), []).append(fid)
            by_name.setdefault(rel.rsplit("/", 1)[-1].lower(), []).append(fid)
        by_id[fid] = {
            "file_id": fid,
            "sha256": sha,
            "relative_path": str(m.get("relative_path") or ""),
            "entity": str(m.get("entity") or ""),
            "entity_basis": str(m.get("entity_basis") or ""),
            "period": str(m.get("period") or ""),
            "doc_type": str(m.get("doc_type") or ""),
            "part": str(m.get("part") or ""),
            "version_status": str(m.get("version_status") or ""),
        }
        if sha:
            by_sha.setdefault(sha, []).append(fid)
    return {"by_id": by_id, "by_sha": by_sha, "by_path": by_path, "by_name": by_name}


def index_from_snapshot(snapshot: dict[str, Any] | list[dict[str, Any]] | None,
                        meta: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """快照对象 + meta ⇒ 图书馆索引。

    ``snapshot`` 支持三种形态（**都要能用**，否则会误判成「标准答案材料在库里找不到」）：

    1. ``{file_id: {"sha256": ...}}``（``dd_v1_manifest_service`` 的快照）；
    2. ``{"files": [{"file_id", "relative_path", "sha256"}, ...]}``
       （``dd_v1_snapshot_freeze_service`` 的冻结快照 —— **sha256 只在这里**，
       ``meta.json`` 里通常**没有** sha256 字段）；
    3. ``[{"file_id", "sha256"}, ...]``。

    快照里有的 sha256 优先（快照是冻结指纹的权威），meta 里的作为补充。
    """
    idx = build_library_index(meta)
    rows: list[dict[str, Any]] = []
    if isinstance(snapshot, dict):
        files = snapshot.get("files")
        if isinstance(files, list):
            rows = [r for r in files if isinstance(r, dict)]
        else:
            for fid, rec in snapshot.items():
                if isinstance(rec, dict):
                    rows.append({"file_id": fid, **rec})
                elif isinstance(rec, str):
                    rows.append({"file_id": fid, "sha256": rec})
    elif isinstance(snapshot, list):
        rows = [r for r in snapshot if isinstance(r, dict)]
    for r in rows:
        fid = str(r.get("file_id") or "").strip()
        sha = str(r.get("sha256") or "").strip().lower()
        if not fid or not sha:
            continue
        row = idx["by_id"].setdefault(fid, {"file_id": fid, "relative_path": "", "entity": "",
                                            "entity_basis": "", "period": "", "doc_type": "",
                                            "part": "", "version_status": ""})
        row["sha256"] = sha
        if r.get("relative_path"):
            row["relative_path"] = str(r.get("relative_path"))
        idx["by_sha"].setdefault(sha, [])
        if fid not in idx["by_sha"][sha]:
            idx["by_sha"][sha].append(fid)
    # ★ 诊断反查表补齐（快照形态可能不带 relative_path ⇒ 保持已有值，不覆盖）
    for fid, rec in list(idx["by_id"].items()):
        rel = str(rec.get("relative_path") or "").strip().replace("\\", "/")
        if not rel:
            continue
        idx.setdefault("by_path", {}).setdefault(rel.lower(), []).append(fid)
        idx.setdefault("by_name", {}).setdefault(rel.rsplit("/", 1)[-1].lower(), []).append(fid)
    return idx


# ── 指纹解析 ─────────────────────────────────────────────────────────────────

def _resolve_one_file(exp: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """按 **SHA256** 反查图书馆里的 file_id（内容寻址，禁按文件名）。"""
    sha = str(exp.get("sha256") or "").strip().lower()
    out = {
        "gold_relative_path": str(exp.get("relative_path") or ""),
        "gold_entity": str(exp.get("entity") or ""),
        "gold_period": str(exp.get("period") or ""),
        "gold_doc_type": str(exp.get("doc_type") or ""),
        "role": str(exp.get("role") or "primary"),
        "sha256": sha,
        "file_id": "",
        "resolution": "NO_FINGERPRINT",
        "resolution_note": "",
    }
    if not sha:
        out["resolution_note"] = "标准答案未提供材料指纹 ⇒ 无法按内容比对（不得按文件名认定）"
        return out
    hits = sorted(index["by_sha"].get(sha, []))
    if len(hits) == 1:
        out["file_id"] = hits[0]
        out["resolution"] = "RESOLVED"
        out["resolution_note"] = "按 SHA256 内容指纹唯一命中图书馆材料"
        return out
    if len(hits) > 1:
        out["file_id"] = ""
        out["resolution"] = "AMBIGUOUS_CONTENT"
        out["resolution_note"] = (f"同一内容指纹命中 {len(hits)} 份图书馆材料（{', '.join(hits)}）"
                                  "⇒ 内容寻址无法唯一定位 ⇒ 需人工指定")
        return out
    out["resolution"] = "MISSING_IN_LIBRARY"
    out["resolution_note"] = ("标准答案材料的内容指纹在当前图书馆快照中找不到"
                              "⇒ 该份在库里不存在（或已被替换）⇒ 不得当成「答案正确」")
    return out


def resolve_gold_files(manifest: dict[str, Any],
                       index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """把标准答案包逐条解析到图书馆的 ``file_id``（内容寻址）。

    返回::

        {"gold_pack_id": ..., "items": [{obligation_id, expected_verdict,
                                          expected_files: [{...resolution...}],
                                          resolved_file_ids: [...],
                                          resolution_state: ...}],
         "summary": {...}}
    """
    items_out: list[dict[str, Any]] = []
    total_files = resolved = missing = ambiguous = nofp = 0
    for it in manifest.get("items") or []:
        oid = str(it.get("obligation_id"))
        exp_files = it.get("expected_files") or []
        files_out = [_resolve_one_file(f, index) for f in exp_files]
        total_files += len(files_out)
        for f in files_out:
            if f["resolution"] == "RESOLVED":
                resolved += 1
            elif f["resolution"] == "MISSING_IN_LIBRARY":
                missing += 1
            elif f["resolution"] == "AMBIGUOUS_CONTENT":
                ambiguous += 1
            else:
                nofp += 1
        ids = [f["file_id"] for f in files_out if f["resolution"] == "RESOLVED"]
        if not exp_files:
            state = "NO_EXPECTED_FILES"
        elif len(ids) == len(exp_files):
            state = "RESOLVED"
        elif ambiguous:
            state = "AMBIGUOUS_CONTENT"
        elif missing:
            state = "MISSING_IN_LIBRARY"
        else:
            state = "PARTIAL_RESOLVED"
        items_out.append({
            "obligation_id": oid,
            "item_no": str(it.get("item_no") or ""),
            "expected_verdict": str(it.get("expected_verdict") or ""),
            "expected_files": files_out,
            "resolved_file_ids": ids,
            "resolution_state": state,
            "note": str(it.get("note") or ""),
        })
    return {
        "gold_pack_id": str(manifest.get("gold_pack_id") or ""),
        "exam_id": str(manifest.get("exam_id") or ""),
        "items": items_out,
        "summary": {
            "obligations": len(items_out),
            "expected_files": total_files,
            "resolved": resolved,
            "missing_in_library": missing,
            "ambiguous_content": ambiguous,
            "no_fingerprint": nofp,
        },
    }


# ── 与考卷 / 图书馆的对应关系 ─────────────────────────────────────────────────

def check_correspondence(manifest: dict[str, Any],
                          resolved: dict[str, Any],
                          *,
                          checklist_sha256: str | None = None,
                          library_fingerprint: str | None = None) -> dict[str, Any]:
    """核「考卷 / 标准答案 / 图书馆」三者是否对应同一场考试。

    冲突**不静默**：命���即报 ``BROKEN`` 并写清差在哪一侧。
    """
    problems: list[str] = []
    m_check = (manifest.get("checklist") or {}) if isinstance(manifest.get("checklist"), dict) else {}
    m_lib = (manifest.get("library") or {}) if isinstance(manifest.get("library"), dict) else {}

    if checklist_sha256:
        want = str(m_check.get("sha256") or "").strip().lower()
        if want and want != str(checklist_sha256).strip().lower():
            problems.append(f"CHECKLIST_FINGERPRINT_MISMATCH:标准答案记 {want[:16]}…，本次考卷 {str(checklist_sha256)[:16]}…")
    if library_fingerprint:
        want = str(m_lib.get("fingerprint") or "").strip().lower()
        if want and want != str(library_fingerprint).strip().lower():
            problems.append(f"LIBRARY_FINGERPRINT_MISMATCH:标准答案记 {want[:16]}…，本次图书馆 {str(library_fingerprint)[:16]}…")

    s = resolved.get("summary") or {}
    if s.get("missing_in_library"):
        problems.append(f"GOLD_FILES_MISSING_IN_LIBRARY:{s['missing_in_library']}")
    if s.get("ambiguous_content"):
        problems.append(f"GOLD_FILES_AMBIGUOUS_CONTENT:{s['ambiguous_content']}")
    if s.get("no_fingerprint"):
        problems.append(f"GOLD_FILES_WITHOUT_FINGERPRINT:{s['no_fingerprint']}")
    # ★★ P0-1（#108 实测 · 2026-10-30）：**「Gold 在」≠「Gold 有基准」**。
    #   实测：标准答案清单里的 `expected_files` 全为空 ⇒ 解析统计 `expected_files=0`
    #   ⇒ 上面三条一条都不触发 ⇒ 对应关系判 `CONFIRMED` ⇒ 预检拼出
    #   `READY_FOR_FORMAL_SCORING` ⇒ **没有一题可对答案，却宣布可正式评分**。
    #   ⇒ 「一条期望文件都没有」是**阻塞事实**：既没有基准可比，也就没有分母。
    #   ⇒ 口径：**不删 Gold、不改 Gold**；只如实说「这份 Gold 没有可比的基准」。
    if not s.get("expected_files"):
        problems.append("GOLD_NO_EXPECTED_FILES:标准答案清单没有任何期望文件"
                        "⇒ 没有可比的基准 ⇒ 不具备正式评分条件（分母为 0）")
    if not s.get("obligations"):
        problems.append("GOLD_NO_OBLIGATIONS:标准答案清单没有任何义务条目 ⇒ 无可评分对象")

    return {
        "state": "BROKEN" if problems else "CONFIRMED",
        "problems": problems,
        "checklist_fingerprint_declared": str(m_check.get("sha256") or ""),
        "library_fingerprint_declared": str(m_lib.get("fingerprint") or ""),
    }


def missing_confirmations(manifest: dict[str, Any] | list[dict[str, Any]] | None) -> list[str]:
    """缺人工确认（``confirmed_by`` / ``confirmed_at``）的义务 id。

    ★ 口径**沿用** ``dd_v1_score_service.missing_confirmations``（**逐条**确认，
      缺一 ⇒ NOT_SCORABLE，不是「空值当已确认」）；
    ★ 增补一条：**清单级**的 ``confirmed_by`` / ``confirmed_at`` 可作为
      **条目级未单独标注时的默认值**（人工一次性签收整包的情形），
      但**条目级显式写了别的值时以条目级为准**。
    """
    if isinstance(manifest, dict):
        items = manifest.get("items") or []
        fallback_by = str(manifest.get("confirmed_by") or "")
        fallback_at = str(manifest.get("confirmed_at") or "")
    else:
        items = manifest or []
        fallback_by = fallback_at = ""
    out: list[str] = []
    for g in items:
        oid = str(g.get("obligation_id") or "<no-obligation-id>")
        by = str(g.get("confirmed_by") or fallback_by or "").strip()
        at = str(g.get("confirmed_at") or fallback_at or "").strip()
        if not by or not at:
            out.append(oid)
    return out


def gold_state(manifest: dict[str, Any] | None,
               correspondence: dict[str, Any] | None,
               *, provided: bool = True) -> tuple[str, str]:
    """标准答案的**状态**与**人话原因**（严格区分「未接入」与「不存在」）。"""
    if not provided or manifest is None:
        return ("NOT_PROVIDED",
                "业务方尚未提供历史人工交付包（#74 交办已暂停）⇒ 未接入评分基准；"
                "这不等于「历史上没有标准答案」")
    corr = correspondence or {}
    if corr.get("state") == "BROKEN":
        kind = blocking_kind(corr)
        _tail = ("（★ **部分缺口** ⇒ 可**分层评分**：保留全卷分母，只把可评分的部分算出来）"
                 if kind == "GAPS" else
                 ("（★ **硬冲突** ⇒ 不可评分）" if kind == "HARD" else ""))
        return ("BROKEN", "标准答案已提供但与本次考卷/图书馆对不上：" +
                "；".join(corr.get("problems") or ["对应关系未确认"]) + _tail)
    missing = missing_confirmations(manifest)
    if missing:
        return ("NOT_CONFIRMED",
                f"标准答案已接入，但有 {len(missing)} 条缺人工确认（confirmed_by / confirmed_at）"
                "⇒ 不得当已确认（ID：" + ",".join(sorted(missing)[:5]) + "…）")
    return ("FOUND", "标准答案已找到、映射完成、人工已确认 ⇒ 具备正式评分条件")


# ── WP3：Gold 缺口的**逐件**诊断（#108 波总裁定 · 2026-10-30）──────────────
#
# ★ 波总要求：「先列出 11 份缺失、4 份歧义的**逐件清单、原始路径/哈希及对应题号**，
#   排查是否是**路径、文件名、哈希或材料库范围错误**；能在本机安全纠正映射的**直接纠正**，
#   确实缺料的**单列补料清单**。」
# ★ ⇒ 光答「不在库里」**不够** ⇒ 必须给出**分类 ＋ 候选 ＋ 修复动作**。
#
# ★ 分类口径（A–F，与施工令一致）：
#   A  确实缺料        —— 库里既无同内容、也无同路径/同名件
#   B  路径解析错误    —— 库里有**同内容**但路径不同（内容寻址已能命中 ⇒ 实际不该出现）
#   C  文件名匹配错误  —— 库里有**同名**件但内容指纹不同
#   D  哈希/内容识别错 —— 库里同路径件的指纹与 Gold 记的不一致（内容被替换/重新导出）
#   E  主体/期间/范围错 —— 同内容命中，但该材料的**主体/期间**与 Gold 记的不一致
#   F  Gold 清单需人工确认 —— 该条目没有期望文件、或题号挂不上本考卷的义务
# ★ ★ **不删 Gold、不改 Gold**：本函数**只读**，产出的是**待处置清单**。

GAP_CLASSES = ("A_MISSING", "B_PATH_MISMATCH", "C_NAME_MISMATCH",
               "D_FINGERPRINT_MISMATCH", "E_SCOPE_MISMATCH", "F_NEEDS_HUMAN_CONFIRM")

#: ★ **两类阻塞必须分开**（#108 波总裁定 · 2026-10-30「保留全卷分母的分层评分」）：
#: · HARD ＝ **真不可评分**（考卷/图书馆指纹冲突、或根本没有可比基准）⇒ NOT_SCORABLE；
#: · GAPS ＝ **部分缺口**（个别标准答案文件缺料/歧义）⇒ ★ **可分层评分**：
#:   ★ 保留全卷分母，把**可评分**的那部分算出分子分母与得分，缺口逐件列出。
#: ★ ★ 开考**闸门**对两类都拦（不开考）；★ 但**阅卷**对 GAPS **不得**全盘 NOT_SCORABLE
#:   （那会把「11 份缺料」变成「42 题全部不可评」⇒ 违反波总的分层裁定）。
HARD_BLOCK_CODES = ("CHECKLIST_FINGERPRINT_MISMATCH", "LIBRARY_FINGERPRINT_MISMATCH",
                     "GOLD_NO_EXPECTED_FILES", "GOLD_NO_OBLIGATIONS")
GAP_BLOCK_CODES = ("GOLD_FILES_MISSING_IN_LIBRARY", "GOLD_FILES_AMBIGUOUS_CONTENT",
                   "GOLD_FILES_WITHOUT_FINGERPRINT")


def blocking_kind(correspondence: dict[str, Any] | None) -> str:
    """把对应关系的阻塞分档：**HARD**（真不可评分）／**GAPS**（可分层）／``""``（无阻塞）。"""
    codes = {str(p).split(":")[0] for p in ((correspondence or {}).get("problems") or [])}
    if codes & set(HARD_BLOCK_CODES):
        return "HARD"
    if codes & set(GAP_BLOCK_CODES):
        return "GAPS"
    return ""


def _classify_one(resolved: dict[str, Any],
                   index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """给一条「没解析出来」的 Gold 期望文件定类 ＋ 给候选 ＋ 给修复动作。

    ★ 入参是 **``_resolve_one_file`` 的输出**（键名是 ``gold_relative_path``／``sha256``／
      ``gold_entity``／``gold_period``）⇒ ★ **不要**按清单原始键名读（那是另一套形状）。
    """
    gold_path = str(resolved.get("gold_relative_path") or "").strip().replace("\\", "/")
    gold_name = gold_path.rsplit("/", 1)[-1].lower() if gold_path else ""
    gold_sha = str(resolved.get("sha256") or "").strip().lower()
    out: dict[str, Any] = {
        "resolution": str(resolved.get("resolution") or ""),
        "resolution_note": str(resolved.get("resolution_note") or ""),
        "gold_relative_path": gold_path,
        "gold_sha256": gold_sha,
        "gold_entity": str(resolved.get("gold_entity") or ""),
        "gold_period": str(resolved.get("gold_period") or ""),
        "gap_class": "",
        "candidates": [],
        "remedy": "",
    }
    if not gold_sha:
        out["gap_class"] = "F_NEEDS_HUMAN_CONFIRM"
        out["remedy"] = "补 Gold 的内容指纹（sha256）⇒ 不得按文件名认定"
        return out
    by_path = index.get("by_path") or {}
    by_name = index.get("by_name") or {}
    by_id = index.get("by_id") or {}
    # D：同路径、不同内容 ⇒ 内容被替换/重新导出
    same_path = [fid for fid in by_path.get(gold_path.lower(), [])]
    if same_path:
        out["gap_class"] = "D_FINGERPRINT_MISMATCH"
        out["candidates"] = [{
            "file_id": fid, "relative_path": str((by_id.get(fid) or {}).get("relative_path") or ""),
            "sha256": str((by_id.get(fid) or {}).get("sha256") or ""),
            "entity": str((by_id.get(fid) or {}).get("entity") or ""),
            "period": str((by_id.get(fid) or {}).get("period") or ""),
        } for fid in same_path]
        out["remedy"] = "人工核对：库里同路径件的内容指纹与 Gold 记的不一致 ⇒ 是内容被替换，还是 Gold 记错"
        return out
    # C：同名、不同内容
    same_name = [fid for fid in by_name.get(gold_name, [])] if gold_name else []
    if same_name:
        out["gap_class"] = "C_NAME_MISMATCH"
        out["candidates"] = [{
            "file_id": fid, "relative_path": str((by_id.get(fid) or {}).get("relative_path") or ""),
            "sha256": str((by_id.get(fid) or {}).get("sha256") or ""),
            "entity": str((by_id.get(fid) or {}).get("entity") or ""),
            "period": str((by_id.get(fid) or {}).get("period") or ""),
        } for fid in same_name]
        out["remedy"] = "人工核对同名件：内容不同 ⇒ 若确为同一份材料，请由业务方**补正确指纹**（不得由程序猜）"
        return out
    # A：库里既无同内容、也无同路径/同名件
    out["gap_class"] = "A_MISSING"
    out["remedy"] = "**补料**：该份标准答案材料在当前图书馆快照里不存在 ⇒ 单列进补料清单（不得删 Gold）"
    return out


def gold_gap_report(manifest: dict[str, Any],
                    index: dict[str, dict[str, Any]],
                    resolved: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gold 缺口的**逐件**清单（题号 ＋ 原始路径 ＋ 哈希 ＋ 分类 ＋ 候选 ＋ 修复动作）。

    ★ 输入：Gold 清单 ＋ 图书馆索引（``by_id``／``by_sha``／``by_path``／``by_name``）。
    ★ 输出：**每条没解析出来的期望文件**一行；★ **已解析的不列**（不制造噪声）。
    ★ ★ **只读**：不写 Gold、不改 Gold、不补料、不猜。
    """
    resolved = resolved if resolved is not None else resolve_gold_files(manifest, index)
    gaps: list[dict[str, Any]] = []
    by_class: dict[str, int] = {}
    for it in resolved.get("items") or []:
        oid = str(it.get("obligation_id") or "")
        item_no = str(it.get("item_no") or "")
        for exp in it.get("expected_files") or []:
            r = str(exp.get("resolution") or "")
            if r == "RESOLVED":
                continue
            g = _classify_one(exp, index)
            g["obligation_id"] = oid
            g["item_no"] = item_no
            # ★ 题号挂不上本考卷的义务 ⇒ F（Gold 清单侧的问题，不是缺料）
            if not item_no:
                g["gap_class"] = "F_NEEDS_HUMAN_CONFIRM"
                g["remedy"] = "Gold 条目**缺题号** ⇒ 无法挂到本考卷的义务 ⇒ 人工补题号"
            gaps.append(g)
            by_class[g["gap_class"]] = by_class.get(g["gap_class"], 0) + 1
    # ★ 条目级：一条期望文件都没有 ⇒ 也是 F（不是「答对了」）
    for it in resolved.get("items") or []:
        if not (it.get("expected_files") or []):
            gaps.append({
                "obligation_id": str(it.get("obligation_id") or ""),
                "item_no": str(it.get("item_no") or ""),
                "resolution": "NO_EXPECTED_FILES",
                "resolution_note": "该义务在 Gold 清单里没有期望文件 ⇒ 无可比基准",
                "gold_relative_path": "", "gold_sha256": "",
                "gold_entity": "", "gold_period": "",
                "gap_class": "F_NEEDS_HUMAN_CONFIRM",
                "candidates": [],
                "remedy": "人工补该义务的期望文件（Gold 侧）⇒ **不得**因此删义务",
            })
            by_class["F_NEEDS_HUMAN_CONFIRM"] = by_class.get("F_NEEDS_HUMAN_CONFIRM", 0) + 1
    return {
        "schema_version": "dd_v1_gold_gap_report.v1",
        "gold_pack_id": str(manifest.get("gold_pack_id") or ""),
        "exam_id": str(manifest.get("exam_id") or ""),
        "counts": {
            "obligations": len(resolved.get("items") or []),
            "expected_files": int((resolved.get("summary") or {}).get("expected_files") or 0),
            "resolved": int((resolved.get("summary") or {}).get("resolved") or 0),
            "gaps": len(gaps),
            "by_class": by_class,
        },
        "gaps": gaps,
        "note": ("逐件待处置清单：★ **不删 Gold、不改 Gold**；"
                 "A/B/C/D/E 由人工核对后**在本地纠正映射**，A（确实缺料）单列进补料清单"),
    }


# ── 隔离闸 ───────────────────────────────────────────────────────────────────

def assert_gold_isolated(gold_path: Path, *forbidden_dirs: Path) -> None:
    """Gold 不得落在材料目录 / 运行目录 / Git 工作树内。

    **复用**既有 ``dd_v1_score_service.assert_gold_isolated``（含 Git 工作树检测），
    语义不改、只加一层别名，便于本模块独立使用。
    """
    sc.assert_gold_isolated(Path(gold_path), *forbidden_dirs)


def gold_fingerprint(manifest: dict[str, Any]) -> str:
    """标准答案包的**内容指纹**（清单自身，不含真实材料字节）。

    用于「同一场考试用的是同一份标准答案」的自证；**不含**任何路径或文件名。

    ★★ **MINOR-2 修复**（独立 Reviewer 第 3 轮）：此前指纹把 ``obligation_id``
      （**uuid4，每次建库都变**）一起 hash ⇒ **同一份 Gold 每次指纹都不同**
      ⇒ 这个字段**自证不了**「用的是同一份标准答案」（假信号）。
      ⇒ 现在改用**内容派生的稳定键** ``obligation_key``（无 key 时退回 ``obligation_id``）。
    """
    h = hashlib.sha256()
    h.update(str(manifest.get("gold_pack_id") or "").encode("utf-8"))
    h.update(b"\x1f")
    for it in sorted(manifest.get("items") or [],
                      key=lambda x: str(x.get("obligation_key") or x.get("obligation_id"))):
        # ★ **稳定键优先**（内容派生）⇒ 同一份 Gold ⇒ 同一指纹
        h.update(str(it.get("obligation_key") or it.get("obligation_id") or "").encode("utf-8"))
        h.update(b"\x1f")
        h.update(str(it.get("expected_verdict") or "").encode("utf-8"))
        h.update(b"\x1f")
        for f in sorted(it.get("expected_files") or [], key=lambda x: str(x.get("sha256"))):
            h.update(str(f.get("sha256") or "").encode("utf-8"))
            h.update(b"\x1f")
    return h.hexdigest()
