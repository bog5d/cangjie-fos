"""需求03 — 模板的 DB 存取层（在线编辑 + 多套模板 + 跨轮次复用）。

设计：
  - 内置标准模板（template_id='standard'）首次访问时从 package_template.py 种子化；
    可在线编辑，也可一键 reset 恢复默认。
  - 用户可另存任意多套模板（如「A轮精简包」「并购尽调包」），跨轮次/跨机构复用。
  - 模板是 tenant 内共享资产（材料库共享哲学一致）。
  - 编辑采用「整体替换 items」：前端编辑器一次提交全量条目，简单且无并发歧义。
"""
from __future__ import annotations

import time
import uuid

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.package_template import get_standard_template

BUILTIN_ID = "standard"
BUILTIN_NAME = "标准数据包（内置）"


def ensure_builtin(tenant_id: str = "default") -> None:
    """确保内置标准模板存在（幂等）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT template_id FROM package_templates WHERE template_id = ? AND tenant_id = ?",
            (BUILTIN_ID, tenant_id),
        ).fetchone()
        if row:
            return
        now = time.time()
        conn.execute(
            """INSERT INTO package_templates
               (template_id, tenant_id, name, is_builtin, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (BUILTIN_ID, tenant_id, BUILTIN_NAME, now, now),
        )
        _insert_items(conn, BUILTIN_ID, tenant_id, get_standard_template())


def _insert_items(conn, template_id: str, tenant_id: str, items: list[dict]) -> None:
    for i, it in enumerate(items):
        conn.execute(
            """INSERT INTO package_template_items
               (id, template_id, tenant_id, item_no, category, requirement, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), template_id, tenant_id, str(i + 1),
             it.get("category", ""), it["requirement"],
             it.get("importance", "normal")),
        )


def list_templates(tenant_id: str = "default") -> list[dict]:
    ensure_builtin(tenant_id)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT t.template_id, t.name, t.is_builtin, t.created_at, t.updated_at,
                      COUNT(i.id) AS item_count
               FROM package_templates t
               LEFT JOIN package_template_items i ON i.template_id = t.template_id
                    AND i.tenant_id = t.tenant_id
               WHERE t.tenant_id = ?
               GROUP BY t.template_id
               ORDER BY t.is_builtin DESC, t.created_at""",
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_template_items(template_id: str, tenant_id: str = "default") -> list[dict]:
    ensure_builtin(tenant_id)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT item_no, category, requirement, importance
               FROM package_template_items
               WHERE template_id = ? AND tenant_id = ?
               ORDER BY CAST(item_no AS INTEGER)""",
            (template_id, tenant_id),
        ).fetchall()
    return [dict(r) for r in rows]


def template_exists(template_id: str, tenant_id: str = "default") -> bool:
    ensure_builtin(tenant_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM package_templates WHERE template_id = ? AND tenant_id = ?",
            (template_id, tenant_id),
        ).fetchone()
    return bool(row)


def create_template(
    name: str,
    tenant_id: str = "default",
    copy_from: str | None = None,
) -> dict:
    """新建模板；copy_from 指定时复制其条目（"另存为"语义）。"""
    ensure_builtin(tenant_id)
    template_id = str(uuid.uuid4())
    now = time.time()
    items = get_template_items(copy_from, tenant_id) if copy_from else []
    with _connect() as conn:
        conn.execute(
            """INSERT INTO package_templates
               (template_id, tenant_id, name, is_builtin, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            (template_id, tenant_id, name.strip() or "未命名模板", now, now),
        )
        if items:
            _insert_items(conn, template_id, tenant_id, items)
    return {"template_id": template_id, "name": name, "item_count": len(items)}


def replace_items(template_id: str, items: list[dict], tenant_id: str = "default") -> int:
    """整体替换模板条目（在线编辑器一次提交全量）。返回新条目数。

    校验：requirement 非空；importance 规整为 core/normal；item_no 重新连续编号。
    """
    cleaned: list[dict] = []
    for it in items:
        req = str(it.get("requirement", "")).strip()
        if not req:
            continue
        imp = str(it.get("importance", "normal")).strip().lower()
        cleaned.append({
            "category": str(it.get("category", "")).strip() or "未分类",
            "requirement": req,
            "importance": imp if imp in ("core", "normal") else "normal",
        })
    with _connect() as conn:
        conn.execute(
            "DELETE FROM package_template_items WHERE template_id = ? AND tenant_id = ?",
            (template_id, tenant_id),
        )
        _insert_items(conn, template_id, tenant_id, cleaned)
        conn.execute(
            "UPDATE package_templates SET updated_at = ? WHERE template_id = ? AND tenant_id = ?",
            (time.time(), template_id, tenant_id),
        )
    return len(cleaned)


def rename_template(template_id: str, name: str, tenant_id: str = "default") -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE package_templates SET name = ?, updated_at = ? "
            "WHERE template_id = ? AND tenant_id = ? AND is_builtin = 0",
            (name.strip() or "未命名模板", time.time(), template_id, tenant_id),
        )


def delete_template(template_id: str, tenant_id: str = "default") -> bool:
    """删除非内置模板。内置模板不可删（只可 reset）。"""
    if template_id == BUILTIN_ID:
        return False
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM package_templates WHERE template_id = ? AND tenant_id = ? AND is_builtin = 0",
            (template_id, tenant_id),
        )
        conn.execute(
            "DELETE FROM package_template_items WHERE template_id = ? AND tenant_id = ?",
            (template_id, tenant_id),
        )
    return cur.rowcount > 0


def reset_builtin(tenant_id: str = "default") -> int:
    """把内置标准模板恢复为 package_template.py 的默认内容。返回条目数。"""
    ensure_builtin(tenant_id)
    items = get_standard_template()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM package_template_items WHERE template_id = ? AND tenant_id = ?",
            (BUILTIN_ID, tenant_id),
        )
        _insert_items(conn, BUILTIN_ID, tenant_id, items)
        conn.execute(
            "UPDATE package_templates SET updated_at = ? WHERE template_id = ? AND tenant_id = ?",
            (time.time(), BUILTIN_ID, tenant_id),
        )
    return len(items)
