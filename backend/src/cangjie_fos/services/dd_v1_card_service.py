"""DD-V1 结构化材料认知卡（WP2）。

为每份可解析材料建立一张**带出处**的认知卡。这是后续匹配、覆盖度计算、
组包判定的共同数据底座。

**核心纪律：所有字段区分 FACT / INFERRED / UNKNOWN，不能推断的内容不得编造。**

- ``FACT``     —— 从文件内容或文件系统**直接读到**的值，附证据位置。
- ``INFERRED`` —— 由确定性规则**推导**的值（如从目录名推主体），必须写明推导规则。
- ``UNKNOWN``  —— 取不到证据。**值为空字符串，绝不用「猜一个像样的」填充。**

特别地，以下字段在无视觉/OCR 能力时**必须留 UNKNOWN**，不得臆测：

- ``seal_status``（签章状态）：没有图像核验就不知道盖没盖章。
- ``sensitivity``（敏感等级）：没有制度依据就不能编等级。
- ``group``（所属集团）：目录名不等于法律上的集团，需权威名单才能定。

一个文件可覆盖多个用途、可关联其他附件，故 `purpose` / `related_files`
按多值存储；「关联」只记录**确定观察到**的同目录/同名关联，**不臆造**关系。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from cangjie_fos.services import dd_v1_manifest_service as mf

logger = logging.getLogger(__name__)

# ── 出处分类 ────────────────────────────────────────────────────────────────
FACT = "FACT"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

# 认知卡字段全集（Schema 固定，便于校验与后续映射）
CARD_FIELDS = (
    "doc_type",        # 文件类型
    "title",           # 材料标题
    "entity",          # 公司主体
    "group",           # 所属集团
    "fiscal_period",   # 年度或期间
    "sign_date",       # 签署日期
    "effective_date",  # 生效日期
    "version",         # 版本
    "seal_status",     # 签章状态
    "purpose",         # 材料用途
    "proves",          # 证明内容
    "key_facts",       # 关键事实
    "related_files",   # 相关文件
    "sensitivity",     # 敏感等级
    "source_trust",    # 可信来源
    "parse_complete",  # 解析完整性
    "evidence_loc",    # 证据位置
)

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_material_cards (
    file_id         TEXT PRIMARY KEY,
    library_id      TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    entity          TEXT NOT NULL DEFAULT '',
    group_name      TEXT NOT NULL DEFAULT '',
    fiscal_period   TEXT NOT NULL DEFAULT '',
    sign_date       TEXT NOT NULL DEFAULT '',
    effective_date  TEXT NOT NULL DEFAULT '',
    version         TEXT NOT NULL DEFAULT '',
    seal_status     TEXT NOT NULL DEFAULT '',
    purpose         TEXT NOT NULL DEFAULT '',
    proves          TEXT NOT NULL DEFAULT '',
    key_facts       TEXT NOT NULL DEFAULT '',
    related_files   TEXT NOT NULL DEFAULT '',
    sensitivity     TEXT NOT NULL DEFAULT '',
    source_trust    TEXT NOT NULL DEFAULT '',
    parse_complete  INTEGER NOT NULL DEFAULT 0,
    evidence_loc    TEXT NOT NULL DEFAULT '',
    fields_json     TEXT NOT NULL DEFAULT '{}',
    card_status     TEXT NOT NULL DEFAULT 'draft',
    built_at        REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_cards_entity
    ON dd_v1_material_cards(library_id, entity);
CREATE INDEX IF NOT EXISTS idx_dd_v1_cards_period
    ON dd_v1_material_cards(library_id, fiscal_period);

-- 正文缓存（Markdown / 抽取文本）。存受控 Data Plane，不回写材料源目录。
CREATE TABLE IF NOT EXISTS dd_v1_text_cache (
    file_id        TEXT PRIMARY KEY,
    library_id     TEXT NOT NULL,
    method         TEXT NOT NULL DEFAULT '',
    text           TEXT NOT NULL DEFAULT '',
    truncated      INTEGER NOT NULL DEFAULT 0,
    original_chars INTEGER NOT NULL DEFAULT 0,
    built_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_text_cache_lib
    ON dd_v1_text_cache(library_id);

-- FTS5 混合检索索引（SCP v3.8：优先 FTS5/BM25 + 关键词 + 业务字段过滤）
CREATE VIRTUAL TABLE IF NOT EXISTS dd_v1_material_fts USING fts5(
    file_id UNINDEXED,
    library_id UNINDEXED,
    rel_path,
    title,
    entity,
    body,
    tokenize='unicode61'
);
"""

