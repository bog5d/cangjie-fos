"""DD-V1 期间语义（四态）—— cangjie-fos#71 R2-WP1（考生2 第二轮 WP1）。

本模块是**期间这一维度**的唯一权威口径，回答三个问题：

1. **义务这一侧说的期间是哪种语义**（四态，封闭枚举）：
   - ``EXPLICIT`` 明确年度（如 2024、2022-2024）⇒ 直接判定；
   - ``RELATIVE`` 相对期间（上一年度／近三年／最近十二个月等）⇒ **必须**结合
     **可验证的截止日期（锚点）＋报告期间**才能解释；
   - ``CURRENT`` 当前有效（执照/章程这类**无年度口径**的材料）⇒ 沿用 R1 已落地的
     CURRENT 优先语义，**不继承**段落年份；
   - ``UNKNOWN`` 期间未知（文本压根没提期间）⇒ **不猜**。
2. **材料这一侧的期间标签与义务口径对不对得上**（四态，封闭枚举）：
   ``MATCH``（对得上）／``MISMATCH``（已知且对不上）／``UNVERIFIABLE``（依据不足，
   既不能放行也不能判否）／``NOT_A_CONSTRAINT``（义务压根没提期间 ⇒ 该维度不构成门槛）。
3. **相对期间的锚点从哪来**：只认**可验证来源**（显式配置／清单声明／材料自身年度），
   **禁止**拿当前系统时间当隐式基准（见 ``ANCHOR_SOURCES`` 与模块末尾的
   ``_assert_no_system_clock`` 自证）。

★ **不新建材料匹配引擎**：本模块只判定「期间这一维度」，候选召回、主体过滤、
  版本有效性、披露权限一律仍由既有 ``dd_v1_semantic_retrieval_service`` /
  ``dd_v1_entity_service`` / ``dd_v1_policy_service`` 负责。

★ **不引入第二套材料类型表**：「当前有效」类（执照/章程）的判定由调用方按
  ``dd_v1_requirement_service.CURRENT_DOC_TYPES`` 以 ``current_doc_type=True`` 传入
  ⇒ 10 类唯一权威仍在 requirement service，本模块**不 import 任何类型表**。

★ **纯函数、零 IO、零网络、零模型**：所有入参都是明文，输出都是可 JSON 序列化的
  ``dict``／``list``／``str``（可直接进 obligations.json 与语义包）。
"""
from __future__ import annotations

import re
import sys
from typing import Any, Iterable

#: 义务侧的四种期间语义（**封闭枚举**，不得扩展）。
PERIOD_KINDS = ("EXPLICIT", "RELATIVE", "CURRENT", "UNKNOWN")

#: 义务口径 × 材料标签 的四种兼容结论（**封闭枚举**，不得扩展）。
#: - ``MATCH``：材料期间与义务口径一致（可继续判满足）；
#: - ``MISMATCH``：材料期间**已知**且与义务口径冲突（判否的依据）；
#: - ``UNVERIFIABLE``：依据不足（相对期间缺可验证锚点／材料自身无年度标注）
#:   ⇒ **既不得升格 MATCHED，也不得判成「不满足／缺失」**；
#: - ``NOT_A_CONSTRAINT``：义务压根没提期间 ⇒ 该维度不构成门槛。
COMPAT_STATUSES = ("MATCH", "MISMATCH", "UNVERIFIABLE", "NOT_A_CONSTRAINT")

#: 相对期间锚点的**可验证来源**（按优先级从高到低）。
#: ★ **没有**「当前系统时间」这一档 —— 相对期间永不以运行时刻为隐式基准。
ANCHOR_SOURCES = ("EXPLICIT_CONFIG", "CHECKLIST_DECLARATION", "MATERIAL_DATE")

#: 「当前有效」口径的三种形态（同一态 ``CURRENT`` 下的**不同判据**，不是新枚举）：
#: - ``CLASS``：该类**无年度口径**（执照/章程）⇒ 材料带不带年份都算这一类
#:   （年份是版本/备案日期，不是年度要求）；
#: - ``LATEST``：需求写的是「最新/现行」⇒ 取候选池中**年度最新**的那一份；
#: - ``LABEL``：只知道义务的期间**标签**是 CURRENT（旧数据没有更细的口径）
#:   ⇒ 只认标签同为 CURRENT 的材料（**不放宽**）。
CURRENT_MODES = ("CLASS", "LATEST", "LABEL")

