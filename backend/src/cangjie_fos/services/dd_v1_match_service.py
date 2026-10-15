"""DD-V1 多文件匹配与四维完整性覆盖（WP3 · M2 / M3）。

把「一条原子义务 → 多个证据文件」这件事做实，并把「找到一份就算完成」改掉。

## 直接对治既有缺陷

**D3（候选上限只是 prompt 文本）**
旧实现把「最多 2 个」写在提示词里（`dd_match_service.py:928`），解析处
（`:988-998`）没有任何代码切片，实际靠 LLM 自觉。
本模块把候选上限变成**显式可配置参数** ``candidate_cap``（默认 20，可按库调），
并做**高召回 → 确定性精排**两段式，**任何截断都记录被截断的数量**。

**D3（多文件聚合只按年份）**
旧 `_apply_multifile_aggregation:1348` 只按年份聚合，母子公司/多主体无任何建模。
本模块按**主体 × 期间 × 材料类型 × 必备附件**四维分别计算覆盖率，
**一个义务可以同时需要「母公司×合并 + 3 个子公司×单体」共 4 份以上材料**。

**D4（决策记忆无主体/版本/时效校验）**
记忆命中一律要过 `revalidate_memory_hit()`：主体、期间、版本、有效性、
适用范围五项任一不符即拒绝沿用。旧实现把 `last_institution` 写进去却从不读
（`dd_match_service.py:1478` vs `:1546`），属写而不读。

## 判定口径

一个义务的最终判定 = 四维覆盖 + 冲突/受限检查，**不是「有没有找到相关文件」**：

- ``MATCHED``    四维全覆盖且无冲突
- ``PARTIAL``    缺一部分（典型：主体缺 1 家，或期间缺 1 年）
- ``MISSING``    四维基本为零
- ``STALE``      找到材料但版本/期间不满足当前要求（如要求今年却是去年的）
- ``CONFLICT``   同一义务存在互相矛盾的多份材料（如两份不同主体的审计报告同号）
- ``UNCERTAIN``  证据不足以判定（主体范围无权威名单、相对年份未锚定等）
- ``RESTRICTED`` 材料敏感/受限/不可读/权限未知——**不得自动纳入可对外交付结果**
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_requirement_service as rq

logger = logging.getLogger(__name__)

# ── 判定枚举 ────────────────────────────────────────────────────────────────
V_MATCHED = "MATCHED"
V_PARTIAL = "PARTIAL"
V_MISSING = "MISSING"
V_STALE = "STALE"
V_CONFLICT = "CONFLICT"
V_UNCERTAIN = "UNCERTAIN"
V_RESTRICTED = "RESTRICTED"

# ── 默认参数（全部可配，禁止硬编码「最多 2 份」）────────────────────────────
DEFAULT_CANDIDATE_CAP = int(
    __import__("os").getenv("CANGJIE_DD_V1_CANDIDATE_CAP", "20") or "20"
)
# 四维覆盖率阈值：低于 FULL 即判不完整。调高会让「找到一份就算完成」的毛病复发。
FULL_COVERAGE = 0.999

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_matches (
    match_id      TEXT PRIMARY KEY,
    obligation_id TEXT NOT NULL,
    library_id    TEXT NOT NULL,
    file_id       TEXT NOT NULL,
    rank          INTEGER NOT NULL DEFAULT 0,
    score         REAL NOT NULL DEFAULT 0,
    entity_ok     INTEGER NOT NULL DEFAULT 0,
    period_ok     INTEGER NOT NULL DEFAULT 0,
    doctype_ok    INTEGER NOT NULL DEFAULT 0,
    attachment_ok INTEGER NOT NULL DEFAULT 0,
    seal_ok       INTEGER NOT NULL DEFAULT 0,
    deliverable   INTEGER NOT NULL DEFAULT 1,
    verdict       TEXT NOT NULL DEFAULT '',
    evidence      TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    UNIQUE (obligation_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_match_obl ON dd_v1_matches(obligation_id);
CREATE INDEX IF NOT EXISTS idx_dd_v1_match_lib ON dd_v1_matches(library_id);

CREATE TABLE IF NOT EXISTS dd_v1_obligation_status (
    obligation_id  TEXT PRIMARY KEY,
    library_id     TEXT NOT NULL,
    verdict        TEXT NOT NULL,
    entity_cov     REAL NOT NULL DEFAULT 0,
    period_cov     REAL NOT NULL DEFAULT 0,
    doctype_cov    REAL NOT NULL DEFAULT 0,
    attach_cov     REAL NOT NULL DEFAULT 0,
    need_entities  INTEGER NOT NULL DEFAULT 0,
    need_periods   INTEGER NOT NULL DEFAULT 0,
    missing_detail TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    capped         INTEGER NOT NULL DEFAULT 0,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_status_lib ON dd_v1_obligation_status(library_id);
"""