# 正则：仅取**带明确标签**的值，避免从自由文本里误抓
_SIGN_DATE_RE = re.compile(r"签[署订](?:日期|时间|于)\s*[:：]?\s*(\d{4}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2})")
_EFFECTIVE_RE = re.compile(r"(?:生效日期|生效时间|自\s*)(\d{4}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2})")
_PERIOD_RE = re.compile(r"(\d{4})\s*(?:年度|财年|年)")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# 材料用途词典（确定性关键词映射，只标记「材料自称是什么」，不推断法律效力）
_PURPOSE_KEYWORDS = {
    "审计报告": "审计结论", "财务报表": "财务状况", "资产负债表": "财务状况",
    "利润表": "经营成果", "现金流量表": "现金流", "纳税申报": "税务合规",
    "营业执照": "主体存续", "公司章程": "治理结构", "验资": "出资证明",
    "股东会决议": "决策记录", "董事会决议": "决策记录", "专利": "知识产权",
    "商标": "知识产权", "商标注册证": "知识产权", "发明专利": "知识产权",
    "劳动合同": "用工合规", "社保": "用工合规", "股权激励": "激励安排",
    "商业计划书": "融资材料", "尽职调查问卷": "尽调应答",
}

# ── 附件关系识别（WP6 前补齐：必备附件覆盖是硬门槛要求的第四维）──────────
# 三条**确定性**规则，只认文件名与目录结构里能直接观察到的关系：
#   1. 附件自述：文件名含「附件 / 附表 / 明细 / 签字页 / 盖章页」等
#   2. 同根不同扩展名：同目录下主文件名相同、扩展名不同 → 互为附件
#   3. 同前缀编号：同目录同前缀 → 一组材料
# **判定为 INFERRED 而非 FACT**：这是从文件名结构推出的关系，
# 必须能被人一眼核对；不能因为「文件挨在一起」就断言它们是同一份材料的附件。
_ATTACHMENT_WORDS = re.compile(
    r"(附件|附表|附页|明细|签字页|签章页|盖章页|附录|Schedule|Annex)")
def _attach_key(name: str) -> str:
    """去掉版本/年份/编号等噪音后的主文件名，用于「同根不同扩展名」判断。

    **复用** ``dd_index_service.clean_filename``——它已经处理了年份、版本号
    与「最终版/终稿/副本/扫描件/盖章版/签字版/修订」等噪音词，
    不另立第二套文件名归一化标准（复用优先）。
    """
    from cangjie_fos.services.dd_index_service import clean_filename  # noqa: PLC0415
    base = clean_filename(name or "")
    # clean_filename 不处理「附表/明细/签字页」这类附件标记词，
    # 不剥掉的话主文件名对不上，附件关系就永远识别不出来。
    base = _ATTACHMENT_WORDS.sub("", base)
    base = re.sub(r"[\s_\-()（）\[\]【】]+", "", base)
    return base.strip().lower()


