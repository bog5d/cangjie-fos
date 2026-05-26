# Agentic Capital Workflow
### 融资 Agent 架构手记 · Desensitized Skills & Research Notes for Primary Market Capital Operations

> **中文** | 本仓库是"仓颉 FOS"融资作战操作系统的**对外开放面**。核心生产系统因涉及机构敏感数据已设为私有，此处持续更新脱敏后的代码片段（Skills）、架构决策记录（ADR）及研究数据集，供同行参考与交流。
>
> **EN** | This is the public-facing companion to **Cangjie FOS** — a private, agentic fundraising OS for primary market operations. Sensitive institutional data stays private; what lives here are desensitized code skills, architecture decision records, and research datasets for the community.

---

## 🗂️ 仓库结构 · Repository Structure

```
Agentic-Capital-Workflow/
├── skills/              # 可复用 Agent 技能片段 / Reusable agent skill snippets
│   ├── dd-matcher/      # 尽调清单语义匹配 / DD checklist semantic matching
│   ├── institution-crm/ # 机构偏好记忆 / Investor preference memory
│   └── pitch-scorer/    # 路演评分流水线 / Pitch scoring pipeline
├── adr/                 # 架构决策记录 / Architecture Decision Records
├── datasets/            # 脱敏研究数据集 / Desensitized research datasets
└── notes/               # 实战手记 / Field notes & reflections
```

---

## 🚀 核心场景 · Core Use Cases

| 场景 · Scenario | 技术栈 · Stack | 状态 · Status |
|---|---|---|
| 尽调清单 × 材料库语义匹配 | LangGraph + DeepSeek + SQLite | 🟢 持续迭代 |
| DD Checklist × Document Semantic Matching | LangGraph + DeepSeek + SQLite | 🟢 Active |
| 机构偏好记忆与热度管理 | FastAPI + SQLite CRM | 🟢 持续迭代 |
| Investor Preference Memory & Thermal Tracking | FastAPI + SQLite CRM | 🟢 Active |
| 路演录音 → 风险点提取 → 评分 | Whisper + LLM Judge | 🟡 内测中 |
| Pitch Audio → Risk Extraction → Scoring | Whisper + LLM Judge | 🟡 Beta |
| 融资漏斗自动推进（Agentic Pipeline） | LangGraph Conditional Edges | 🔵 规划中 |
| Fundraising Funnel Auto-Advance | LangGraph Conditional Edges | 🔵 Planned |

---

## 🧠 架构理念 · Design Philosophy

**中文**

> 一级市场的信息摩擦不是"没有数据"，而是"数据全在人脑里"。  
> Agentic Workflow 的价值不在于替代 FA/VC 的判断，而在于把散落在录音、邮件、微信、笔记里的隐性知识**结构化、可检索、可追溯**。

**EN**

> The friction in primary market fundraising isn't a lack of data — it's that all the data lives inside people's heads.  
> The value of Agentic Workflow isn't to replace FA/VC judgment. It's to make the tacit knowledge scattered across recordings, emails, WeChat, and notes **structured, searchable, and auditable**.

---

## 🔗 相关项目 · Related Projects

| 项目 · Project | 说明 · Description | 链接 · Link |
|---|---|---|
| **Cangjie FOS** (Private) | 完整生产系统 · Full production OS | 🔒 Private |
| **AI Pitch Coach** | 路演分析原型 · Pitch analysis prototype | [→ repo](https://github.com/bog5d/ai-pitch-coach) |
| **Cangjie Team OS** | 团队知识管理 · Team knowledge management | [→ repo](https://github.com/bog5d/Cangjie-Team-OS) |

---

## 📬 交流 · Connect

如果你也在用 AI 工具处理融资流程中的信息问题，欢迎 Issue 或直接联系。  
If you're also using AI to tackle information friction in fundraising workflows, open an Issue or reach out directly.

---

<div align="center">
  <sub>Build in Public · 公开构建 | 核心生产系统永远私有 · Core production stays private</sub>
</div>
