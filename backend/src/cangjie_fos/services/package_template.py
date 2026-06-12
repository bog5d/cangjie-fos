"""需求03 — 标准数据包模板（融资材料的"标准答案清单"）。

与尽调台的区别：
  - 尽调台：机构发来「他们的清单」→ 我们匹配
  - 数据包补全：对照「我们自己的标准模板」→ 看自己还缺哪些维度

模板维度来自实战（财务/法务/业务），每条是一个"应当具备的材料"。
importance: core(投资人必看) / normal(应备) —— 影响缺口提示的优先级。

模板是机构无关的全局资产，可跨轮次/跨项目复用。后续可做成可编辑（存库），
当前先内置一份权威默认模板，覆盖最常见的融资尽调材料维度。
"""
from __future__ import annotations

# 每条：(category, requirement, importance)
_STANDARD_ITEMS: list[tuple[str, str, str]] = [
    # ── 财务 ────────────────────────────────────────────────
    ("财务", "营业执照", "core"),
    ("财务", "近三年财务报表（资产负债表/利润表/现金流量表）", "core"),
    ("财务", "近三年审计报告", "core"),
    ("财务", "近期税务申报与完税证明", "normal"),
    ("财务", "未来三年营收与利润预测", "core"),
    ("财务", "银行流水与主要账户清单", "normal"),
    ("财务", "应收应付与主要负债明细", "normal"),
    # ── 法务 ────────────────────────────────────────────────
    ("法务", "公司章程（最新版）", "core"),
    ("法务", "历史融资/投资协议与股权结构表", "core"),
    ("法务", "员工持股平台与期权池文件", "normal"),
    ("法务", "重大合同（客户/供应商/租赁）清单", "normal"),
    ("法务", "知识产权清单（商标/专利/著作权）", "normal"),
    ("法务", "行政处罚与诉讼仲裁记录", "core"),
    ("法务", "主要资质与经营许可证", "normal"),
    # ── 业务 ────────────────────────────────────────────────
    ("业务", "商业计划书（BP）", "core"),
    ("业务", "前十大客户清单与收入占比", "core"),
    ("业务", "主要供应商与上下游清单", "normal"),
    ("业务", "各产品线收入占比与毛利", "core"),
    ("业务", "市场规模与市占率分析", "normal"),
    ("业务", "在手订单与销售管线", "normal"),
    ("业务", "核心团队简历与组织架构", "core"),
]


def get_standard_template() -> list[dict]:
    """返回标准数据包模板项列表。

    形状：[{item_no, category, requirement, importance}, ...]
    item_no 从 1 连续编号，供前端展示与排序。
    """
    return [
        {
            "item_no": str(i + 1),
            "category": cat,
            "requirement": req,
            "importance": imp,
        }
        for i, (cat, req, imp) in enumerate(_STANDARD_ITEMS)
    ]


def template_categories() -> list[str]:
    """模板涉及的维度（去重保序）。"""
    seen: list[str] = []
    for cat, _, _ in _STANDARD_ITEMS:
        if cat not in seen:
            seen.append(cat)
    return seen