def detect_related_files(rel_path: str, siblings: list[dict]) -> list[str]:
    """识别附件关系，返回关联文件的相对路径。

    ``siblings`` 为同目录下的材料条目（含 file_name / rel_path）。
    **只返回观察到的关系，不臆造**；判不出来就返回空列表并留 UNKNOWN。
    """
    if not rel_path:
        return []
    cur = Path(rel_path)
    cur_name = cur.name
    cur_key = _attach_key(cur_name)
    out: list[str] = []

    for s in siblings:
        other = s.get("rel_path") or s.get("file_name") or ""
        if not other or other == rel_path:
            continue
        op = Path(other)
        # 只看同目录，跨目录不猜
        if op.parent != cur.parent:
            continue
        reason = None
        if _ATTACHMENT_WORDS.search(cur_name) or _ATTACHMENT_WORDS.search(op.name):
            # 任一方自称附件且共享主文件名 → 关联
            if cur_key and cur_key == _attach_key(op.name):
                reason = "同目录、主文件名相同且含附件标记词"
        if reason is None and cur_key and cur_key == _attach_key(op.name) \
                and op.suffix.lower() != cur.suffix.lower():
            reason = "同目录、主文件名相同、扩展名不同"
        if reason:
            out.append(other)
    return out


_MATERIAL_PUNCT_RE = re.compile(r"[\s　]+")


def bigram_expand(text: str) -> str:
    """中文 bigram 展开，供 FTS5 建索引与查询使用。

    **为什么必须做**：SQLite FTS5 的 `unicode61` 把连续汉字当作**单个 token**，
    实测 `"本报告涉及知识产权与专利布局"` 用 `MATCH '专利'` 命中 **0**；
    `trigram` 又要求查询词 ≥3 字符，2 字中文词同样搜不到。
    而尽调材料全是中文，检索词 2 字最常见（「专利」「审计」「商标」），
    因此**索引侧与查询侧都必须展开成 bigram**，FTS5 才能真正可用。

    查询侧用短语查询还原子串连续性（见 :func:`to_fts_query`）。
    与既有 ``dd_match_service._prefilter_files_for_batch`` 的汉字 bigram 思路一致，
    不另立第二套中文分词标准（复用优先）。
    """
    if not text:
        return ""
    s = _MATERIAL_PUNCT_RE.sub("", str(text))
    if len(s) <= 1:
        return s
    return " ".join(s[i:i + 2] for i in range(len(s) - 1))


def to_fts_query(q: str) -> str:
    """把用户查询转成 FTS5 短语查询。

    展开成 bigram 后必须用短语（``"…"``）包起来，否则多字词会被当成单个
    token 而搜不到（实测 ``MATCH '知识产权'`` 对 bigram 索引命中 0）。
    """
    bg = bigram_expand(q)
    if not bg:
        return '""'
    return '"' + bg.replace('"', "") + '"'


@dataclass
class CardBuilder:
    """认知卡构建器。所有赋值都必须经由 :meth:`set`，以强制携带出处。"""
    fields: dict = field(default_factory=dict)

    def __init__(self) -> None:
        self.fields = {k: {"value": "", "provenance": UNKNOWN, "evidence": []}
                       for k in CARD_FIELDS}

    def set(self, name: str, value, provenance: str, evidence: list | None = None) -> None:
        """写入字段并强制记录出处。

        空值一律降级为 UNKNOWN，**但保留 evidence**——
        「为什么不知道」和「知道什么」同样重要：没有说明的 UNKNOWN
        会让复核者无法区分「确实没有」与「忘了做」。
        """
        if name not in self.fields:
            raise KeyError(f"未知认知卡字段：{name}")
        if provenance not in (FACT, INFERRED, UNKNOWN):
            raise ValueError(f"非法出处分类：{provenance}")
        if value in (None, "", [], {}):
            self.fields[name] = {
                "value": "", "provenance": UNKNOWN, "evidence": evidence or [],
            }
            return
        self.fields[name] = {
            "value": value,
            "provenance": provenance,
            "evidence": evidence or [],
        }

    def multi(self, name: str, values: list, provenance: str,
              evidence: list | None = None) -> None:
        """多值字段（用途/关键事实/相关文件）。

        空列表保持为 ``[]`` 而不是降级成 ``""``——多值字段就是多值类型，
        消费方应当能直接迭代，不必先判类型。这也是消费侧的判据：
        ``[]`` 表示「观察后确实没有」，``""`` 会被误当成未赋值。
        """
        clean = [v for v in (values or []) if v]
        if not clean:
            self.fields[name] = {
                "value": [], "provenance": UNKNOWN, "evidence": evidence or [],
            }
            return
        self.set(name, clean, provenance, evidence)

    def as_dict(self) -> dict:
        return self.fields


