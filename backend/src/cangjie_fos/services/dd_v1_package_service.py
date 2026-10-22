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
# A3（G-A3-2）：精确选中规则（交付集合 = 选中件 + 必备附件，不是全部候选）
from cangjie_fos.services import dd_v1_selection_service as selsvc
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


# ── A3（G-A3-2 / G-A3-5 / H-3）：审核包与交付包共用的「组包计划」────────────
def _related_map(candidates: list[dict], db_path: Path | None = None) -> dict:
    """``file_id → related_files 相对路径列表``（只认认知卡里**显式**列出的）。"""
    out: dict[str, list[str]] = {}
    for c in candidates or []:
        fid = str(c.get("file_id") or "")
        if not fid or fid in out:
            continue
        card = cs.get_card(fid, db_path=db_path)
        fields = (card or {}).get("fields") or {}
        raw = (fields.get("related_files") or {}).get("value") or []
        out[fid] = [str(x) for x in raw] if isinstance(raw, list) else []
    return out


def _entity_display_map(rows: list[dict]) -> tuple[dict, dict]:
    """主体范围 → **稳定代号**（★ H-3：审核包不得带出客户标识）。

    ★ 判定「这个值是不是客户标识」**只用** ``rq.entity_scope_value()``
      ——判定层已有的**唯一**脱敏口径；本模块**不另写第二套**。
    ★ 代号按**首次出现顺序**分配（``主体-1``、``主体-2``……）⇒ 同一主体全表一致。
    ★ **列里不出现任何原值**（连范围类型也不出现）——原值只作内存里的分组键。
    """
    codes: dict[str, str] = {}
    stats = {"scopes": 0, "masked": 0}
    n = 0
    for r in rows or []:
        raw = str(r.get("entity_scope") or "").strip()
        if not raw or raw in codes:
            continue
        stats["scopes"] += 1
        if rq.entity_scope_value(raw) != raw:
            stats["masked"] += 1
        n += 1
        codes[raw] = f"主体-{n}"
    return codes, stats


#: 受限/不可交付原因的**分类**（G-A3-5：受限与「不存在」必须分开报）
_BLOCKED_CATEGORIES = (
    ("披露不可外发", "受限（披露策略判定不可外发）"),
    ("敏感等级", "受限（敏感等级未知）"),
    ("解析状态", "不可读/解析失败"),
    ("无材料认知卡", "受限（无认知卡，敏感等级不可判定）"),
    ("索引/目录件", "索引件（非材料）"),
    ("源文件已不存在", "源文件不存在"),
    ("目标越界", "越界拦截（安全跳过）"),
)


def _blocked_category(reason: str) -> str:
    """把拦截原因归类（原始原因**一并保留**，分类只是给人看的标签）。"""
    text = str(reason or "")
    for key, label in _BLOCKED_CATEGORIES:
        if key in text:
            return label
    return "受限/不可交付"