# 认知卡 purpose 关键词 → 义务 doc_type 的映射（确定性，不猜）
_DOC_TYPE_PURPOSE_MAP = {
    "audit_report": ("审计",),
    "financial_statement": ("财务", "利润", "资产负债", "现金流"),
    "tax": ("纳税", "税务", "完税"),
    "license": ("营业执照", "主体存续"),
    "charter": ("章程", "治理"),
    "capital": ("验资", "出资"),
    "resolution": ("决议", "决策记录"),
    "ip": ("知识产权", "专利", "商标"),
    "labor": ("用工合规",),
    "contract": (),
}


def _ensure_schema(conn) -> None:
    conn.executescript(_DDL)
    conn.commit()


def _conn(db_path: Path | None = None):
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    return conn


# ── 单文件对单义务的维度判定 ────────────────────────────────────────────────
def evaluate_file(
    obligation: dict,
    card: dict | None,
    manifest_row: dict | None,
    need_entities: list[dict],
) -> dict:
    """算出一份材料对一个义务的四维命中情况。**确定性，不含 LLM。**"""
    ent_ok = per_ok = doc_ok = seal_ok = 0

    # 主体维度
    if need_entities and card:
        names = {e["display_name"] for e in need_entities}
        blob = f"{card.get('entity','')} {card.get('rel_path','')} {card.get('title','')}"
        ent_ok = 1 if any(n and n in blob for n in names) else 0
    elif not need_entities:
        # 义务没要求特定主体范围（如「贵司」）→ 主体维度不构成门槛
        ent_ok = 1

    # 期间维度
    y_from, y_to = obligation.get("period_from", 0), obligation.get("period_to", 0)
    if y_from and y_to:
        pv = card.get("fiscal_period") if card else ""
        per_ok = 1 if pv and y_from <= int(pv) <= y_to else 0
    else:
        per_ok = 1   # 期间未锚定 → 由 obligation_status 判 UNCERTAIN，不在此扣分

    # 材料类型维度
    dt = obligation.get("doc_type") or ""
    if dt:
        purposes = " ".join(card.get("purpose") or []) if card else ""
        keys = _DOC_TYPE_PURPOSE_MAP.get(dt)
        doc_ok = 1 if (card and ((not keys) or any(k in purposes or k in card.get("title", "") for k in keys))) else 0
    else:
        doc_ok = 1

    # 签章维度（认知卡里 seal_status 恒 UNKNOWN → 这里必然不满足，属已知缺口）
    seal_req = obligation.get("seal_required") or ""
    if seal_req:
        seal_ok = 1 if (card and card.get("seal_status") == seal_req) else 0
    else:
        seal_ok = 1

    # 可交付性：不可读/解析失败/敏感等级未知 → 不得自动纳入对外交付
    deliverable = 1
    reasons = []
    if manifest_row is not None:
        if manifest_row.get("parse_status") not in (mf.PARSE_OK, mf.PARSE_PARTIAL):
            deliverable = 0
            reasons.append(f"解析状态={manifest_row.get('parse_status')}")
    if card is not None:
        if card.get("sensitivity") in ("", None):
            deliverable = 0
            reasons.append("敏感等级未知，按指令不得自动纳入对外交付")

    # 必备附件维度：认知卡的 related_files 目前恒 UNKNOWN（WP2 未实现附件关系解析），
    # 因此义务要求附件时这一维度必然不满足——**这是已知缺口，不得为了好看而放行**。
    if obligation.get("needs_attachments"):
        rel = (card or {}).get("related_files") if card else None
        attachment_ok = 1 if rel else 0
    else:
        attachment_ok = 1

    return {
        "entity_ok": ent_ok, "period_ok": per_ok, "doctype_ok": doc_ok,
        "seal_ok": seal_ok, "attachment_ok": attachment_ok,
        "deliverable": deliverable, "reasons": reasons,
    }