_ANCHOR_PRIORITY = {src: i for i, src in enumerate(ANCHOR_SOURCES)}

FACT = "FACT"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

# ── 字面识别式 ──────────────────────────────────────────────────────────────
# 明确年度（区间 / 单年）
_RANGE_RE = re.compile(r"(\d{4})\s*年?\s*(?:至|到|[-—–~])\s*(\d{4})\s*年?")
_YEAR_SCAN_RE = re.compile(r"(20\d\d)\s*年?")
_YEAR_RE = re.compile(r"(\d{4})\s*年度?")
# 相对期间（跨度）
_REL_YEARS_RE = re.compile(r"(?:近|最近|过去)\s*([一二三四五六七八九十两\d]+)\s*年")
_REL_MONTHS_RE = re.compile(r"(?:近|最近|过去)\s*([一二三四五六七八九十两\d]+)\s*个?月")
# 相对期间（单年：上一年度 / 本年度）
_PREV_YEAR_RE = re.compile(r"(?:上一年度|上一会计年度|上年度|上一个年度|去年|上年)")
_CUR_YEAR_RE = re.compile(r"(?:本会计年度|本年度|今年|本年|当期|本报告期)")
# 「期」为单位的相对期间（无法换算成年份）
_PERIOD_UNIT_RE = re.compile(r"(?:最近|上一|上一个|本|本期)\s*(?:一|二|两|三|四|五|六|七|八|九|十|\d)*\s*期")

# ── 相对期间字面存在性（C-1 修复用）────────────────────────────────────
_REL_MARKER_RES = (_REL_YEARS_RE, _REL_MONTHS_RE, _PREV_YEAR_RE, _CUR_YEAR_RE,
                   _PERIOD_UNIT_RE)


def _has_relative_marker(text: str) -> bool:
    """文本里是否出现相对期间字面（跨度 / 上一年度 / 本年度 / 期为单位）。

    ★ C-1：相对期间语义不得被「单年 EXPLICIT」静默吞掉 —— 本函数是该判定的唯一入口。
    """
    return any(rx.search(text) for rx in _REL_MARKER_RES)
# 「当前有效」字面
_LATEST_RE = re.compile(r"(?:最新|现行有效|当前有效|目前有效|有效版本)")
# 清单/需求文本里**自带的截止日期或报告期声明**（可验证来源之一）
_DECL_DATE_RE = re.compile(
    r"(?:截止日期|截止日|截至|报告期截止|基准日|资料截止日|估值基准日)\s*[:：]?\s*"
    r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*(?:[-/月]\s*(\d{1,2})\s*日?)?")
_DECL_YEAR_RE = re.compile(
    r"(?:报告期(?:为|截止)?|报告年度|年度基准|截止日期|截止日|截至|资料截止日)\s*[:：]?\s*(\d{4})\s*年")

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_number(txt: str) -> int | None:
    """中文数字 → 阿拉伯数字（支持 十二 / 二十 / 二十三 这类写法）。"""
    s = str(txt or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if len(s) == 2 and s[0] == "十" and s[1] in _CN_NUM:
        return 10 + _CN_NUM[s[1]]
    if len(s) == 2 and s[1] == "十" and s[0] in _CN_NUM:
        return _CN_NUM[s[0]] * 10
    if len(s) == 3 and s[1] == "十" and s[0] in _CN_NUM and s[2] in _CN_NUM:
        return _CN_NUM[s[0]] * 10 + _CN_NUM[s[2]]
    return None


def _parse_date(text: str) -> tuple[int, int, int] | None:
    """解析 ``YYYY-MM-DD`` / ``YYYY/MM/DD`` / ``YYYY年M月D日`` ⇒ (y, m, d)。"""
    s = str(text or "").strip()
    m = re.match(r"^(\d{4})\s*[-/年]\s*(\d{1,2})\s*(?:[-/月]\s*(\d{1,2})\s*日?)?$", s)
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2))
    d = int(m.group(3) or 1)
    if not (1 <= mo <= 12) or not (1 <= d <= 31):
        return None
    return y, mo, d


