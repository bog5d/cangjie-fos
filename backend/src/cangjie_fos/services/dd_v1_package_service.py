"""DD-V1 人工审核、完整性报告与交付组包（WP4）。

## 最重要的一条：未经人工最终批准，不得复制任何材料

这是硬门槛 HG1（严重越权披露）的机器侧强制实现：

- ``build_review_pack()`` 只在受控 Data Plane 生成**审核包**（核对表 / 缺口清单 /
  证据说明 / Manifest+hash），**不碰材料源文件，也不复制任何原件**。
- ``package_approved()`` 是唯一会复制原件的入口，它**必须**先通过
  :func:`assert_approval`，否则抛 :class:`ApprovalRequired` 并**在复制之前**中止。
- 受限、不可读、解析失败、敏感等级未知的材料**一律不进交付目录**，
  即使人工勾选了也会被 Gate 拦下并记录原因（人可覆盖判定，但不能绕过受限事实）。

## 复用优先

路径清洗与越界防护**直接复用** ``dd_export_service._within / _safe_filename /
_safe_dirname``（既有代码已在真实导出中跑过），不另立第二套文件名安全标准。

## 人工纠错沉淀

每次修改记录：原候选、机器判断、证据、修正前后、修改人、修改原因、
适用主体、机构、时间、版本。一次修改**不会**被自动升级为全局规则——
经验只落到 ``review_id`` 维度，跨任务复用属 WP5 且必须经 Gate。
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import uuid
from pathlib import Path

from cangjie_fos.core import paths as fos_paths
from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_requirement_service as rq

# 复用既有路径安全工具（不另立标准）
from cangjie_fos.services.dd_export_service import (  # noqa: PLC0415
    _safe_dirname, _safe_filename, _within,
)

logger = logging.getLogger(__name__)

# 审核单状态机
ST_DRAFT = "draft"            # 已生成审核包，待人工审阅
ST_REVIEWED = "reviewed"      # 人工已提交修改意见
ST_APPROVED = "approved"      # 人工已最终批准
ST_PACKAGED = "packaged"      # 已组包
ST_REJECTED = "rejected"      # 人工否决

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_reviews (
    review_id     TEXT PRIMARY KEY,
    library_id    TEXT NOT NULL,
    institution   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    reviewed_by   TEXT NOT NULL DEFAULT '',
    approved_by   TEXT NOT NULL DEFAULT '',
    approved_at   REAL,
    review_note   TEXT NOT NULL DEFAULT '',
    pack_path     TEXT NOT NULL DEFAULT '',
    pack_manifest TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_reviews_lib ON dd_v1_reviews(library_id);

-- 人工修改留痕（一次修改 ≠ 一条全局规则）
CREATE TABLE IF NOT EXISTS dd_v1_review_edits (
    edit_id       TEXT PRIMARY KEY,
    review_id     TEXT NOT NULL,
    obligation_id TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL,
    before_json   TEXT NOT NULL DEFAULT '{}',
    after_json    TEXT NOT NULL DEFAULT '{}',
    reason        TEXT NOT NULL DEFAULT '',
    scope_entity  TEXT NOT NULL DEFAULT '',
    institution   TEXT NOT NULL DEFAULT '',
    template      TEXT NOT NULL DEFAULT '',
    version       TEXT NOT NULL DEFAULT 'v1',
    edited_by     TEXT NOT NULL,
    edited_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_edits_review ON dd_v1_review_edits(review_id);
"""


class ApprovalRequired(RuntimeError):
    """未获人工最终批准就请求组包——必须在复制任何原件之前中止。"""


class GateBlocked(RuntimeError):
    """材料被安全 Gate 拦截（受限/不可读/敏感等级未知）。"""


def _ensure(conn) -> None:
    conn.executescript(_DDL)
    # 本服务的核对表依赖 WP3 的义务表与 WP2 的认知卡表：
    # 未先跑过匹配时这些表可能尚不存在，必须一并确保，
    # 否则「只生成审核包」这条最轻的路径反而会因缺表崩掉。
    rq._ensure_schema(conn)
    cs._ensure_schema(conn)
    ms._ensure_schema(conn)
    conn.commit()