def _card_conn(db_path: Path | None = None):
    """认知卡与 FTS 共用 Manifest 库的连接（同一进程、同一把写锁）。"""
    return mf._connect(db_path)


def _ensure_schema(conn) -> None:
    conn.executescript(_DDL)
    conn.commit()


def _extract_labels(text: str) -> dict:
    """从正文里抽**带标签**的确定值；抽不到就交回 UNKNOWN。"""
    out: dict[str, tuple[str, str]] = {}
    if not text:
        return out
    m = _SIGN_DATE_RE.search(text)
    if m:
        out["sign_date"] = (m.group(1).strip(), "正文中带「签署日期/签署于」标签的取值")
    m = _EFFECTIVE_RE.search(text)
    if m:
        out["effective_date"] = (m.group(1).strip(), "正文中带「生效日期/生效时间」标签的取值")
    m = _PERIOD_RE.search(text)
    if m:
        out["fiscal_period"] = (m.group(1), "正文中带「年度/财年」标签的取值")
    return out


def _siblings_of(conn, manifest_row: dict) -> list[dict]:
    """取同目录下、同材料库内的其他文件，供附件关系识别使用。"""
    rel = manifest_row.get("rel_path") or ""
    parent = str(Path(rel).parent)
    if parent == ".":
        parent = ""
    rows = conn.execute(
        """SELECT file_name, rel_path FROM dd_v1_manifest
           WHERE library_id=? AND deleted_at IS NULL AND file_id<>?
             AND (CASE WHEN instr(rel_path,'/')>0
                       THEN substr(rel_path,1,instr(rel_path,'/')-1) ELSE '' END)=?
           LIMIT 500""",
        (manifest_row["library_id"], manifest_row["file_id"], parent),
    ).fetchall()
    return [dict(r) for r in rows]


