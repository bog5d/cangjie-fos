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
    c.commit()
    return c


def upsert_institution(row: InstitutionProfile) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO institutions (
                institution_id, tenant_id, name, stage, thermal,
                preferences, concerns, ai_summary, updated_at, source_trace_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tenant_id, name) DO UPDATE SET
                stage=excluded.stage,
                thermal=excluded.thermal,
                preferences=excluded.preferences,
                concerns=excluded.concerns,
                ai_summary=excluded.ai_summary,
                updated_at=excluded.updated_at,
                source_trace_id=excluded.source_trace_id
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
    )
    upsert_institution(prof)
    return prof


def list_institutions(*, tenant_id: str, limit: int = 200) -> list[InstitutionProfile]:
    with _conn() as c:
        cur = c.execute(
            """SELECT institution_id, tenant_id, name, stage, thermal,
                      preferences, concerns, ai_summary, updated_at, source_trace_id
               FROM institutions WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?""",
            (tenant_id, limit),
        )
        rows = cur.fetchall()
    out: list[InstitutionProfile] = []
    for r in rows:
        out.append(
            InstitutionProfile(
                institution_id=r[0],
                tenant_id=r[1],
                name=r[2],
                stage=PipelineStage(r[3]),
                thermal=InstitutionThermal(r[4]),
                preferences=r[5] or "",
                concerns=r[6] or "",
                ai_summary=r[7] or "",
                updated_at=float(r[8] or 0),
                source_trace_id=r[9],
            )
        )
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
                      preferences, concerns, ai_summary, updated_at, source_trace_id
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
    )


def get_by_name(*, tenant_id: str, name: str) -> InstitutionProfile | None:
    name = name.strip()
    if not name:
        return None
    with _conn() as c:
        cur = c.execute(
            """SELECT institution_id, tenant_id, name, stage, thermal,
                      preferences, concerns, ai_summary, updated_at, source_trace_id
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