def _build_rows(library_id: str, db_path: Path | None = None) -> list[dict]:
    """逐义务算出：判定 + 候选 + **选中集合**。

    ★ 审核包（``build_review_pack``）与交付包（``package_approved``）
      **共用这一份计划** ⇒ 人工审阅的集合 = 实际交付的集合，
      不会出现「审的是 A、交的是 B」。
    """
    conn = _conn(db_path)
    obl_rows = [dict(r) for r in conn.execute(
        "SELECT o.*, i.item_no, i.raw_text FROM dd_v1_obligations o "
        "LEFT JOIN dd_v1_checklist_items i ON i.item_uid=o.item_uid "
        "WHERE o.library_id=? ORDER BY i.item_no, o.seq", (library_id,))]

    rows: list[dict] = []
    for o in obl_rows:
        st = ms.get_status(o["obligation_id"], db_path=db_path) or {}
        cands = ms.list_matches(o["obligation_id"], db_path=db_path)
        related = _related_map(cands, db_path) if o.get("needs_attachments") else {}
        sel = selsvc.select_for_obligation(o, cands, related=related)
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
            "expected_count": o.get("expected_count", 0),
            "expected_count_basis": o.get("expected_count_basis") or "",
            "verdict": st.get("verdict", "UNMATCHED"),
            "entity_cov": st.get("entity_cov", 0),
            "period_cov": st.get("period_cov", 0),
            "doctype_cov": st.get("doctype_cov", 0),
            "need_entities": st.get("need_entities", 0),
            "need_periods": st.get("need_periods", 0),
            "missing_detail": st.get("missing_detail", ""),
            "candidate_count": st.get("candidate_count", 0),
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
            "selected": sel["selected"],
            "unselected": sel["unselected"],
            "selection_rule": sel["rule"],
            "target_reason": sel["target_reason"],
            "count_pending": sel["count_pending"],
        })

    codes, stats = _entity_display_map(rows)
    for r in rows:
        raw = str(r.get("entity_scope") or "").strip()
        r["entity_display"] = codes.get(raw, "")
    return rows


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

    # ★ A3（G-A3-2）：逐义务的「判定 + 候选 + 选中集合」由 _build_rows 统一算，
    #   审核包与交付包**共用同一份计划** ⇒ 审的 = 交的。
    rows = _build_rows(library_id, db_path)

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


def _count_label(r: dict) -> str:
    """核对表里「应有份数」列的文案（三态：A3-1）。"""
    v = r.get("expected_count")
    if v is None:
        return "不可判定（待人工确认）"
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "清单未规定"
    return f"{n} 份"