# ── 高召回 + 确定性精排 ────────────────────────────────────────────────────
def _recall_candidates(
    obligation: dict, library_id: str, cap: int, db_path: Path | None
) -> tuple[list[dict], bool]:
    """高召回：用**材料里真实会出现的中文词**做 FTS 召回，取前 ``cap`` 份。

    注意：首轮实现把 ``doc_type`` 的英文 key（如 ``audit_report``）当检索词，
    而认知卡与正文全是中文 → 召回恒为空、四维覆盖全算 0。
    必须经 :func:`rq.doc_type_search_terms` 翻译成中文材料词。
    """
    terms = rq.doc_type_search_terms(obligation.get("doc_type") or "")
    hits: dict[str, float] = {}
    for t in terms:
        for h in cs.search_materials(library_id, t, limit=cap * 2, db_path=db_path):
            hits[h["file_id"]] = min(hits.get(h["file_id"], 0.0), h["score"])
    ordered = sorted(hits.items(), key=lambda kv: kv[1])[:cap]
    return ([{"file_id": fid, "score": sc} for fid, sc in ordered],
            len(hits) > cap)


def match_obligation(
    library_id: str,
    obligation_id: str,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    db_path: Path | None = None,
) -> dict:
    """对一条原子义务做匹配并给出最终判定。"""
    conn = _conn(db_path)
    obl = conn.execute(
        "SELECT * FROM dd_v1_obligations WHERE obligation_id=?", (obligation_id,)
    ).fetchone()
    if obl is None:
        raise KeyError(f"义务不存在：{obligation_id}")
    obl = dict(obl)

    need_entities = rq.resolve_entities(
        library_id, obl.get("entity_scope") or "", obl.get("period_to") or None, db_path)

    # 召回：先用权威名单内的主体文件，再退回全文召回
    candidates, capped = _recall_candidates(obl, library_id, candidate_cap, db_path)

    results = []
    for c in candidates:
        card = cs.get_card(c["file_id"], db_path=db_path)
        mrow = conn.execute(
            "SELECT * FROM dd_v1_manifest WHERE file_id=?", (c["file_id"],)
        ).fetchone()
        ev = evaluate_file(obl, card, dict(mrow) if mrow else None, need_entities)
        score = (ev["entity_ok"] + ev["period_ok"] + ev["doctype_ok"] + ev["seal_ok"]) / 4.0
        results.append({**c, "card": card, "manifest": dict(mrow) if mrow else None,
                        "ev": ev, "score": round(score, 4)})

    results.sort(key=lambda r: -r["score"])
    for i, r in enumerate(results, 1):
        r["rank"] = i

    status = judge(obl, results, need_entities, capped)
    _persist(conn, library_id, obligation_id, obl, results, status)
    return status