def build_card(
    manifest_row: dict,
    text: str = "",
    db_path: Path | None = None,
) -> dict:
    """为单份材料构建认知卡并落库，同时写入 FTS 索引。

    ``manifest_row`` 来自 ``dd_v1_manifest``；``text`` 为已抽取正文（可为空）。
    纯确定性，**零 LLM 调用**——认知卡的事实层不允许由模型编造。
    """
    conn = _card_conn(db_path)
    _ensure_schema(conn)

    rel = manifest_row["rel_path"]
    file_name = manifest_row.get("file_name") or Path(rel).name
    ext = manifest_row.get("ext") or Path(rel).suffix.lower()
    b = CardBuilder()

    # ── FACT：文件系统直接可读 ──────────────────────────────────────────
    b.set("doc_type", ext.lstrip("."), FACT,
          [{"kind": "fs_ext", "loc": rel}])

    stem = Path(file_name).stem
    b.set("title", stem, INFERRED,
          [{"kind": "filename_stem", "loc": rel, "rule": "取文件名去扩展名；可能是草稿名，非正式标题"}])

    # ── INFERRED：主体来自目录结构（**不是法律事实**）────────────────────
    parts = Path(rel).parts
    entity = ""
    entity_evidence = []
    if len(parts) > 1:
        candidate = parts[-2]
        if candidate and not candidate.startswith("."):
            entity = candidate
            entity_evidence = [{
                "kind": "path_segment",
                "loc": rel,
                "rule": "取相对路径的父目录名作为主体线索；未经权威名单核验，不等于法律主体",
            }]
    b.set("entity", entity, INFERRED, entity_evidence)

    # ── 所属集团：无权威名单，一律 UNKNOWN（不编造）─────────────────────
    b.set("group", "", UNKNOWN,
          [{"kind": "missing_authority",
            "note": "需权威集团成员名单或工商登记信息才能认定，当前无可用依据，按 UNKNOWN 处理"}])

    # ── 版本：仅文件名线索，INFERRED ────────────────────────────────────
    v_hint, y_hint = mf.iter_version_hints(file_name)
    b.set("version", v_hint, INFERRED if v_hint else UNKNOWN,
          [{"kind": "filename_token", "loc": rel,
            "rule": "从文件名抽取版本词；「最终版」等词不构成业务有效性证明"}] if v_hint else [])

    # ── 正文标签值：FACT（因为有明文标签）───────────────────────────────
    labels = _extract_labels(text)
    for key in ("sign_date", "effective_date", "fiscal_period"):
        if key in labels:
            value, note = labels[key]
            b.set(key, value, FACT,
                  [{"kind": "content_label", "loc": f"{rel}#正文", "rule": note}])
        elif key == "fiscal_period" and y_hint:
            b.set(key, y_hint, INFERRED,
                  [{"kind": "filename_year", "loc": rel,
                    "rule": "仅文件名含年份，正文未见「年度」标签"}])
        else:
            b.set(key, "", UNKNOWN)

    # ── 签章状态：无视觉核验能力，必须 UNKNOWN ──────────────────────────
    b.set("seal_status", "", UNKNOWN,
          [{"kind": "no_capability",
            "note": "无图像/印章核验能力，不得据文件名猜测是否盖章"}])

    # ── 敏感等级：无制度依据，必须 UNKNOWN ──────────────────────────────
    b.set("sensitivity", "", UNKNOWN,
          [{"kind": "no_policy",
            "note": "未接入披露政策分级规则，不得自行判定敏感等级"}])

    # ── 材料用途：关键词命中即标记，但仅代表「材料自称」 ─────────────────
    hits = []
    haystack = f"{stem}\n{text[:4000]}"
    for kw, purpose in _PURPOSE_KEYWORDS.items():
        if kw in haystack:
            hits.append(f"{kw}→{purpose}")
    b.multi("purpose", hits, FACT if hits else UNKNOWN,
            [{"kind": "keyword_hit", "loc": rel,
              "rule": "关键词命中即记录；仅描述材料自称用途，不代表已核实法律效力"}] if hits else [])

    # ── 证明内容 / 关键事实：无抽取能力时留空，不编造 ────────────────────
    b.set("proves", "", UNKNOWN,
          [{"kind": "not_extracted", "note": "证明内容需人工或后续 WP 的语义抽取，当前不臆造"}])
    key_facts = []
    if text:
        heads = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and len(ln.strip()) <= 40][:5]
        key_facts = heads
    b.multi("key_facts", key_facts, FACT if key_facts else UNKNOWN,
            [{"kind": "content_heading", "loc": rel, "rule": "正文前若干短行标题"}] if key_facts else [])

    # ── 相关文件：只记「同目录可观察」的附件关系 ────────────────────────
    related = detect_related_files(rel, _siblings_of(conn, manifest_row))
    b.multi("related_files", related, INFERRED if related else UNKNOWN,
            [{"kind": "path_structure", "loc": rel,
              "rule": "同目录 + 主文件名相同（含附件标记词或扩展名不同）；"
                      "这是从文件名结构推出的关系，**非法律事实**，需人工确认"}]
            if related else [{"kind": "not_resolved",
                              "note": "未观察到可确定的附件关系，不臆造"}])

    # ── 可信来源：来源可观察 → INFERRED ────────────────────────────────
    b.set("source_trust", manifest_row.get("source_hint") or "内部材料库",
          INFERRED, [{"kind": "scan_source", "loc": rel}])

    # ── 解析完整性：由 Manifest 解析状态直接决定，**不可含糊** ────────────
    ps = manifest_row.get("parse_status", "")
    complete = ps == mf.PARSE_OK
    b.set("parse_complete", "complete" if complete else ("partial" if ps == mf.PARSE_PARTIAL else "incomplete"),
          FACT,
          [{"kind": "manifest_status", "loc": rel,
            "rule": f"parse_status={ps}, method={manifest_row.get('parse_method','')}, "
                    f"truncated={manifest_row.get('truncated', 0)}"}])

    # ── 证据位置 ────────────────────────────────────────────────────────
    b.set("evidence_loc", rel, FACT, [{"kind": "fs_path", "loc": rel}])

    card = b.as_dict()
    now = time.time()
    conn.execute(
        """INSERT INTO dd_v1_material_cards
           (file_id, library_id, rel_path, doc_type, title, entity, group_name,
            fiscal_period, sign_date, effective_date, version, seal_status,
            purpose, proves, key_facts, related_files, sensitivity, source_trust,
            parse_complete, evidence_loc, fields_json, card_status, built_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',?,?)
           ON CONFLICT(file_id) DO UPDATE SET
             doc_type=excluded.doc_type, title=excluded.title, entity=excluded.entity,
             group_name=excluded.group_name, fiscal_period=excluded.fiscal_period,
             sign_date=excluded.sign_date, effective_date=excluded.effective_date,
             version=excluded.version, seal_status=excluded.seal_status,
             purpose=excluded.purpose, proves=excluded.proves,
             key_facts=excluded.key_facts, related_files=excluded.related_files,
             sensitivity=excluded.sensitivity, source_trust=excluded.source_trust,
             parse_complete=excluded.parse_complete, evidence_loc=excluded.evidence_loc,
             fields_json=excluded.fields_json, updated_at=excluded.updated_at""",
        (
            manifest_row["file_id"], manifest_row["library_id"], rel,
            _v(card, "doc_type"), _v(card, "title"), _v(card, "entity"),
            _v(card, "group"), _v(card, "fiscal_period"), _v(card, "sign_date"),
            _v(card, "effective_date"), _v(card, "version"), _v(card, "seal_status"),
            json.dumps(_v(card, "purpose"), ensure_ascii=False),
            _v(card, "proves"),
            json.dumps(_v(card, "key_facts"), ensure_ascii=False),
            json.dumps(_v(card, "related_files"), ensure_ascii=False),
            _v(card, "sensitivity"), _v(card, "source_trust"),
            1 if _v(card, "parse_complete") == "complete" else 0,
            _v(card, "evidence_loc"),
            json.dumps(card, ensure_ascii=False), now, now,
        ),
    )

    # FTS 索引（幂等：先删后插）。中文需 bigram 展开，见 bigram_expand 说明。
    conn.execute("DELETE FROM dd_v1_material_fts WHERE file_id=?", (manifest_row["file_id"],))
    conn.execute(
        """INSERT INTO dd_v1_material_fts
           (file_id, library_id, rel_path, title, entity, body)
           VALUES (?,?,?,?,?,?)""",
        (manifest_row["file_id"], manifest_row["library_id"],
         bigram_expand(rel), bigram_expand(_v(card, "title")),
         bigram_expand(_v(card, "entity")),
         bigram_expand((text or "")[:20000])),
    )
    conn.commit()
    return card