def _month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    """月份平移（**纯整数运算**，不依赖任何时间库 ⇒ 天然不读系统时间）。"""
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _norm_anchor(anchor: dict[str, Any] | None, source: str,
                 literal: str = "") -> dict[str, Any] | None:
    """把各种形态的锚点归一成 ``{year, date, source, literal, note}``。"""
    if not anchor:
        return None
    raw_date = anchor.get("date")
    raw_year = anchor.get("year")
    year: int | None = None
    date: str | None = None
    if raw_date:
        parsed = _parse_date(str(raw_date))
        if parsed:
            year = parsed[0]
            date = "%04d-%02d-%02d" % parsed
    if year is None and raw_year is not None:
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            year = None
    if year is None:
        return None
    note = str(anchor.get("note") or "")
    if not note:
        note = "锚点年度 %d（来源：%s）" % (year, source)
    return {"year": year, "date": date, "source": source,
            "literal": str(anchor.get("literal") or literal or ""), "note": note}


# ── 1. 锚点来源 ────────────────────────────────────────────────────────────

def parse_anchor_declaration(text: str) -> dict[str, Any] | None:
    """从**需求/清单原文**里取「自带的截止日期或报告期声明」（可验证来源之一）。

    例：「请提供近三年审计报告（报告期截至 2024-12-31）」⇒
    ``{"year": 2024, "date": "2024-12-31", "source": "CHECKLIST_DECLARATION"}``。

    ★ 只认**原文里写着的**声明：没写就是没写 ⇒ 返回 ``None``（**不猜**）。
    """
    s = str(text or "")
    m = _DECL_DATE_RE.search(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        d = int(m.group(3) or 1)
        if not (1 <= mo <= 12) or not (1 <= d <= 31):
            return None
        return {"year": y, "date": "%04d-%02d-%02d" % (y, mo, d),
                "source": "CHECKLIST_DECLARATION", "literal": m.group(0),
                "note": "锚点取自原文声明「%s」" % m.group(0)}
    m = _DECL_YEAR_RE.search(s)
    if m:
        y = int(m.group(1))
        return {"year": y, "date": None, "source": "CHECKLIST_DECLARATION",
                "literal": m.group(0),
                "note": "锚点取自原文声明「%s」" % m.group(0)}
    return None


def resolve_anchor(*, config_anchor: dict[str, Any] | None = None,
                   declared_anchor: dict[str, Any] | None = None,
                   material_years: Iterable[Any] = ()) -> dict[str, Any] | None:
    """按优先级挑一个**可验证**锚点：显式配置 > 清单声明 > 材料自身年度。

    - ``config_anchor``：操作员/调用方显式给的锚点（``{"date": "2024-12-31"}`` 或 ``{"year": 2024}``）；
    - ``declared_anchor``：需求原文里自带的声明（``parse_anchor_declaration`` 的产物）；
    - ``material_years``：材料**自身**声明的年度（meta 的 period 字段）⇒ 取最大可验证年份。

    ★ **返回 None 的唯一含义是「没有可验证锚点」** ⇒ 相对期间必须判 UNVERIFIABLE，
      **不得**退化成「拿今天当基准」。
    """
    cands: list[dict[str, Any]] = []
    a = _norm_anchor(config_anchor, "EXPLICIT_CONFIG")
    if a:
        cands.append(a)
    a = _norm_anchor(declared_anchor, "CHECKLIST_DECLARATION")
    if a:
        cands.append(a)
    years = []
    for y in material_years or ():
        try:
            yi = int(str(y).strip())
        except (TypeError, ValueError):
            continue
        if 1900 <= yi <= 2999:
            years.append(yi)
    if years:
        top = max(years)
        cands.append({"year": top, "date": None, "source": "MATERIAL_DATE",
                      "literal": str(top),
                      "note": "锚点年度取自材料自身年度（最大可验证年份 %d）" % top})
    if not cands:
        return None
    cands.sort(key=lambda c: _ANCHOR_PRIORITY.get(c["source"], len(_ANCHOR_PRIORITY)))
    return cands[0]


# ── 2. 四态解析 ────────────────────────────────────────────────────────────

def parse_period_spec(raw: str, *, current_doc_type: bool = False) -> dict[str, Any]:
    """把一段需求文本解析成**期间语义四态**（不含锚点展开）。

    返回 dict：
    ``kind``（四态之一）、``years``（已解析的绝对年度集合）、``literal``（命中的字面）、
    ``relative``（相对期间参数：span/unit/direction）、``declared_anchor``（原文自带的声明）、
    ``resolved``（相对期间是否已锚定）、``basis``、``notes``。

    ★ ``current_doc_type=True`` ⇒ 恒为 ``CURRENT``：该类**无年度口径**
      （执照/章程），**不继承**段落年份 —— R1 已落地的 CURRENT 优先语义，**不回归**。
    """
    text = str(raw or "")
    spec: dict[str, Any] = {
        "kind": "UNKNOWN", "years": [], "literal": "", "relative": None,
        "anchor": None, "declared_anchor": parse_anchor_declaration(text),
        "resolved": True, "basis": UNKNOWN, "notes": [], "latest": False,
        "current_mode": None,
    }

    if current_doc_type:
        spec.update(kind="CURRENT", literal="CURRENT", basis=FACT, current_mode="CLASS")
        spec["notes"].append("该类无年度口径（当前有效类）⇒ 期间口径为 CURRENT，不继承段落年份")
        return spec

    # ① 明确年度（区间优先于单年）
    m = _RANGE_RE.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        spec.update(kind="EXPLICIT", years=list(range(a, b + 1)), literal=m.group(0), basis=FACT)
        return spec
    years = sorted({int(y) for y in _YEAR_SCAN_RE.findall(text)})
    if len(years) >= 2:
        spec.update(kind="EXPLICIT", years=list(range(years[0], years[-1] + 1)),
                    literal="、".join(str(y) for y in years), basis=INFERRED)
        spec["notes"].append("由文中散落年份推断区间")
        return spec
    # ★ C-1 修复：相对期间字面优先于「单年 EXPLICIT」。
    # 旧序：单年分支在此直接 return ⇒ 文本同时含相对期间字面与四位年份时（例：
    # 「请提供近三年的审计报告（报告期截至2024-06-30）」）被判成 EXPLICIT(2024)，
    # 相对期间语义被静默丢弃 ⇒ build_period_spec 因 kind != RELATIVE 跳过锚点解析
    # ⇒ 相对期间无锚点可展开 ⇒ 判否且不带 abstain_reason（自信地紧）。
    # 新序：含相对期间字面时不在此判 EXPLICIT，交给下方相对期间分支（可被锚点展开）。
    # 明确区间（_RANGE_RE）仍最优先：区间本身即已声明窗口。
    if not _has_relative_marker(text):
        m = _YEAR_RE.search(text)
        if m:
            spec.update(kind="EXPLICIT", years=[int(m.group(1))], literal=m.group(0), basis=FACT)
            return spec

    # ② 相对期间（跨度）
    m = _REL_YEARS_RE.search(text)
    if m:
        span = _cn_number(m.group(1))
        if span:
            spec.update(kind="RELATIVE", literal=m.group(0), resolved=False,
                        basis="relative_unresolved",
                        relative={"span": span, "unit": "YEAR", "mode": "WINDOW"})
            spec["notes"].append("相对期间「%s」需可验证截止日期（锚点）才能展开" % m.group(0))
            return spec
    m = _REL_MONTHS_RE.search(text)
    if m:
        span = _cn_number(m.group(1))
        if span:
            spec.update(kind="RELATIVE", literal=m.group(0), resolved=False,
                        basis="unresolved",
                        relative={"span": span, "unit": "MONTH", "mode": "WINDOW"})
            spec["notes"].append("相对期间「%s」需可验证截止日期（锚点）才能展开" % m.group(0))
            return spec
    m = _PREV_YEAR_RE.search(text)
    if m:
        spec.update(kind="RELATIVE", literal=m.group(0), resolved=False,
                    basis="unresolved",
                    relative={"span": 1, "unit": "YEAR", "mode": "PREVIOUS"})
        spec["notes"].append("相对期间「%s」需可验证截止日期（锚点）才能展开" % m.group(0))
        return spec
    m = _CUR_YEAR_RE.search(text)
    if m:
        spec.update(kind="RELATIVE", literal=m.group(0), resolved=False,
                    basis="unresolved",
                    relative={"span": 1, "unit": "YEAR", "mode": "CURRENT"})
        spec["notes"].append("相对期间「%s」需可验证截止日期（锚点）才能展开" % m.group(0))
        return spec
    m = _PERIOD_UNIT_RE.search(text)
    if m:
        spec.update(kind="RELATIVE", literal=m.group(0), resolved=False,
                    basis="unresolved",
                    relative={"span": 1, "unit": "PERIOD", "mode": "PREVIOUS"})
        spec["notes"].append("期间单位为「期」，无法换算为年度 ⇒ 需人工确认")
        return spec

    # ③ 「当前有效」字面
    m = _LATEST_RE.search(text)
    if m:
        spec.update(kind="CURRENT", literal=m.group(0), basis=FACT, latest=True,
                    current_mode="LATEST")
        spec["notes"].append("「%s」口径：取候选池中年度最新的一份" % m.group(0))
        return spec

    # ④ 期间未知
    spec["basis"] = UNKNOWN
    spec["notes"].append("文本未声明期间 ⇒ 期间维度不构成门槛（不得据此判否，也不得据此升格）")
    return spec


def apply_anchor(spec: dict[str, Any], anchor: dict[str, Any] | None) -> dict[str, Any]:
    """把锚点灌进相对期间口径：能展开 ⇒ 展开成绝对年度集合；不能 ⇒ 保持未锚定。

    ★ 展开规则：
    - 跨度 N 年、方向 BACKWARD、锚定年 A ⇒ 年度集合 ``A-N+1 .. A``；
    - 跨度 N 月、方向 BACKWARD ⇒ 需要**带日**的锚点（只有年份不足以定位窗口），
      年度集合取窗口覆盖到的自然年（可能跨两个年）；
    - 单位为「期」⇒ 永远无法换算 ⇒ 保持未锚定。
    """
    out = dict(spec or {})
    if out.get("kind") != "RELATIVE":
        return out
    rel = out.get("relative") or {}
    if not anchor:
        out["anchor"] = None
        out["resolved"] = False
        return out
    a = _norm_anchor(anchor, str(anchor.get("source") or "EXPLICIT_CONFIG"))
    if not a:
        out["anchor"] = None
        out["resolved"] = False
        return out
    out["anchor"] = a
    span = int(rel.get("span") or 0)
    unit = str(rel.get("unit") or "")
    mode = str(rel.get("mode") or "WINDOW")
    if unit == "YEAR" and span >= 1 and a.get("year"):
        base = int(a["year"])
        if mode == "PREVIOUS":
            out["years"] = [base - 1]
        elif mode == "CURRENT":
            out["years"] = [base]
        else:
            out["years"] = list(range(base - span + 1, base + 1))
        out["resolved"] = True
        out["basis"] = FACT
        out["notes"].append("相对期间「%s」按锚点 %d 展开为 %s"
                            % (out.get("literal"), base,
                               "-".join(str(y) for y in out["years"])))
        return out
    if unit == "MONTH" and span >= 1 and a.get("date"):
        y, mo, _d = _parse_date(a["date"])
        # 「N 个月」按**含锚点月的最近 N 个自然月**解释（报告期间口径）
        sy, sm = _month_shift(y, mo, -(span - 1))
        out["years"] = list(range(sy, y + 1))
        out["resolved"] = True
        out["basis"] = INFERRED
        out["notes"].append("相对期间「%s」按锚点 %s 展开为 %s（窗口覆盖到的自然年）"
                            % (out.get("literal"), a["date"],
                               "-".join(str(x) for x in out["years"])))
        return out
    out["resolved"] = False
    out["basis"] = "unresolved"
    if unit == "MONTH" and a.get("year") and not a.get("date"):
        out["notes"].append("锚点只有年份，定位不了「N 个月」窗口 ⇒ 保持未锚定（不猜）")
    elif unit == "PERIOD":
        out["notes"].append("期间单位为「期」，无法换算为年度 ⇒ 保持未锚定（不猜）")
    else:
        out["notes"].append("锚点不可用 ⇒ 保持未锚定（不猜）")
    return out


def build_period_spec(raw: str, *, current_doc_type: bool = False,
                      config_anchor: dict[str, Any] | None = None,
                      material_years: Iterable[Any] = ()) -> dict[str, Any]:
    """一步到位：解析四态 + 解析锚点 + 展开相对期间。

    锚点优先级：显式配置 > 原文声明 > 材料自身年度（**永不使用系统时间**）。
    """
    spec = parse_period_spec(raw, current_doc_type=current_doc_type)
    if spec.get("kind") != "RELATIVE":
        return spec
    anchor = resolve_anchor(config_anchor=config_anchor,
                             declared_anchor=spec.get("declared_anchor"),
                             material_years=material_years)
    return apply_anchor(spec, anchor)


def spec_from_obligation(ob: dict[str, Any]) -> dict[str, Any]:
    """从一条**义务**字典推导期间语义四态（**兼容旧数据**）。

    - 有 ``period_spec``（R2-WP1 挂上的结构化口径）⇒ 直接用；
    - 没有（旧 obligations.json / 手写义务）⇒ 按既有**字符串**口径**退化**成四态：
      ``CURRENT`` ⇒ CURRENT（**标签**口径 current_mode=LABEL，不放宽）；
      四位年份 ⇒ EXPLICIT；其余（含 ``UNKNOWN``）⇒ UNKNOWN（该维度不构成门槛）。

    ★ 这是**唯一**的退化入口：语义层与 R4 校验层都走它 ⇒ 两端口径不会分叉。
    """
    spec = (ob or {}).get("period_spec")
    if isinstance(spec, dict) and spec.get("kind"):
        return dict(spec)
    raw = str((ob or {}).get("period") or "").strip()
    if raw.upper() == "CURRENT":
        out = parse_period_spec("", current_doc_type=True)
        out["current_mode"] = "LABEL"      # 旧数据只知道标签 ⇒ 只认同标签的材料
        return out
    if raw.isdigit() and len(raw) == 4:
        return parse_period_spec("%s年度" % raw)
    return parse_period_spec("")


# ── 3. 兼容判定 ────────────────────────────────────────────────────────────

def normalize_material_period(value: Any) -> dict[str, Any]:
    """材料侧期间标签归一：``2024`` / ``CURRENT`` / 未知（空串等）。"""
    s = str(value or "").strip()
    if not s:
        return {"kind": "UNKNOWN", "year": None, "raw": s}
    if s.upper() == "CURRENT":
        return {"kind": "CURRENT", "year": None, "raw": s}
    if s.isdigit() and len(s) == 4:
        return {"kind": "YEAR", "year": int(s), "raw": s}
    return {"kind": "UNKNOWN", "year": None, "raw": s}


def compatibility(spec: dict[str, Any], material_period: Any, *,
                  pool_periods: Iterable[Any] = ()) -> dict[str, Any]:
    """义务期间口径 × 材料期间标签 ⇒ 四态兼容结论。

    ★ **「依据不足」的落点永远是 ``UNVERIFIABLE``**：既不升格 MATCHED，
      也不判成「不满足／缺失」；调用方据此产出 UNCERTAIN ＋ 候选证据 ＋ abstain_reason。
    ★ **期间检查没有被取消**：明确年度口径下，年份对不上仍是 ``MISMATCH``。
    """
    sp = spec or {}
    kind = str(sp.get("kind") or "UNKNOWN")
    years = [int(y) for y in (sp.get("years") or [])]
    mp = normalize_material_period(material_period)
    res: dict[str, Any] = {
        "status": "NOT_A_CONSTRAINT", "reason": "", "abstain_reason": None,
        "obligation_kind": kind, "obligation_years": years,
        "material_period": mp["raw"], "material_period_kind": mp["kind"],
        "anchor": sp.get("anchor"), "obligation_literal": sp.get("literal", ""),
    }

    if kind == "UNKNOWN":
        res["reason"] = "义务未声明期间口径 ⇒ 期间维度不构成门槛（不得据此判否，也不得据此升格）"
        return res

    if kind == "CURRENT":
        mode = str(sp.get("current_mode") or "CLASS")
        if mode == "LATEST":
            pool_years = []
            for p in pool_periods or ():
                pm = normalize_material_period(p)
                if pm["kind"] == "YEAR":
                    pool_years.append(int(pm["year"]))
            if mp["kind"] == "YEAR" and pool_years:
                top = max(pool_years)
                if mp["year"] == top:
                    res.update(status="MATCH",
                               reason="材料年度 %d 是候选池中的最新年度" % top)
                else:
                    res.update(status="MISMATCH",
                               reason="材料年度 %d 不是候选池中的最新年度（最新为 %d）"
                                      % (mp["year"], top))
                return res
            if mp["kind"] == "CURRENT":
                res.update(status="MATCH", reason="材料为「当前有效」口径，与「最新」一致")
                return res
            res.update(status="UNVERIFIABLE",
                       reason="材料自身无年度标注且候选池无年度可比 ⇒ 无法判定是否为最新",
                       abstain_reason="材料自身无年度标注，无法判定是否为「最新」的一份")
            return res
        if mode == "LABEL":
            # 旧数据只知道义务的期间**标签**是 CURRENT ⇒ 只认标签同为 CURRENT 的材料（不放宽）
            if mp["kind"] == "CURRENT":
                res.update(status="MATCH", reason="材料标签与义务同为「当前有效」")
                return res
            if mp["kind"] == "YEAR":
                res.update(status="MISMATCH",
                           reason="材料带年度标签 %s，与「当前有效」口径不一致" % mp["raw"])
                return res
            res.update(status="UNVERIFIABLE",
                       reason="材料自身无年度标注 ⇒ 无法判定是否为「当前有效」的一份",
                       abstain_reason="材料自身无年度标注，无法判定是否为「当前有效」的一份")
            return res
        # CLASS：该类无年度口径（执照/章程）⇒ 材料自带年份不构成年度冲突
        if mp["kind"] in ("CURRENT", "YEAR"):
            res.update(status="MATCH",
                       reason="「当前有效」口径：该类无年度口径，材料自带年份不构成年度冲突")
            return res
        res.update(status="UNVERIFIABLE",
                   reason="材料自身无年度标注 ⇒ 无法判定是否为「当前有效」的一份",
                   abstain_reason="材料自身无年度标注，无法判定是否为「当前有效」的一份")
        return res

    if kind == "RELATIVE" and not sp.get("resolved"):
        res.update(status="UNVERIFIABLE",
                   reason="相对期间「%s」缺可验证截止日期（锚点）⇒ 无法判定期间是否符合"
                          % (sp.get("literal") or ""),
                   abstain_reason="相对期间「%s」缺可验证截止日期，无法判定期间是否符合"
                                  % (sp.get("literal") or ""))
        return res

    # EXPLICIT / 已锚定的 RELATIVE
    if mp["kind"] == "YEAR":
        if mp["year"] in years:
            res.update(status="MATCH",
                       reason="材料年度 %d 在要求区间 %s 内"
                              % (mp["year"], "-".join(str(y) for y in years)))
        else:
            res.update(status="MISMATCH",
                       reason="材料年度 %d 不在要求区间 %s 内"
                              % (mp["year"], "-".join(str(y) for y in years)))
        return res
    if mp["kind"] == "CURRENT":
        res.update(status="MISMATCH",
                   reason="材料为「当前有效」口径（无年度），不能满足指定年度的要求")
        return res
    res.update(status="UNVERIFIABLE",
               reason="材料自身无年度标注 ⇒ 无法判定是否属于要求年度",
               abstain_reason="材料自身无年度标注，无法判定是否属于要求年度")
    return res


# ── 4. 自证：模块内**不读系统时间** ────────────────────────────────────────

#: 禁止出现的「读当前时刻」调用（**字面量用拼接表达**，免得本自证把自己判成违规）。
_FORBIDDEN_CLOCK_CALLS = ("datetime." + "now", "date." + "today",
                          "time." + "time(", "utc" + "now(",
                          "monot" + "onic(")


def assert_no_system_clock() -> None:
    """自证：本模块源码里**没有**任何「读当前时刻」的调用。

    ★ 相对期间的基准必须来自可验证来源（显式配置／清单声明／材料自身年度），
      绝不能是「跑代码的那一天」—— 那会让同一条需求的结论随运行日期漂移。
    ★ 用例直接调本函数 ⇒ 违规会**当场炸**，而不是靠人读代码发现。
    """
    import inspect
    module_src = inspect.getsource(sys.modules[__name__])
    for bad in _FORBIDDEN_CLOCK_CALLS:
        if bad in module_src:
            raise AssertionError("期间语义模块不得读系统时间：发现 %s" % bad)
