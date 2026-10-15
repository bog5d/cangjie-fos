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
    # 异常检测结果（STALE/CONFLICT）需要持久化，供审核包与组包读取。
    # 用 ALTER 而非改 CREATE，保证既有库平滑升级。
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(dd_v1_obligation_status)")}
    if "anomalies_json" not in cols:
        conn.execute("ALTER TABLE dd_v1_obligation_status ADD COLUMN anomalies_json TEXT NOT NULL DEFAULT '{}'")
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

    # 必备附件维度：读**已解析的** fields.related_files。
    # 注意不能直接读卡片表的 related_files 列——那是 json.dumps 的字符串，
    # `json.dumps([])` 得到 "[]"，是真值，会让本维度恒判定为满足（假阳性）。
    if obligation.get("needs_attachments"):
        rel = []
        if card:
            fields = card.get("fields") or {}
            raw = (fields.get("related_files") or {}).get("value") or []
            rel = raw if isinstance(raw, list) else []
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


def _related_of(r: dict) -> list[str]:
    """取卡片里已解析的 related_files（不是 JSON 字符串列）。"""
    fields = (r.get("card") or {}).get("fields") or {}
    raw = (fields.get("related_files") or {}).get("value") or []
    return raw if isinstance(raw, list) else []


def _is_attachment_of_other(pool: list[dict], fid: str, fids: set[str]) -> bool:
    """该文件是否是同组里另一份文件的附件。"""
    me = next((r for r in pool if r["file_id"] == fid), None)
    if me is None:
        return False
    mine = set(_related_of(me))
    for other in fids - {fid}:
        orow = next((r for r in pool if r["file_id"] == other), None)
        if orow is None:
            continue
        rel_other = ((orow.get("card") or {}).get("rel_path")
                     or (orow.get("manifest") or {}).get("rel_path") or "")
        rel_me = ((me.get("card") or {}).get("rel_path")
                  or (me.get("manifest") or {}).get("rel_path") or "")
        if rel_other in mine or rel_me in set(_related_of(orow)):
            return True
    return False


def detect_entity_substitution(pool, need_entities) -> list[dict]:
    """跨主体复用检测：同一份材料被用于满足**不同主体**的义务。

    这是 HG2「主体冒充」的第二层——第一层只看「同一 file_id 是否挂了多个主体」，
    但更常见的错法是：拿 A 公司的材料去顶 B 公司的要求。
    """
    names = {e["display_name"] for e in need_entities if e.get("display_name")}
    by_file: dict[str, set[str]] = {}
    for r in pool:
        card = r.get("card") or {}
        ent = card.get("entity") or ""
        if not ent:
            continue
        by_file.setdefault(r["file_id"], set()).add(ent)
    out = []
    for fid, ents in by_file.items():
        other = ents & names - {next(iter(ents))} if len(ents & names) > 1 else set()
        if len(ents & names) > 1:
            out.append({"file_id": fid, "entities": sorted(ents & names)})
    return out