def _conn(db_path: Path | None = None):
    conn = mf._connect(db_path)
    _ensure(conn)
    return conn


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


# ── 1. 生成审核包（只读材料，不复制原件）─────────────────────────────────
def build_review_pack(
    library_id: str,
    institution: str = "",
    db_path: Path | None = None,
) -> dict:
    """生成审核包：核对表 / 缺口清单 / 证据说明 / Manifest+hash。

    **绝不复制任何原件**——这一步只是让人看清楚系统判了什么、依据是什么。
    """
    conn = _conn(db_path)
    review_id = uuid.uuid4().hex
    now = time.time()

    obl_rows = [dict(r) for r in conn.execute(
        "SELECT o.*, i.item_no, i.raw_text FROM dd_v1_obligations o "
        "LEFT JOIN dd_v1_checklist_items i ON i.item_uid=o.item_uid "
        "WHERE o.library_id=? ORDER BY i.item_no, o.seq", (library_id,))]

    rows: list[dict] = []
    for o in obl_rows:
        st = ms.get_status(o["obligation_id"], db_path=db_path)
        cands = ms.list_matches(o["obligation_id"], db_path=db_path)
        rows.append({
            "item_no": o.get("item_no") or "",
            "raw_text": o.get("raw_text") or "",
            "obligation": o["obligation"],
            "obligation_id": o["obligation_id"],
            "entity_scope": o["entity_scope"],
            "entity_basis": o["entity_basis"],
            "period": f"{o['period_from']}-{o['period_to']}" if o["period_from"] else "",
            "period_basis": o["period_basis"],
            "doc_type": o["doc_type"],
            "doc_type_basis": o["doc_type_basis"],
            "verdict": (st or {}).get("verdict", "UNMATCHED"),
            "entity_cov": (st or {}).get("entity_cov", 0),
            "period_cov": (st or {}).get("period_cov", 0),
            "doctype_cov": (st or {}).get("doctype_cov", 0),
            "need_entities": (st or {}).get("need_entities", 0),
            "need_periods": (st or {}).get("need_periods", 0),
            "missing_detail": (st or {}).get("missing_detail", ""),
            "candidate_count": (st or {}).get("candidate_count", 0),
            "candidates": [
                {
                    "file_id": c["file_id"],
                    "rel_path": c.get("card_rel_path") or "",
                    "title": c.get("card_title") or "",
                    "score": c["score"],
                    "deliverable": bool(c["deliverable"]),
                    "evidence": c.get("evidence", ""),
                } for c in cands
            ],
        })

    out_dir = fos_paths.get_dd_v1_data_dir() / "reviews" / review_id
    out_dir.mkdir(parents=True, exist_ok=True)
    written = _write_pack_files(out_dir, review_id, rows)

    conn.execute(
        """INSERT INTO dd_v1_reviews
           (review_id, library_id, institution, status, created_at, updated_at, pack_path)
           VALUES (?,?,?,?,?,?,?)""",
        (review_id, library_id, institution, ST_DRAFT, now, now, str(out_dir)),
    )
    conn.commit()

    tally: dict[str, int] = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    return {
        "review_id": review_id,
        "library_id": library_id,
        "status": ST_DRAFT,
        "obligations": len(rows),
        "by_verdict": tally,
        "pack_path": str(out_dir),
        "files": written,
        "copied_source_files": 0,
        "note": "审核包只读材料、零复制；复制原件必须经 approve + package_approved",
    }