def search_materials(
    library_id: str,
    query: str,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    """中文友好的材料检索（FTS5 + bigram 短语）。

    与既有实现的区别：旧 DD 路径**没有真实全文引擎**
    （`api/routes/assets.py:383` 的「BM25」只是注释，实为 bigram 预筛 + LLM 批判），
    本函数是真 FTS5 虚表，可在无 LLM、无 API key 的环境下独立召回。
    """
    conn = _card_conn(db_path)
    _ensure_schema(conn)
    if not query.strip():
        return []
    rows = conn.execute(
        """SELECT f.file_id, bm25(dd_v1_material_fts) AS score
           FROM dd_v1_material_fts f
           WHERE dd_v1_material_fts MATCH ? AND library_id=?
           ORDER BY score LIMIT ?""",
        (to_fts_query(query), library_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        # rel_path 必须回表取真值：FTS 表里存的是 bigram 展开串，直接取会得到乱码
        card = get_card(r["file_id"], db_path=db_path)
        out.append({
            "file_id": r["file_id"],
            "rel_path": card["rel_path"] if card else "",
            "score": round(r["score"], 6),
            "title": card["title"] if card else "",
            "entity": card["entity"] if card else "",
        })
    return out


def cache_text(
    file_id: str,
    library_id: str,
    text: str,
    method: str = "",
    truncated: bool = False,
    original_chars: int = 0,
    db_path: Path | None = None,
) -> None:
    """写入正文缓存（受控 Data Plane，不回写材料源目录）。"""
    conn = _card_conn(db_path)
    _ensure_schema(conn)
    conn.execute(
        """INSERT INTO dd_v1_text_cache
           (file_id, library_id, method, text, truncated, original_chars, built_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(file_id) DO UPDATE SET
             method=excluded.method, text=excluded.text,
             truncated=excluded.truncated, original_chars=excluded.original_chars,
             built_at=excluded.built_at""",
        (file_id, library_id, method, text or "", 1 if truncated else 0,
         original_chars or 0, time.time()),
    )
    conn.commit()


def get_cached_text(file_id: str, db_path: Path | None = None) -> str:
    conn = _card_conn(db_path)
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT text FROM dd_v1_text_cache WHERE file_id=?", (file_id,)
    ).fetchone()
    return row["text"] if row else ""


def _v(card: dict, name: str):
    return card.get(name, {}).get("value", "")


def build_cards_for_library(
    library_id: str,
    db_path: Path | None = None,
    limit: int = 500,
    use_text_cache: bool = True,
) -> dict:
    """批量为库内材料建卡。

    正文来源：``dd_v1_text_cache``（由 ``dd_v1_parser_service`` 写入）。
    **未缓存正文的材料照样建卡**，但依赖正文的字段（签署日期、期间、关键事实）
    一律留 UNKNOWN —— 宁可不知道，不臆造。
    """
    conn = _card_conn(db_path)
    _ensure_schema(conn)
    rows = [dict(r) for r in conn.execute(
        """SELECT m.* FROM dd_v1_manifest m
           WHERE m.library_id=? AND m.deleted_at IS NULL
           ORDER BY m.rel_path LIMIT ?""",
        (library_id, limit),
    )]
    built = 0
    with_text = 0
    for row in rows:
        text = get_cached_text(row["file_id"], db_path=db_path) if use_text_cache else ""
        if text:
            with_text += 1
        build_card(row, text=text, db_path=db_path)
        built += 1
    return {
        "library_id": library_id,
        "built": built,
        "from_rows": len(rows),
        "with_cached_text": with_text,
        "without_text": built - with_text,
    }


def get_card(file_id: str, db_path: Path | None = None) -> dict | None:
    conn = _card_conn(db_path)
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM dd_v1_material_cards WHERE file_id=?", (file_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["fields"] = json.loads(d.pop("fields_json") or "{}")
    return d


def card_coverage(library_id: str, db_path: Path | None = None) -> dict:
    """认知卡出处分布——用来判断「有多少字段其实我们并不知道」。

    这是**认知完备性的诚实度量**，不是业务效果指标。
    """
    conn = _card_conn(db_path)
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT fields_json FROM dd_v1_material_cards WHERE library_id=?",
        (library_id,),
    ).fetchall()
    tally = {FACT: 0, INFERRED: 0, UNKNOWN: 0}
    per_field = {k: {FACT: 0, INFERRED: 0, UNKNOWN: 0} for k in CARD_FIELDS}
    for r in rows:
        card = json.loads(r["fields_json"] or "{}")
        for k, v in card.items():
            p = v.get("provenance", UNKNOWN)
            tally[p] = tally.get(p, 0) + 1
            if k in per_field:
                per_field[k][p] = per_field[k].get(p, 0) + 1
    total = max(len(rows), 1)
    return {
        "library_id": library_id,
        "cards": len(rows),
        "by_provenance": tally,
        "fact_ratio": round(tally[FACT] / (total * len(CARD_FIELDS)), 4),
        "unknown_fields": sum(1 for k, c in per_field.items() if c[UNKNOWN] == len(rows) and len(rows)),
        "per_field": per_field,
    }