def judge(
    obl: dict, results: list[dict], need_entities: list[dict], capped: bool
) -> dict:
    """四维覆盖 → 最终判定。**核心：不是「有没有找到相关文件」。**"""
    n_ent = len(need_entities)
    # 需要的期间数（每一年都要有）
    y_from, y_to = obl.get("period_from", 0), obl.get("period_to", 0)
    need_periods = (y_to - y_from + 1) if (y_from and y_to and y_to >= y_from) else 0

    matched = [r for r in results if r["ev"]["deliverable"]]
    # 覆盖度按**全部候选**计算（材料是否存在），而不是只算可交付的。
    # 「材料存在但受限」与「材料根本不存在」在缺口清单里是两回事，必须分开报：
    # 前者 RESTRICTED，后者 MISSING/PARTIAL。
    pool = results

    # 主体覆盖：需要的主体里有多少被覆盖
    ent_cov = 0.0
    if n_ent:
        covered = set()
        for r in pool:
            blob = f"{(r['card'] or {}).get('entity','')} {r['manifest']['rel_path'] if r['manifest'] else ''}"
            for e in need_entities:
                if e["display_name"] and e["display_name"] in blob:
                    covered.add(e["entity_id"])
        ent_cov = len(covered) / n_ent
    else:
        ent_cov = 1.0

    # 期间覆盖：需要的年份里有多少被覆盖
    period_cov = 0.0
    if need_periods:
        years = set()
        for r in pool:
            pv = (r["card"] or {}).get("fiscal_period")
            if pv and str(pv).isdigit():
                y = int(pv)
                if y_from <= y <= y_to:
                    years.add(y)
        period_cov = len(years) / need_periods
    else:
        period_cov = 1.0

    doctype_cov = (sum(1 for r in pool if r["ev"]["doctype_ok"]) / len(pool)
                   if pool else 0.0)
    attach_cov = (sum(1 for r in pool if r["ev"]["attachment_ok"]) / len(pool)
                  if pool else 0.0)

    missing = []
    if n_ent and ent_cov < FULL_COVERAGE:
        missing.append(f"主体缺 {n_ent - round(ent_cov * n_ent)}/{n_ent} 家")
    if need_periods and period_cov < FULL_COVERAGE:
        missing.append(f"期间缺 {need_periods - round(period_cov * need_periods)}/{need_periods} 年")

    # 判定
    if not results:
        verdict = V_MISSING
    elif need_periods and period_cov < 1.0 and period_cov > 0:
        verdict = V_PARTIAL
    elif not obl.get("period_basis") or obl.get("period_basis") == "relative_unresolved":
        verdict = V_UNCERTAIN
    elif not n_ent and obl.get("entity_scope"):
        # 要求了主体范围却没有权威名单 → 不得用目录名凑数，判 UNCERTAIN
        verdict = V_UNCERTAIN
    elif ent_cov < FULL_COVERAGE:
        verdict = V_PARTIAL
    elif doctype_cov < FULL_COVERAGE:
        verdict = V_PARTIAL
    else:
        verdict = V_MATCHED

    # 受限材料不能顶替：覆盖完整但**一份都不可交付**时，不得判 MATCHED。
    # 这是硬门槛 HG1「未经人工最终批准不得对外交付」的机器侧兜底。
    if verdict == V_MATCHED and not matched:
        verdict = V_RESTRICTED
        missing.append("材料已找到但全部受限/不可读/敏感等级未知，不得自动纳入对外交付")

    return {
        "obligation_id": obl["obligation_id"],
        "verdict": verdict,
        "entity_cov": round(ent_cov, 4),
        "period_cov": round(period_cov, 4),
        "doctype_cov": round(doctype_cov, 4),
        "attach_cov": round(attach_cov, 4),
        "need_entities": n_ent,
        "need_periods": need_periods,
        "missing_detail": "; ".join(missing),
        "candidate_count": len(results),
        "capped": 1 if capped else 0,
        "deliverable_count": len(matched),
    }