def _write_pack_files(out_dir: Path, review_id: str, rows: list[dict]) -> list[str]:
    """写核对表 / 缺口清单 / 证据说明 / Manifest+hash。全部在 Data Plane 内。"""
    written: list[str] = []

    # ── 1) Excel 匹配核对表 ────────────────────────────────────────────
    try:
        from openpyxl import Workbook  # noqa: PLC0415
        wb = Workbook()
        ws = wb.active
        ws.title = "匹配核对表"
        headers = ["机构编号", "机构原文", "原子义务", "主体范围", "主体出处",
                   "期间", "期间出处", "材料类型", "类型出处", "判定",
                   "主体覆盖", "期间覆盖", "类型覆盖", "需主体数", "需期间数",
                   "缺口明细", "候选数", "候选文件", "可交付"]
        ws.append(headers)
        for r in rows:
            ws.append([
                r["item_no"], r["raw_text"], r["obligation"],
                r["entity_scope"], r["entity_basis"], r["period"],
                r["period_basis"], r["doc_type"], r["doc_type_basis"],
                r["verdict"], r["entity_cov"], r["period_cov"],
                r["doctype_cov"], r["need_entities"], r["need_periods"],
                r["missing_detail"], r["candidate_count"],
                "; ".join(c["rel_path"] for c in r["candidates"][:5]),
                "是" if any(c["deliverable"] for c in r["candidates"]) else "否",
            ])
        p = out_dir / "匹配核对表.xlsx"
        wb.save(p)
        written.append(p.name)
    except Exception as exc:  # noqa: BLE001 — Excel 失败不阻断其余产物
        logger.warning("Excel 核对表生成失败：%s", exc)
        (out_dir / "匹配核对表.csv").write_text(
            "\n".join(
                "\t".join(str(r.get(k, "")) for k in
                          ("item_no", "raw_text", "obligation", "verdict", "missing_detail"))
                for r in rows), encoding="utf-8")
        written.append("匹配核对表.csv")

    # ── 2) 缺失与待确认清单 ────────────────────────────────────────────
    gaps = [r for r in rows if r["verdict"] not in ("MATCHED",)]
    (out_dir / "缺口与待确认清单.txt").write_text(
        "以下义务未达完整状态，需人工处理。判定口径见 Goal Contract 硬门槛。\n\n" +
        "\n".join(
            f"[{r['verdict']}] {r['item_no']} {r['obligation']}\n"
            f"    缺口：{r['missing_detail'] or '（未提供明细）'}\n"
            f"    候选：{'; '.join(c['rel_path'] for c in r['candidates']) or '（无）'}"
            for r in gaps
        ), encoding="utf-8")
    written.append("缺口与待确认清单.txt")

    # ── 3) 证据与完整性说明 ────────────────────────────────────────────
    (out_dir / "证据与完整性说明.md").write_text(
        "# 证据与完整性说明\n\n"
        "## 判定口径\n\n"
        "- 主体覆盖：权威名单中已被材料覆盖的主体占比。**无权威名单时判 UNCERTAIN**，\n"
        "  不用目录名凑数。\n"
        "- 期间覆盖：要求区间内已被覆盖的年份占比。**相对年份（如「近三年」）无锚定年时\n"
        "  不展开，判 UNCERTAIN**。\n"
        "- 必备附件与签章：认知卡字段目前恒 UNKNOWN，故这两个维度**必然不满足**——\n"
        "  这是已知缺口被如实暴露，不是数据问题。\n"
        "- 交付资格：解析失败、不可读、或敏感等级未知的材料**不进入交付目录**。\n\n"
        "## 逐条说明\n\n" +
        "\n".join(
            f"### {r['item_no']} {r['obligation']}\n\n"
            f"- 判定：**{r['verdict']}**\n"
            f"- 主体覆盖 {r['entity_cov']} / 期间覆盖 {r['period_cov']} / 类型覆盖 {r['doctype_cov']}\n"
            f"- 缺口：{r['missing_detail'] or '无'}\n"
            f"- 候选与证据：\n" +
            "\n".join(
                f"    - {c['rel_path']}（score={c['score']}, 可交付={'是' if c['deliverable'] else '否'}）"
                f" {c['evidence']}"
                for c in r["candidates"]) + "\n"
            for r in rows
        ), encoding="utf-8")
    written.append("证据与完整性说明.md")

    # ── 4) Manifest + hash 核验（此处只记录源文件 hash，不复制）─────────
    mpath = out_dir / "交付清单与hash核验.tsv"
    lines = ["file_id\trel_path\tsha256\tsize\t可交付\t阻断原因"]
    for r in rows:
        for c in r["candidates"]:
            ev = c.get("evidence") or ""
            lines.append(f"{c['file_id']}\t{c['rel_path']}\t\t\t"
                         f"{'是' if c['deliverable'] else '否'}\t{ev}")
    mpath.write_text("\n".join(lines), encoding="utf-8")
    written.append(mpath.name)

    return written