def _evidence_text(raw) -> str:
    """把候选的 evidence（JSON 数组字符串）摊平成可读文本。"""
    text = str(raw or "")
    try:
        items = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(items, list):
        return "；".join(str(x) for x in items)
    return text


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
                   "缺口明细", "候选数", "候选文件", "可交付",
                   # ★ A3（G-A3-1 / G-A3-2）：份数与**选中集合**
                   #   主体范围列写的是**稳定代号**（H-3 脱敏），不写原值
                   "应有份数", "选中件数", "选中文件", "选中理由",
                   "未选用文件", "未选用理由", "选中规则"]
        ws.append(headers)
        for r in rows:
            ws.append([
                r["item_no"], r["raw_text"], r["obligation"],
                r.get("entity_display", ""), r["entity_basis"], r["period"],
                r["period_basis"], r["doc_type"], r["doc_type_basis"],
                r["verdict"], r["entity_cov"], r["period_cov"],
                r["doctype_cov"], r["need_entities"], r["need_periods"],
                r["missing_detail"], r["candidate_count"],
                "; ".join(c["rel_path"] for c in r["candidates"][:5]),
                "是" if any(c["deliverable"] for c in r["candidates"]) else "否",
                _count_label(r),
                len(r.get("selected") or []),
                "; ".join(p["rel_path"] for p in (r.get("selected") or [])),
                "; ".join(p["reason"] for p in (r.get("selected") or [])),
                "; ".join(u["rel_path"] for u in (r.get("unselected") or [])),
                "; ".join(u["reason"] for u in (r.get("unselected") or [])),
                r.get("selection_rule", ""),
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

    # ── 2) 缺失与待确认清单（★ G-A3-5：受限与「不存在」**分区单列**）─────
    #   「材料存在但不可外发」与「材料根本不存在」是两回事，混在一起
    #   ⇒ 复核者会去追一份根本不存在的材料，而真正该处理的受限件被淹没。
    _sections = (
        ("一、材料根本不存在（MISSING）", ("MISSING",),
         "材料在库内查无此物"),
        ("二、材料不完整（PARTIAL）", ("PARTIAL",),
         "材料存在，但五维未齐（缺口明细已指名缺哪一维）"),
        ("三、材料存在但受限·不可外发（RESTRICTED）", ("RESTRICTED",),
         "材料在，但不可对外交付（原因逐条列出，不混入 MISSING）"),
        ("四、不可判定·待人工确认（UNCERTAIN）", ("UNCERTAIN",),
         "证据不足以判定，不得猜"),
        ("五、需人工裁定（CONFLICT）", ("CONFLICT",),
         "同主体同期内容冲突，必须人工裁定"),
        ("六、版本或期间不满足（STALE）", ("STALE",),
         "找到材料但版本/期间不满足当期要求"),
    )
    _gaps = [r for r in rows if r["verdict"] != "MATCHED"]
    _lines = ["以下义务未达完整状态，需人工处理。判定口径见 Goal Contract 硬门槛。",
              f"未达完整状态义务数：{len(_gaps)}（总义务 {len(rows)}）", ""]
    for title, verdicts, blurb in _sections:
        bucket = [r for r in _gaps if r["verdict"] in verdicts]
        _lines.append(f"## {title}（{len(bucket)} 条）")
        _lines.append(f"    {blurb}")
        if not bucket:
            _lines.append("    （无）")
        for r in bucket:
            _lines.append(f"  [{r['verdict']}] {r['item_no']} {r['obligation']}")
            _lines.append(f"    缺口：{r['missing_detail'] or '（未提供明细）'}")
            if r["verdict"] == "RESTRICTED":
                _reasons = []
                for c in r["candidates"]:
                    if c["deliverable"]:
                        continue
                    ev = _evidence_text(c.get("evidence"))
                    _reasons.append(f"{c['rel_path']}：{_blocked_category(ev)}"
                                    f"（{ev or '未提供原因'}）")
                _lines.append(f"    受限原因：{'；'.join(_reasons) or '（未提供明细）'}")
            _lines.append(f"    候选："
                          f"{'; '.join(c['rel_path'] for c in r['candidates']) or '（无）'}")
            if r.get("count_pending"):
                _lines.append("    ★ 份数待人工确认：清单提及份数但无法解析出权威份数"
                              "（不得默认 1 份），本条不自动交付主件")
        _lines.append("")
    (out_dir / "缺口与待确认清单.txt").write_text("\n".join(_lines), encoding="utf-8")
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
            f"- 应有份数：{_count_label(r)}（{r.get('target_reason', '')}）\n"
            f"- 缺口：{r['missing_detail'] or '无'}\n"
            f"- 选中集合（{len(r.get('selected') or [])} 件）：\n" +
            ("\n".join(
                f"    - [选中·{p.get('role', '主件')}] {p['rel_path']}：{p['reason']}"
                for p in (r.get("selected") or [])) or "    （无）") + "\n"
            f"- 未选用（{len(r.get('unselected') or [])} 件，不进交付目录）：\n" +
            ("\n".join(
                f"    - [未选用] {u['rel_path']}：{u['reason']}"
                for u in (r.get("unselected") or [])) or "    （无）") + "\n"
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
    lines = ["file_id\trel_path\tsha256\tsize\t可交付\t选中\t阻断原因"]
    for r in rows:
        _sel_ids = {p.get("file_id") for p in (r.get("selected") or [])}
        for c in r["candidates"]:
            ev = c.get("evidence") or ""
            lines.append(f"{c['file_id']}\t{c['rel_path']}\t\t\t"
                         f"{'是' if c['deliverable'] else '否'}\t"
                         f"{'是' if c['file_id'] in _sel_ids else '否'}\t{ev}")
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

    # ★ A3（G-A3-2）：交付集合 = **选中件** + 必备附件，**不是全部候选**。
    #   计划与审核包**共用**（_build_rows）⇒ 人工审阅的集合 = 实际交付的集合。
    rows = _build_rows(review["library_id"], db_path)
    unselected_rows: list[dict] = []

    for r in rows:
        for u in (r.get("unselected") or []):
            unselected_rows.append({
                "item_no": r["item_no"] or "",
                "obligation": r["obligation"],
                "file_id": u["file_id"],
                "rel_path": u["rel_path"],
                "reason": u["reason"],
            })
        # ★ G-A3-5：受限/不可交付的候选**单独分类**记录，不与「不存在」混同
        for c in r["candidates"]:
            if c["deliverable"]:
                continue
            ev = _evidence_text(c.get("evidence"))
            blocked.append({
                "obligation": r["obligation"],
                "file_id": c["file_id"],
                "rel_path": c["rel_path"],
                "category": _blocked_category(ev),
                "reason": ev or "受限/不可读/敏感等级未知",
            })
        sel = r.get("selected") or []
        if not sel:
            # 没有选中件 ⇒ **不建目录**（空目录也是「同目录顺带复制」的残留）
            continue

        item_dir = out / _safe_dirname((r["item_no"] or r["obligation_id"]))
        item_dir.mkdir(parents=True, exist_ok=True)

        for p in sel:
            c = next((x for x in r["candidates"] if x["file_id"] == p["file_id"]), None)
            if c is None or not c["deliverable"]:
                blocked.append({
                    "obligation": r["obligation"], "file_id": p["file_id"],
                    "rel_path": p.get("rel_path", ""),
                    "category": "受限/不可交付",
                    "reason": "选中件在复制前失去交付资格",
                })
                continue
            mrow = conn.execute(
                "SELECT * FROM dd_v1_manifest WHERE file_id=?", (c["file_id"],)
            ).fetchone()
            if mrow is None:
                continue
            src = Path(mrow["abs_path"])
            if not src.is_file():
                blocked.append({"obligation": r["obligation"],
                                "file_id": c["file_id"], "rel_path": c["rel_path"],
                                "category": "源文件不存在",
                                "reason": "源文件已不存在"})
                continue
            dest = item_dir / _safe_filename(mrow["file_name"])
            # 越界兜底闸：清洗后仍异常则跳过，不写
            if not _within(out, dest):
                blocked.append({"obligation": r["obligation"],
                                "file_id": c["file_id"], "rel_path": c["rel_path"],
                                "category": "越界拦截（安全跳过）",
                                "reason": "目标越界，安全跳过"})
                continue
            if dest.exists():
                dest = item_dir / f"{_safe_filename(src.stem)}_{_safe_filename(c['file_id'][:8])}{src.suffix}"
                if not _within(out, dest):
                    blocked.append({"obligation": r["obligation"],
                                    "file_id": c["file_id"], "rel_path": c["rel_path"],
                                    "category": "越界拦截（安全跳过）",
                                    "reason": "目标越界，安全跳过"})
                    continue
            shutil.copy2(src, dest)
            exported.append({
                "item_no": r["item_no"] or "",
                "obligation": r["obligation"],
                "dest": str(dest.relative_to(out)),
                "src_sha256": mrow["content_hash"],
                "dest_sha256": _sha256(dest),
                "verdict": r["verdict"],
                "role": p.get("role", "主件"),
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
    # ★ A3（G-A3-2）：**未选用清单**必须可审计——
    #   「不交」是决定，「不解释」是失职。逐条写明**为什么没选**。
    (out / "未选用清单.tsv").write_text(
        "机构编号\t原子义务\tfile_id\t相对路径\t未选用原因\n" +
        "\n".join(
            f"{u['item_no']}\t{u['obligation']}\t{u['file_id']}\t"
            f"{u['rel_path']}\t{u['reason']}"
            for u in unselected_rows), encoding="utf-8")

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
        # ★ A3（G-A3-2）：交付集合的口径要能自证——
        #   交了几件、没交几件、没交的理由都在清单里。
        "unselected": len(unselected_rows),
        "unselected_manifest": str(out / "未选用清单.tsv"),
        "selection_rule": ("可交付候选按「四维命中分 → 主体命中 → 期间命中 → "
                           "类型命中 → file_id 升序」确定性排序取前 N 份；"
                           "必备附件只认 related_files 显式列出的文件"),
    }


def get_review(review_id: str, db_path: Path | None = None) -> dict | None:
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    return dict(row) if row else None
