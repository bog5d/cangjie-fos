"""Phase 6：机构画像 SQLite 存储（按 tenant_id 隔离）。"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from cangjie_fos.core import paths as fos_paths
from cangjie_fos.schemas.institution import (
    InstitutionProfile,
    InstitutionProfileCreate,
    InstitutionThermal,
    PipelineStage,
)


def _db_path() -> str:
    p = fos_paths.get_backend_root() / "data" / "institutions.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), check_same_thread=False)
    c.execute(
        """CREATE TABLE IF NOT EXISTS institutions (
            institution_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            stage TEXT NOT NULL,
            thermal TEXT NOT NULL,
            preferences TEXT NOT NULL DEFAULT '',
            concerns TEXT NOT NULL DEFAULT '',
            ai_summary TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            source_trace_id TEXT,
            UNIQUE(tenant_id, name)
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_institutions_tenant ON institutions(tenant_id)")
    # CRM 扩展字段 migration（幂等）
    for col_def in [
        "contact_name TEXT NOT NULL DEFAULT ''",
        "contact_title TEXT NOT NULL DEFAULT ''",
        "valuation TEXT NOT NULL DEFAULT ''",
        "deal_size TEXT NOT NULL DEFAULT ''",
        "probability INTEGER NOT NULL DEFAULT 0",
        "legal_status TEXT NOT NULL DEFAULT ''",
        # 里程碑字段（v1.3.0）
        "nda_signed INTEGER NOT NULL DEFAULT 0",
        "offline_meeting_count INTEGER NOT NULL DEFAULT 0",
        "project_approved INTEGER NOT NULL DEFAULT 0",
        "committee_approved INTEGER NOT NULL DEFAULT 0",
        "onsite_dd_done INTEGER NOT NULL DEFAULT 0",
        "external_dd_done INTEGER NOT NULL DEFAULT 0",
        "agreement_signed INTEGER NOT NULL DEFAULT 0",
        "deal_closed INTEGER NOT NULL DEFAULT 0",
        "referral_source TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            c.execute(f"ALTER TABLE institutions ADD COLUMN {col_def}")  # noqa: S608
        except sqlite3.OperationalError:
            pass  # column already exists
    c.commit()
    return c


def upsert_institution(row: InstitutionProfile) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO institutions (
                institution_id, tenant_id, name, stage, thermal,
                preferences, concerns, ai_summary, updated_at, source_trace_id,
                contact_name, contact_title, valuation, deal_size, probability, legal_status,
                nda_signed, offline_meeting_count, project_approved, committee_approved,
                onsite_dd_done, external_dd_done, agreement_signed, deal_closed, referral_source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tenant_id, name) DO UPDATE SET
                stage=excluded.stage,
                thermal=excluded.thermal,
                preferences=excluded.preferences,
                concerns=excluded.concerns,
                ai_summary=excluded.ai_summary,
                updated_at=excluded.updated_at,
                source_trace_id=excluded.source_trace_id,
                contact_name=excluded.contact_name,
                contact_title=excluded.contact_title,
                valuation=excluded.valuation,
                deal_size=excluded.deal_size,
                probability=excluded.probability,
                legal_status=excluded.legal_status,
                nda_signed=excluded.nda_signed,
                offline_meeting_count=excluded.offline_meeting_count,
                project_approved=excluded.project_approved,
                committee_approved=excluded.committee_approved,
                onsite_dd_done=excluded.onsite_dd_done,
                external_dd_done=excluded.external_dd_done,
                agreement_signed=excluded.agreement_signed,
                deal_closed=excluded.deal_closed,
                referral_source=excluded.referral_source
            """,
            (
                row.institution_id,
                row.tenant_id,
                row.name,
                row.stage.value,
                row.thermal.value,
                row.preferences,
                row.concerns,
                row.ai_summary,
                row.updated_at,
                row.source_trace_id,
                row.contact_name,
                row.contact_title,
                row.valuation,
                row.deal_size,
                row.probability,
                row.legal_status,
                int(row.nda_signed),
                row.offline_meeting_count,
                int(row.project_approved),
                int(row.committee_approved),
                int(row.onsite_dd_done),
                int(row.external_dd_done),
                int(row.agreement_signed),
                int(row.deal_closed),
                row.referral_source,
            ),
        )
        c.commit()


def create_institution(body: InstitutionProfileCreate) -> InstitutionProfile:
    now = time.time()
    prof = InstitutionProfile(
        institution_id=uuid.uuid4().hex,
        tenant_id=body.tenant_id,
        name=body.name.strip(),
        stage=body.stage,
        thermal=body.thermal,
        preferences=body.preferences,
        concerns=body.concerns,
        ai_summary=body.ai_summary,
        updated_at=now,
        source_trace_id=body.source_trace_id,
        contact_name=body.contact_name,
        contact_title=body.contact_title,
        valuation=body.valuation,
        deal_size=body.deal_size,
        probability=body.probability,
        legal_status=body.legal_status,
        nda_signed=body.nda_signed,
        offline_meeting_count=body.offline_meeting_count,
        project_approved=body.project_approved,
        committee_approved=body.committee_approved,
        onsite_dd_done=body.onsite_dd_done,
        external_dd_done=body.external_dd_done,
        agreement_signed=body.agreement_signed,
        deal_closed=body.deal_closed,
        referral_source=body.referral_source,
    )
    upsert_institution(prof)
    return prof


def list_institutions(*, tenant_id: str, limit: int = 200) -> list[InstitutionProfile]:
    with _conn() as c:
        cur = c.execute(
            """SELECT institution_id, tenant_id, name, stage, thermal,
                      preferences, concerns, ai_summary, updated_at, source_trace_id,
                      contact_name, contact_title, valuation, deal_size, probability, legal_status,
                      nda_signed, offline_meeting_count, project_approved, committee_approved,
                      onsite_dd_done, external_dd_done, agreement_signed, deal_closed, referral_source
               FROM institutions WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?""",  # noqa: E501
            (tenant_id, limit),
        )
        rows = cur.fetchall()
    out: list[InstitutionProfile] = []
    for r in rows:
        out.append(row_to_profile(r))
    return out


def count_by_stage(*, tenant_id: str) -> dict[str, int]:
    base = {s.value: 0 for s in PipelineStage}
    with _conn() as c:
        cur = c.execute(
            "SELECT stage, COUNT(*) FROM institutions WHERE tenant_id = ? GROUP BY stage",
            (tenant_id,),
        )
        for st, n in cur.fetchall():
            if st in base:
                base[st] = int(n)
    return base


def delete_institution(*, tenant_id: str, institution_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM institutions WHERE tenant_id = ? AND institution_id = ?",
            (tenant_id, institution_id),
        )
        c.commit()
        return cur.rowcount > 0


def update_institution(
    *,
    tenant_id: str,
    institution_id: str,
    name: str | None = None,
    stage: str | None = None,
    thermal: str | None = None,
    preferences: str | None = None,
    concerns: str | None = None,
    ai_summary: str | None = None,
    contact_name: str | None = None,
    contact_title: str | None = None,
    valuation: str | None = None,
    deal_size: str | None = None,
    probability: int | None = None,
    legal_status: str | None = None,
    nda_signed: bool | None = None,
    offline_meeting_count: int | None = None,
    project_approved: bool | None = None,
    committee_approved: bool | None = None,
    onsite_dd_done: bool | None = None,
    external_dd_done: bool | None = None,
    agreement_signed: bool | None = None,
    deal_closed: bool | None = None,
    referral_source: str | None = None,
) -> InstitutionProfile | None:
    """部分更新机构字段，返回更新后的档案；找不到则返回 None。"""
    import time as _time
    updates: dict[str, Any] = {"updated_at": _time.time()}
    if name is not None:
        updates["name"] = name.strip()
    if stage is not None:
        updates["stage"] = stage
    if thermal is not None:
        updates["thermal"] = thermal
    if preferences is not None:
        updates["preferences"] = preferences
    if concerns is not None:
        updates["concerns"] = concerns
    if ai_summary is not None:
        updates["ai_summary"] = ai_summary
    if contact_name is not None:
        updates["contact_name"] = contact_name
    if contact_title is not None:
        updates["contact_title"] = contact_title
    if valuation is not None:
        updates["valuation"] = valuation
    if deal_size is not None:
        updates["deal_size"] = deal_size
    if probability is not None:
        updates["probability"] = max(0, min(100, int(probability)))
    if legal_status is not None:
        updates["legal_status"] = legal_status
    if nda_signed is not None:
        updates["nda_signed"] = int(nda_signed)
    if offline_meeting_count is not None:
        updates["offline_meeting_count"] = max(0, int(offline_meeting_count))
    if project_approved is not None:
        updates["project_approved"] = int(project_approved)
    if committee_approved is not None:
        updates["committee_approved"] = int(committee_approved)
    if onsite_dd_done is not None:
        updates["onsite_dd_done"] = int(onsite_dd_done)
    if external_dd_done is not None:
        updates["external_dd_done"] = int(external_dd_done)
    if agreement_signed is not None:
        updates["agreement_signed"] = int(agreement_signed)
    if deal_closed is not None:
        updates["deal_closed"] = int(deal_closed)
    if referral_source is not None:
        updates["referral_source"] = referral_source
    if not updates:
        return None
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [tenant_id, institution_id]
    with _conn() as c:
        cur = c.execute(
            f"UPDATE institutions SET {set_clause} WHERE tenant_id = ? AND institution_id = ?",  # noqa: S608
            vals,
        )
        c.commit()
        if cur.rowcount == 0:
            return None
        row = c.execute(
            """SELECT institution_id, tenant_id, name, stage, thermal,
                      preferences, concerns, ai_summary, updated_at, source_trace_id,
                      contact_name, contact_title, valuation, deal_size, probability, legal_status,
                      nda_signed, offline_meeting_count, project_approved, committee_approved,
                      onsite_dd_done, external_dd_done, agreement_signed, deal_closed, referral_source
               FROM institutions WHERE tenant_id = ? AND institution_id = ?""",
            (tenant_id, institution_id),
        ).fetchone()
    return row_to_profile(row) if row else None


def row_to_profile(row: tuple[Any, ...]) -> InstitutionProfile:
    return InstitutionProfile(
        institution_id=row[0],
        tenant_id=row[1],
        name=row[2],
        stage=PipelineStage(row[3]),
        thermal=InstitutionThermal(row[4]),
        preferences=row[5] or "",
        concerns=row[6] or "",
        ai_summary=row[7] or "",
        updated_at=float(row[8] or 0),
        source_trace_id=row[9],
        contact_name=row[10] if len(row) > 10 else "",
        contact_title=row[11] if len(row) > 11 else "",
        valuation=row[12] if len(row) > 12 else "",
        deal_size=row[13] if len(row) > 13 else "",
        probability=int(row[14] or 0) if len(row) > 14 else 0,
        legal_status=row[15] if len(row) > 15 else "",
        nda_signed=bool(row[16]) if len(row) > 16 else False,
        offline_meeting_count=int(row[17] or 0) if len(row) > 17 else 0,
        project_approved=bool(row[18]) if len(row) > 18 else False,
        committee_approved=bool(row[19]) if len(row) > 19 else False,
        onsite_dd_done=bool(row[20]) if len(row) > 20 else False,
        external_dd_done=bool(row[21]) if len(row) > 21 else False,
        agreement_signed=bool(row[22]) if len(row) > 22 else False,
        deal_closed=bool(row[23]) if len(row) > 23 else False,
        referral_source=row[24] if len(row) > 24 else "",
    )


def get_by_id(*, institution_id: str) -> InstitutionProfile | None:
    with _conn() as c:
        cur = c.execute(
            """SELECT institution_id, tenant_id, name, stage, thermal,
                      preferences, concerns, ai_summary, updated_at, source_trace_id,
                      contact_name, contact_title, valuation, deal_size, probability, legal_status,
                      nda_signed, offline_meeting_count, project_approved, committee_approved,
                      onsite_dd_done, external_dd_done, agreement_signed, deal_closed, referral_source
               FROM institutions WHERE institution_id = ? LIMIT 1""",
            (institution_id,),
        )
        row = cur.fetchone()
    return row_to_profile(row) if row else None


def get_by_name(*, tenant_id: str, name: str) -> InstitutionProfile | None:
    name = name.strip()
    if not name:
        return None
    with _conn() as c:
        cur = c.execute(
            """SELECT institution_id, tenant_id, name, stage, thermal,
                      preferences, concerns, ai_summary, updated_at, source_trace_id,
                      contact_name, contact_title, valuation, deal_size, probability, legal_status,
                      nda_signed, offline_meeting_count, project_approved, committee_approved,
                      onsite_dd_done, external_dd_done, agreement_signed, deal_closed, referral_source
               FROM institutions WHERE tenant_id = ? AND name = ? LIMIT 1""",
            (tenant_id, name),
        )
        row = cur.fetchone()
    return row_to_profile(row) if row else None


def _name_aliases(name: str) -> list[str]:
    parts = [name.strip()]
    if "资本" in name:
        parts.append(name.replace("资本", "").strip())
    if "中国" in name:
        parts.append(name.replace("中国", "").strip())
    if "基金" in name:
        parts.append(name.replace("基金", "").strip())
    out: list[str] = []
    for p in parts:
        if len(p) >= 2 and p not in out:
            out.append(p)
    return out


def find_matching_names(*, tenant_id: str, text: str) -> list[InstitutionProfile]:
    """返回名称出现在 text 中的机构（用于战前简报）。"""
    text = text.strip()
    if not text:
        return []
    hits: list[InstitutionProfile] = []
    seen: set[str] = set()
    for inst in list_institutions(tenant_id=tenant_id, limit=500):
        if not inst.name:
            continue
        matched = False
        for alias in _name_aliases(inst.name):
            if alias and alias in text:
                matched = True
                break
        if matched and inst.institution_id not in seen:
            hits.append(inst)
            seen.add(inst.institution_id)
    return hits


def sync_institutions_from_pitch_jobs() -> dict[str, int]:
    """
    从 pitch_jobs 表回溯补全 institutions 表（幂等，启动时自动执行）。

    扫描所有 is_roadshow=1、status='completed'、institution_id 非空且非"待确认_"
    的 pitch_jobs，对每个机构执行 upsert，stage 只升不降（pitched 为最低）。

    返回：{"synced": 新增或更新数, "skipped": 跳过数, "errors": 出错数}
    """
    from cangjie_fos.services.db_base import _connect as _pitch_connect  # noqa: PLC0415
    import logging as _logging  # noqa: PLC0415
    import uuid as _uuid  # noqa: PLC0415

    _log = _logging.getLogger(__name__)
    _stage_order = {"targeted": 0, "pitched": 1, "dd": 2, "term_sheet": 3}

    try:
        rows = _pitch_connect().execute(
            """SELECT tenant_id, institution_id, created_at
               FROM pitch_jobs
               WHERE is_roadshow = 1
                 AND status = 'completed'
                 AND institution_id != ''
               ORDER BY created_at ASC"""
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        _log.warning("sync_institutions: pitch_jobs 读取失败: %s", e)
        return {"synced": 0, "skipped": 0, "errors": 1}

    synced = skipped = errors = 0
    for row in rows:
        tenant_id = row[0] or ""
        inst_name = (row[1] or "").strip()
        created_at = float(row[2] or 0)

        if not inst_name or inst_name.startswith("待确认_") or not tenant_id:
            skipped += 1
            continue
        try:
            existing = get_by_name(tenant_id=tenant_id, name=inst_name)
            existing_order = _stage_order.get(
                existing.stage.value if existing else "", -1
            )
            pitched_order = _stage_order["pitched"]
            # 只有当现有 stage 低于 pitched 时才写入；已有更高阶段的不降级
            if existing and existing_order >= pitched_order:
                skipped += 1
                continue
            profile = InstitutionProfile(
                institution_id=existing.institution_id if existing else _uuid.uuid4().hex,
                tenant_id=tenant_id,
                name=inst_name,
                stage=PipelineStage.PITCHED,
                thermal=existing.thermal if existing else InstitutionThermal.WARM,
                preferences=existing.preferences if existing else "",
                concerns=existing.concerns if existing else "",
                ai_summary=existing.ai_summary if existing else "",
                updated_at=created_at,
                source_trace_id="startup_sync",
            )
            upsert_institution(profile)
            synced += 1
        except Exception as e:  # noqa: BLE001
            _log.warning("sync_institutions: upsert 失败 inst=%s: %s", inst_name, e)
            errors += 1

    _log.info(
        "sync_institutions_from_pitch_jobs done: synced=%d skipped=%d errors=%d",
        synced, skipped, errors,
    )
    return {"synced": synced, "skipped": skipped, "errors": errors}


def get_milestone_stats(*, tenant_id: str) -> dict[str, Any]:
    """返回里程碑计数 + 引荐方排行，供大屏使用。"""
    with _conn() as c:
        rows = c.execute(
            """SELECT nda_signed, offline_meeting_count, project_approved,
                      committee_approved, onsite_dd_done, external_dd_done,
                      agreement_signed, deal_closed, referral_source
               FROM institutions WHERE tenant_id = ?""",
            (tenant_id,),
        ).fetchall()
        total = c.execute(
            "SELECT COUNT(*) FROM institutions WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]

    nda = sum(1 for r in rows if r[0])
    # 线下交流：家数（有过线下见面的机构数）+ 总次数（所有机构 offline_meeting_count 之和）
    offline_met = sum(1 for r in rows if int(r[1] or 0) > 0)
    meeting_sum = sum(int(r[1] or 0) for r in rows)
    proj = sum(1 for r in rows if r[2])
    comm = sum(1 for r in rows if r[3])
    internal_dd = sum(1 for r in rows if r[4])
    external_dd = sum(1 for r in rows if r[5])
    agr = sum(1 for r in rows if r[6])
    closed = sum(1 for r in rows if r[7])

    from collections import Counter
    ref_counter: Counter[str] = Counter()
    for r in rows:
        src = (r[8] or "").strip()
        if src:
            ref_counter[src] += 1
    top_referrals = [
        {"source": src, "count": cnt}
        for src, cnt in ref_counter.most_common(5)
    ]

    return {
        "total_contacted": total,
        "nda_signed": nda,
        "offline_meetings": offline_met,
        "offline_meeting_sum": meeting_sum,
        "project_approved": proj,
        "onsite_dd_done": internal_dd,
        "external_dd_done": external_dd,
        "committee_approved": comm,
        "agreement_signed": agr,
        "deal_closed": closed,
        "top_referrals": top_referrals,
    }


def update_stage_by_name(*, tenant_id: str, name: str, stage: str) -> bool:
    """
    按机构名查找并更新 Pipeline 阶段。
    找不到时返回 False（不自动创建机构）。
    用于 DD 会话创建时自动推进机构阶段。
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE institutions SET stage = ?, updated_at = ? WHERE tenant_id = ? AND name = ?",
            (stage, time.time(), tenant_id, name),
        )
        c.commit()
    return cur.rowcount > 0