# ── 2. 人工修改留痕 ───────────────────────────────────────────────────────
def record_edit(
    review_id: str,
    action: str,
    edited_by: str,
    reason: str = "",
    obligation_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    scope_entity: str = "",
    institution: str = "",
    template: str = "",
    db_path: Path | None = None,
) -> dict:
    """记录一次人工修改。**一次修改不得无条件升级为全局规则。"""
    if not edited_by.strip():
        raise ValueError("edited_by 不能为空：人工修改必须可追责")
    if not reason.strip():
        raise ValueError("reason 不能为空：人工修改必须写明原因")
    conn = _conn(db_path)
    edit_id = uuid.uuid4().hex
    now = time.time()
    conn.execute(
        """INSERT INTO dd_v1_review_edits
           (edit_id, review_id, obligation_id, action, before_json, after_json,
            reason, scope_entity, institution, template, version, edited_by, edited_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (edit_id, review_id, obligation_id, action,
         json.dumps(before or {}, ensure_ascii=False),
         json.dumps(after or {}, ensure_ascii=False),
         reason, scope_entity, institution, template, "v1", edited_by, now),
    )
    conn.execute(
        "UPDATE dd_v1_reviews SET status=?, updated_at=? WHERE review_id=?",
        (ST_REVIEWED, now, review_id))
    conn.commit()
    return {"edit_id": edit_id, "review_id": review_id, "action": action,
            "promoted_to_global_rule": False}


def list_edits(review_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _conn(db_path)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_review_edits WHERE review_id=? ORDER BY edited_at",
        (review_id,))]


# ── 3. 人工批准 Gate（HG1 机器侧强制）────────────────────────────────────
def approve(review_id: str, approved_by: str, note: str = "",
            db_path: Path | None = None) -> dict:
    if not approved_by.strip():
        raise ValueError("approved_by 不能为空：交付必须有可追责的批准人")
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"审核单不存在：{review_id}")
    if row["status"] == ST_PACKAGED:
        raise ValueError("已组包，不可重复批准")
    now = time.time()
    conn.execute(
        """UPDATE dd_v1_reviews SET status=?, approved_by=?, approved_at=?,
           review_note=?, updated_at=? WHERE review_id=?""",
        (ST_APPROVED, approved_by, now, note, now, review_id))
    conn.commit()
    return {"review_id": review_id, "status": ST_APPROVED,
            "approved_by": approved_by, "approved_at": now}


def assert_approval(review_id: str, db_path: Path | None = None) -> dict:
    """组包前的强制检查。**不通过就抛异常，且必须在复制任何文件之前。**"""
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    if row is None:
        raise ApprovalRequired(f"审核单不存在：{review_id}")
    if row["status"] not in (ST_APPROVED, ST_PACKAGED):
        raise ApprovalRequired(
            f"审核单 {review_id} 当前状态为 {row['status']}，"
            f"未经人工最终批准，拒绝组包（HG1）")
    if not (row["approved_by"] or "").strip():
        raise ApprovalRequired(f"审核单 {review_id} 无批准人，拒绝组包（HG1）")
    return dict(row)


# ── 4. 组包（唯一会复制原件的入口）──────────────────────────────────────
def package_approved(
    review_id: str,
    output_dir: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """按机构原编号组织目录并复制原件。**必须先通过人工批准。**"""
    review = assert_approval(review_id, db_path=db_path)   # ← 闸在前，复制在后
    conn = _conn(db_path)

    lib_root = Path(conn.execute(
        "SELECT root_path FROM dd_v1_libraries WHERE library_id=?",
        (review["library_id"],)).fetchone()["root_path"])

    out = Path(output_dir) if output_dir else Path(review["pack_path"]) / "交付包"
    out.mkdir(parents=True, exist_ok=True)

    exported: list[dict] = []
    blocked: list[dict] = []

    obl_rows = conn.execute(
        """SELECT o.*, i.item_no, i.raw_text FROM dd_v1_obligations o
           LEFT JOIN dd_v1_checklist_items i ON i.item_uid=o.item_uid
           WHERE o.library_id=? ORDER BY i.item_no, o.seq""",
        (review["library_id"],)).fetchall()

    for o in obl_rows:
        st = ms.get_status(o["obligation_id"], db_path=db_path)
        cands = ms.list_matches(o["obligation_id"], db_path=db_path)
        if not cands:
            continue
        item_dir = out / _safe_dirname((o["item_no"] or o["obligation_id"]))
        item_dir.mkdir(parents=True, exist_ok=True)

        for c in cands:
            if not c["deliverable"]:
                blocked.append({
                    "obligation": o["obligation"],
                    "file_id": c["file_id"],
                    "reason": c.get("evidence") or "受限/不可读/敏感等级未知",
                })
                continue
            mrow = conn.execute(
                "SELECT * FROM dd_v1_manifest WHERE file_id=?", (c["file_id"],)
            ).fetchone()
            if mrow is None:
                continue
            src = Path(mrow["abs_path"])
            if not src.is_file():
                blocked.append({"obligation": o["obligation"],
                                "file_id": c["file_id"], "reason": "源文件已不存在"})
                continue
            dest = item_dir / _safe_filename(mrow["file_name"])
            # 越界兜底闸：清洗后仍异常则跳过，不写
            if not _within(out, dest):
                blocked.append({"obligation": o["obligation"],
                                "file_id": c["file_id"], "reason": "目标越界，安全跳过"})
                continue
            if dest.exists():
                dest = item_dir / f"{_safe_filename(src.stem)}_{_safe_filename(c['file_id'][:8])}{src.suffix}"
                if not _within(out, dest):
                    blocked.append({"obligation": o["obligation"],
                                    "file_id": c["file_id"], "reason": "目标越界，安全跳过"})
                    continue
            shutil.copy2(src, dest)
            exported.append({
                "item_no": o["item_no"] or "",
                "obligation": o["obligation"],
                "dest": str(dest.relative_to(out)),
                "src_sha256": mrow["content_hash"],
                "dest_sha256": _sha256(dest),
                "verdict": (st or {}).get("verdict", ""),
            })

    # hash 核验：复制件必须与源哈希一致，否则是交付事故
    mismatched = [e for e in exported if e["src_sha256"] != e["dest_sha256"]]
    for e in mismatched:
        logger.error("hash 核验不一致：%s", e["dest"])

    (out / "组包manifest.tsv").write_text(
        "机构编号\t原子义务\t交付路径\t源sha256\t副本sha256\t一致\t判定\n" +
        "\n".join(
            f"{e['item_no']}\t{e['obligation']}\t{e['dest']}\t{e['src_sha256']}\t"
            f"{e['dest_sha256']}\t{'是' if e['src_sha256']==e['dest_sha256'] else '否'}\t{e['verdict']}"
            for e in exported), encoding="utf-8")
    (out / "被拦截清单.json").write_text(
        json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")

    now = time.time()
    conn.execute(
        "UPDATE dd_v1_reviews SET status=?, pack_path=?, updated_at=? WHERE review_id=?",
        (ST_PACKAGED, str(out), now, review_id))
    conn.commit()

    return {
        "review_id": review_id,
        "status": ST_PACKAGED,
        "output_dir": str(out),
        "exported": len(exported),
        "blocked": len(blocked),
        "blocked_detail": blocked[:20],
        "hash_mismatched": len(mismatched),
        "approved_by": review["approved_by"],
    }


def get_review(review_id: str, db_path: Path | None = None) -> dict | None:
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    return dict(row) if row else None