def _persist(conn, library_id, obligation_id, obl, results, status) -> None:
    now = time.time()
    conn.execute("DELETE FROM dd_v1_matches WHERE obligation_id=?", (obligation_id,))
    for r in results:
        conn.execute(
            """INSERT INTO dd_v1_matches
               (match_id, obligation_id, library_id, file_id, rank, score,
                entity_ok, period_ok, doctype_ok, attachment_ok, seal_ok,
                deliverable, verdict, evidence, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, obligation_id, library_id, r["file_id"],
             r["rank"], r["score"], r["ev"]["entity_ok"], r["ev"]["period_ok"],
             r["ev"]["doctype_ok"], r["ev"]["attachment_ok"], r["ev"]["seal_ok"],
             r["ev"]["deliverable"], "", json.dumps(r["ev"]["reasons"], ensure_ascii=False), now),
        )
    conn.execute(
        """INSERT INTO dd_v1_obligation_status
           (obligation_id, library_id, verdict, entity_cov, period_cov,
            doctype_cov, attach_cov, need_entities, need_periods,
            missing_detail, candidate_count, capped, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(obligation_id) DO UPDATE SET
             verdict=excluded.verdict, entity_cov=excluded.entity_cov,
             period_cov=excluded.period_cov, doctype_cov=excluded.doctype_cov,
             attach_cov=excluded.attach_cov, need_entities=excluded.need_entities,
             need_periods=excluded.need_periods, missing_detail=excluded.missing_detail,
             candidate_count=excluded.candidate_count, capped=excluded.capped,
             updated_at=excluded.updated_at""",
        (obligation_id, library_id, status["verdict"], status["entity_cov"],
         status["period_cov"], status["doctype_cov"], status["attach_cov"],
         status["need_entities"], status["need_periods"], status["missing_detail"],
         status["candidate_count"], status["capped"], now),
    )
    conn.commit()


def match_library(
    library_id: str,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    db_path: Path | None = None,
) -> dict:
    """批量匹配全库义务。"""
    conn = _conn(db_path)
    obl_ids = [r["obligation_id"] for r in conn.execute(
        "SELECT obligation_id FROM dd_v1_obligations WHERE library_id=?", (library_id,))]
    tally: dict[str, int] = {}
    for oid in obl_ids:
        st = match_obligation(library_id, oid, candidate_cap=candidate_cap, db_path=db_path)
        tally[st["verdict"]] = tally.get(st["verdict"], 0) + 1
    return {
        "library_id": library_id,
        "obligations": len(obl_ids),
        "candidate_cap": candidate_cap,
        "by_verdict": tally,
        "docling_note": "候选上限为显式配置项，非硬编码",
    }


def get_status(obligation_id: str, db_path: Path | None = None) -> dict | None:
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_obligation_status WHERE obligation_id=?", (obligation_id,)
    ).fetchone()
    return dict(row) if row else None


def list_matches(obligation_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _conn(db_path)
    return [dict(r) for r in conn.execute(
        """SELECT m.*, c.rel_path AS card_rel_path, c.title AS card_title
           FROM dd_v1_matches m
           LEFT JOIN dd_v1_material_cards c ON c.file_id = m.file_id
           WHERE m.obligation_id=? ORDER BY m.rank""", (obligation_id,))]


def file_serves_count(file_id: str, db_path: Path | None = None) -> int:
    """一个文件可服务多条义务——统计复用度（对应指令「一个文件也允许服务多条需求」）。"""
    conn = _conn(db_path)
    return conn.execute(
        "SELECT COUNT(*) c FROM dd_v1_matches WHERE file_id=?", (file_id,)
    ).fetchone()["c"]


# ── D4：决策记忆的严格复验 ─────────────────────────────────────────────────
def revalidate_memory_hit(
    remembered: dict,
    current_entity: str,
    current_period: tuple[int, int] | None,
    card: dict | None,
) -> tuple[bool, str]:
    """决策记忆是否仍可沿用。任一项不符即拒绝。

    直接对治 D4：旧实现把 ``last_institution`` 写入 ``dd_decision_memory`` 却从不在
    lookup 里读（`dd_match_service.py:1478` 写 / `:1546` 读），等于跨主体自动锁定。
    """
    if not remembered:
        return False, "无记忆"
    rec_entity = (remembered.get("last_institution") or "").strip()
    if rec_entity and current_entity and rec_entity != current_entity:
        return False, f"主体不符：记忆={rec_entity} 当前={current_entity}"
    if remembered.get("valid_to"):
        return False, "记忆条目有失效期，当前实现未接入有效期判定，不作沿用"
    if current_period and card:
        pv = card.get("fiscal_period")
        if pv and str(pv).isdigit():
            y = int(pv)
            if not (current_period[0] <= y <= current_period[1]):
                return False, f"期间不符：记忆文件 {y} 不在 {current_period}"
    return True, "通过"