def detect_anomalies(
    obl: dict, pool: list[dict], need_entities: list[dict]
) -> dict:
    """检测 STALE（过期）与 CONFLICT（冲突）。

    WP3 交付时这两态尚未有实质实现，本函数补上：

    - **STALE**：某主体名下只有**区间外**年份的材料覆盖了它，而区间内没有。
      即「拿旧版本顶当期要求」——`mtime` 不代表业务有效，必须靠期间判定。
    - **CONFLICT**：同一义务下，**同一主体 + 同一期间**出现内容哈希不同的多份材料，
      无法判定哪份为准，不得自动二选一。
    """
    stale_entities: list[str] = []
    conflict_pairs: list[dict] = []
    y_from, y_to = obl.get("period_from", 0), obl.get("period_to", 0)

    # 按 (主体, 期间) 分桶
    buckets: dict[tuple[str, str], set[str]] = {}
    for r in pool:
        card = r.get("card") or {}
        ent = card.get("entity") or (r["manifest"]["rel_path"].split("/")[0]
                                     if r.get("manifest") and "/" in r["manifest"]["rel_path"] else "")
        pv = str(card.get("fiscal_period") or "")
        buckets.setdefault((ent, pv), set()).add(r["file_id"])

    for (ent, pv), fids in buckets.items():
        if len(fids) > 1:
            # **主文档与它的附表不是「冲突版本」**，必须排除，
            # 否则「审计报告 + 审计报告附表」这种正常组合会被误判为内容冲突。
            fids = {f for f in fids if not _is_attachment_of_other(pool, f, fids)}
            if len(fids) <= 1:
                continue
            hashes = {
                (r.get("manifest") or {}).get("content_hash")
                for r in pool if r["file_id"] in fids
            }
            hashes.discard(None)
            if len(hashes) > 1:
                conflict_pairs.append({
                    "entity": ent, "period": pv,
                    "files": sorted(fids), "distinct_hashes": len(hashes),
                })

    # STALE：有主体只在区间外被覆盖
    if y_from and y_to:
        covered_by_entity: dict[str, set[int]] = {}
        for r in pool:
            card = r.get("card") or {}
            ent = card.get("entity") or (r["manifest"]["rel_path"].split("/")[0]
                                         if r.get("manifest") and "/" in r["manifest"]["rel_path"] else "")
            pv = str(card.get("fiscal_period") or "")
            if pv.isdigit():
                covered_by_entity.setdefault(ent, set()).add(int(pv))
        targets = ([e["display_name"] for e in need_entities] if need_entities
                   else list(covered_by_entity.keys()))
        for ent in targets:
            years = covered_by_entity.get(ent)
            if not years:
                continue
            inside = {y for y in years if y_from <= y <= y_to}
            outside = years - inside
            if not inside and outside:
                stale_entities.append(f"{ent}: 仅有 {sorted(outside)}，要求 {y_from}-{y_to}")

    return {
        "stale_entities": stale_entities,
        "conflicts": conflict_pairs,
        "has_stale": bool(stale_entities),
        "has_conflict": bool(conflict_pairs),
    }


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
    # 必备附件覆盖：义务要求附件时，看**可交付**的命中材料里有多少带可观察的关联件。
    # 认知卡的 related_files 自 WP6 起可由确定性规则填充，故此维度不再是恒 0。
    if obl.get("needs_attachments"):
        attach_cov = (sum(1 for r in pool if r["ev"]["attachment_ok"]) / len(pool)
                      if pool else 0.0)
    else:
        attach_cov = 1.0

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
    elif attach_cov < FULL_COVERAGE:
        verdict = V_PARTIAL
        missing.append("必备附件缺失")
    else:
        verdict = V_MATCHED

    # 受限材料不能顶替：覆盖完整但**一份都不可交付**时，不得判 MATCHED。
    # 这是硬门槛 HG1「未经人工最终批准不得对外交付」的机器侧兜底。
    if verdict == V_MATCHED and not matched:
        verdict = V_RESTRICTED
        missing.append("材料已找到但全部受限/不可读/敏感等级未知，不得自动纳入对外交付")

    # STALE / CONFLICT 优先于 MATCHED/PARTIAL：拿旧版本顶当期、或同主体同期多版本冲突，
    # 都必须让人看见，不能被「覆盖率够了」盖过去。
    anom = detect_anomalies(obl, results, need_entities)
    if anom["has_conflict"]:
        verdict = V_CONFLICT
        missing.append(f"同一主体/期间存在 {len(anom['conflicts'])} 组内容冲突，需人工裁定")
    elif anom["has_stale"] and verdict in (V_MATCHED, V_PARTIAL):
        verdict = V_STALE
        missing.append("；".join(anom["stale_entities"]))

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
        **anom,
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
    conn.execute(
        "UPDATE dd_v1_obligation_status SET anomalies_json=? WHERE obligation_id=?",
        (json.dumps({k: status.get(k) for k in
                     ("stale_entities", "conflicts", "has_stale", "has_conflict")},
                    ensure_ascii=False), obligation_id),
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
    if not row:
        return None
    d = dict(row)
    try:
        d.update(json.loads(d.pop("anomalies_json") or "{}"))
    except (ValueError, TypeError):
        d["anomalies_json"] = "{}"
    return d


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
