# 开发计划：尽调清单自动生成模式

**版本目标：** v0.8.1  
**预计工时：** 4-6 小时  
**当前测试基线：** 641+ passed（你做完后必须不低于这个数）  
**开发分支：** `claude/financing-agent-integration-k9t5i`

---

## 背景说明（给接手 AI 看）

仓颉 FOS 有一个「尽调响应台」功能（三步向导）：

```
Step 1: 扫描材料库文件夹（建索引）
Step 2: 上传/粘贴投资机构发来的清单 → AI 解析为结构化需求项 → 触发匹配
Step 3: 用户审核匹配结果 → 导出文件夹
```

**现有缺口：** Step 2 只能「响应」机构给的清单，但没有「主动生成」清单的能力。
当项目方问「我要融 A 轮，应该准备哪些材料？」时，系统无法回答。

**这次要做的事：** 在 Step 2 加一个 Tab，允许用户不上传清单，而是输入融资阶段 + 行业，让 AI 生成一份标准清单，然后走完全相同的匹配 → 审核 → 导出流程。

---

## 改动全览

```
后端（3 处改动）：
  1. backend/src/cangjie_fos/services/dd_checklist_parser.py  ← 新增 generate_checklist()
  2. backend/src/cangjie_fos/api/routes/dd_response.py        ← 新增 POST /sessions/generate 端点
  3. backend/tests/test_dd_checklist_parser.py                ← 新增 3 个测试

前端（1 处改动）：
  4. frontend/src/components/DueDiligenceWizard.tsx           ← Step 2 加 Tab 切换
```

---

## 改动一：dd_checklist_parser.py — 新增 generate_checklist()

**文件路径：** `backend/src/cangjie_fos/services/dd_checklist_parser.py`

在文件**末尾**追加以下内容（不改动任何现有函数）：

```python
# ── 清单生成模式（v0.8.1 新增）────────────────────────────────────


# 融资阶段 → 中文描述（用于 prompt）
_STAGE_LABELS: dict[str, str] = {
    "seed": "种子轮（Pre-A 及更早）",
    "series_a": "A 轮",
    "series_b": "B 轮",
    "series_c": "C 轮及以后",
}

# 行业 → 特殊补充提示（用于 prompt）
_SECTOR_HINTS: dict[str, str] = {
    "saas": "补充 SaaS 特有指标：ARR / MRR / NRR / Churn Rate / ACV",
    "hardware": "补充硬件特有材料：生产资质 / 供应链合同 / 专利清单 / BOM 表",
    "medical": "补充医疗/医械特有材料：三类证 / NMPA 许可 / 临床数据",
    "consumer": "补充消费品特有材料：渠道协议 / SKU 销售数据 / 供应商名单",
    "fintech": "补充金融科技特有材料：支付牌照 / 风控模型说明 / 监管合规证明",
    "general": "",
}


def generate_checklist(stage: str, sector: str, extra: str = "") -> list[dict]:
    """
    根据融资阶段和行业生成标准尽调清单。

    stage:  "seed" | "series_a" | "series_b" | "series_c"
    sector: "saas" | "hardware" | "medical" | "consumer" | "fintech" | "general"
    extra:  可选补充说明（如「公司在香港注册」「有外资股东」）

    返回格式与 parse_checklist() 完全相同：
    [{"item_no": "1", "category": "基本情况", "requirement": "营业执照"}, ...]
    """
    stage_label = _STAGE_LABELS.get(stage, stage)
    sector_hint = _SECTOR_HINTS.get(sector, "")

    raw_text = _llm_generate_checklist(stage_label, sector_hint, extra)
    return _llm_extract_items(raw_text)


def _llm_generate_checklist(stage_label: str, sector_hint: str, extra: str) -> str:
    """调用 LLM 生成清单原始文本（可被测试 monkeypatch）。"""
    from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

    client = get_dd_llm_client()

    extra_section = f"\n补充说明：{extra}" if extra.strip() else ""
    sector_section = f"\n行业特殊要求：{sector_hint}" if sector_hint else ""

    prompt = f"""你是一名有十年经验的融资顾问，熟悉国内 VC/PE 机构对不同阶段创业公司的尽调要求。

请为以下情况生成一份完整的融资尽调材料清单：
- 融资阶段：{stage_label}{extra_section}{sector_section}

要求：
1. 按大类组织（基本情况 / 财务 / 法律合规 / 技术产品 / 市场与运营）
2. 每条清单项写具体的文件名称或指标名称，不要写模糊的"相关资料"
3. 根据融资阶段调整深度：种子轮 15-20 条，A 轮 25-35 条，B 轮及以后 35-50 条
4. 标注哪些是"必须有"（在需求前加「[必须]」）哪些是"加分项"（加「[加分]」）
5. 直接输出清单文字，不要额外说明

请按以下格式输出（方便后续解析）：

一、基本情况
1. [必须] 营业执照（三证合一）
2. [必须] 组织机构代码证
3. [加分] 高新技术企业认定证书

二、财务
4. [必须] 最近三年经审计财务报告
...
"""

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.1,
        )
        return resp.choices[0].message.content.strip()

    return call_with_retry(_call, max_retries=3)
```

**关键设计说明：**
- `generate_checklist()` 的返回值格式与 `parse_checklist()` **完全一致**，可以无缝进入 `create_match_session()`
- 两步复用现有逻辑：先生成原始文本 → 再调用现有的 `_llm_extract_items()` 提取结构化数据
- `_llm_generate_checklist()` 单独抽出来方便 monkeypatch 测试

---

## 改动二：dd_response.py — 新增 /sessions/generate 端点

**文件路径：** `backend/src/cangjie_fos/api/routes/dd_response.py`

**第一步：** 在文件顶部的 import 块里，在现有 `from cangjie_fos.services.dd_checklist_parser import parse_checklist` 这行，改为同时导入 `generate_checklist`：

```python
# 改前：
from cangjie_fos.services.dd_checklist_parser import parse_checklist

# 改后：
from cangjie_fos.services.dd_checklist_parser import generate_checklist, parse_checklist
```

**第二步：** 在文件里新增一个 Pydantic schema。找到现有的 `class ExportRequest(BaseModel):` 这行，在它**之后**插入：

```python
class GenerateChecklistRequest(BaseModel):
    stage: str          # "seed" | "series_a" | "series_b" | "series_c"
    sector: str         # "saas" | "hardware" | "medical" | "consumer" | "fintech" | "general"
    extra: str = ""     # 可选补充说明
    folder_root: str    # 材料库文件夹路径
    tenant_id: str = "default"
    institution_name: str = ""
```

**第三步：** 在 `# ── 清单 session 相关 ─` 注释块里，在现有的 `@router.post("/sessions")` **之前**插入新端点：

```python
@router.post("/sessions/generate")
async def generate_session(req: GenerateChecklistRequest):
    """
    根据融资阶段和行业 AI 生成标准尽调清单，创建匹配 session。
    无需上传文件，适用于项目方主动预检场景。
    """
    valid_stages = {"seed", "series_a", "series_b", "series_c"}
    valid_sectors = {"saas", "hardware", "medical", "consumer", "fintech", "general"}

    if req.stage not in valid_stages:
        raise HTTPException(400, f"无效 stage，支持：{sorted(valid_stages)}")
    if req.sector not in valid_sectors:
        raise HTTPException(400, f"无效 sector，支持：{sorted(valid_sectors)}")

    items = generate_checklist(req.stage, req.sector, req.extra)

    if not items:
        raise HTTPException(500, "清单生成失败，LLM 未返回任何需求项")

    stage_labels = {
        "seed": "种子轮", "series_a": "A轮",
        "series_b": "B轮", "series_c": "C轮+"
    }
    checklist_name = f"自动生成_{stage_labels.get(req.stage, req.stage)}_{req.sector}"

    session_id = create_match_session(
        req.tenant_id, checklist_name, req.folder_root, items, req.institution_name
    )

    if req.institution_name.strip():
        try:
            from cangjie_fos.services.institution_store import update_stage_by_name
            updated = update_stage_by_name(
                tenant_id=req.tenant_id, name=req.institution_name.strip(), stage="dd"
            )
            if updated:
                logger.info("机构 %s 阶段已自动更新为 DD", req.institution_name)
        except Exception as e:
            logger.warning("更新机构阶段失败（不影响主流程）: %s", e)

    return {"session_id": session_id, "items": items, "count": len(items)}
```

**注意：** 这个端点必须放在 `@router.post("/sessions")` **之前**，否则 FastAPI 会把 `/sessions/generate` 的 `generate` 误识别为 `session_id` 路径参数。

---

## 改动三：test_dd_checklist_parser.py — 新增 3 个测试

**文件路径：** `backend/tests/test_dd_checklist_parser.py`

在文件**末尾**追加：

```python
# ── generate_checklist 测试（v0.8.1）──────────────────────────────


def test_generate_checklist_returns_items(monkeypatch):
    """generate_checklist 正常路径：LLM 返回文本 → 解析为结构化列表。"""
    def mock_llm_generate(stage_label, sector_hint, extra) -> str:
        return (
            "一、基本情况\n"
            "1. [必须] 营业执照\n"
            "2. [必须] 验资报告\n"
            "二、财务\n"
            "3. [必须] 审计财务报告\n"
        )

    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_generate_checklist",
        mock_llm_generate,
    )

    # _llm_extract_items 也 mock，避免真实 LLM 调用
    def mock_extract(raw_text: str) -> list[dict]:
        return [
            {"item_no": "1", "category": "基本情况", "requirement": "营业执照"},
            {"item_no": "2", "category": "基本情况", "requirement": "验资报告"},
            {"item_no": "3", "category": "财务", "requirement": "审计财务报告"},
        ]

    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_extract_items",
        mock_extract,
    )

    from cangjie_fos.services.dd_checklist_parser import generate_checklist
    result = generate_checklist("series_a", "saas")

    assert len(result) == 3
    assert result[0]["requirement"] == "营业执照"
    assert result[2]["category"] == "财务"
    for item in result:
        assert "item_no" in item
        assert "category" in item
        assert "requirement" in item
        assert item["requirement"]


def test_generate_checklist_invalid_stage_is_passed_through(monkeypatch):
    """generate_checklist 不做 stage/sector 校验（校验在 API 层），直接透传给 LLM。"""
    call_log: list[tuple] = []

    def mock_llm_generate(stage_label, sector_hint, extra) -> str:
        call_log.append((stage_label, sector_hint, extra))
        return "1. [必须] 营业执照"

    def mock_extract(raw_text: str) -> list[dict]:
        return [{"item_no": "1", "category": "基本情况", "requirement": "营业执照"}]

    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_generate_checklist",
        mock_llm_generate,
    )
    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_extract_items",
        mock_extract,
    )

    from cangjie_fos.services.dd_checklist_parser import generate_checklist
    # service 层不校验，直接调用 — 校验在 API 层
    result = generate_checklist("unknown_stage", "general", extra="有外资股东")

    assert len(call_log) == 1
    assert call_log[0][2] == "有外资股东"  # extra 正确传入
    assert len(result) == 1


def test_generate_session_endpoint_e2e(monkeypatch, tmp_path):
    """
    E2E：POST /sessions/generate → 返回 session_id + items。
    验证端点校验、session 创建、items 数量。
    """
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    def mock_llm_generate(stage_label, sector_hint, extra) -> str:
        return "1. [必须] 营业执照\n2. [必须] 审计报告"

    def mock_extract(raw_text: str) -> list[dict]:
        return [
            {"item_no": "1", "category": "基本情况", "requirement": "营业执照"},
            {"item_no": "2", "category": "财务", "requirement": "审计报告"},
        ]

    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_generate_checklist",
        mock_llm_generate,
    )
    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_extract_items",
        mock_extract,
    )

    client = TestClient(create_app())

    # 正常请求
    resp = client.post("/api/v1/dd/sessions/generate", json={
        "stage": "series_a",
        "sector": "saas",
        "folder_root": str(tmp_path),
        "tenant_id": "test",
        "institution_name": "",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "session_id" in data
    assert data["count"] == 2
    assert data["items"][0]["requirement"] == "营业执照"

    # 无效 stage → 400
    resp_bad = client.post("/api/v1/dd/sessions/generate", json={
        "stage": "invalid_stage",
        "sector": "saas",
        "folder_root": str(tmp_path),
        "tenant_id": "test",
    })
    assert resp_bad.status_code == 400
```

---

## 改动四：DueDiligenceWizard.tsx — Step 2 加 Tab

**文件路径：** `frontend/src/components/DueDiligenceWizard.tsx`

这是前端改动，涉及 state 和 JSX，需要比较小心。以下是完整的改动说明：

### 4.1 新增 state（加在现有 Step 2 state 注释块里）

找到 `// Step 2 state` 注释下方，在 `const [checklistText, setChecklistText] = useState("");` 这行**之前**插入：

```typescript
  // Step 2 Tab 模式
  const [step2Mode, setStep2Mode] = useState<"upload" | "generate">("upload");

  // 自动生成模式 state
  const [genStage, setGenStage] = useState<string>("series_a");
  const [genSector, setGenSector] = useState<string>("general");
  const [genExtra, setGenExtra] = useState<string>("");
```

### 4.2 新增 handleGenerate 函数

找到现有的 `handleScan` 函数（`const handleScan = useCallback`），在它**之前**插入（同级别）：

```typescript
  // ── Step 2: 自动生成清单 ──────────────────────────────────────
  const handleGenerate = useCallback(async () => {
    if (!folderPath.trim()) {
      setMatchError("请先在 Step 1 完成材料库扫描");
      return;
    }
    setParsing(true);
    setMatchError("");
    setMatchStatus("idle");
    try {
      const resp = await fetch("/api/v1/dd/sessions/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stage: genStage,
          sector: genSector,
          extra: genExtra,
          folder_root: folderPath,
          tenant_id: "default",
          institution_name: institutionName,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      setSessionId(data.session_id);

      // 触发匹配
      const matchResp = await fetch(
        `/api/v1/dd/sessions/${data.session_id}/match?folder_root=${encodeURIComponent(folderPath)}`,
        { method: "POST" }
      );
      if (!matchResp.ok) throw new Error("匹配触发失败");

      setMatchStatus("running");
      // 轮询逻辑与 handleParseAndMatch 相同，复用 pollMatchRef
      let tries = 0;
      pollMatchRef.current = window.setInterval(async () => {
        tries++;
        if (tries > 30) {
          clearInterval(pollMatchRef.current!);
          setMatchStatus("error");
          setMatchError("匹配超时（60秒），请刷新重试");
          return;
        }
        try {
          const r = await fetch(`/api/v1/dd/sessions/${data.session_id}/items`);
          if (!r.ok) return;
          const itemList: DDItem[] = await r.json();
          const done = itemList.every((it) => it.confidence !== null);
          if (done) {
            clearInterval(pollMatchRef.current!);
            setItems(itemList);
            setMatchStatus("done");
            setStep(3);
          }
        } catch (_) {}
      }, 2000);
    } catch (e: unknown) {
      setMatchError(e instanceof Error ? e.message : "生成失败");
      setMatchStatus("error");
    } finally {
      setParsing(false);
    }
  }, [genStage, genSector, genExtra, folderPath, institutionName]);
```

### 4.3 修改 Step 2 的 JSX 渲染

在 Step 2 的 JSX 区块里，找到原有渲染机构名输入框和文件上传的地方，在**机构名输入框之后、文件上传区域之前**，插入 Tab 切换 UI：

```tsx
{/* Tab 切换 */}
<div style={{ display: "flex", gap: 0, marginBottom: 12, borderBottom: "1px solid #333" }}>
  <button
    onClick={() => setStep2Mode("upload")}
    style={{
      padding: "6px 16px",
      background: step2Mode === "upload" ? "#2a2a2a" : "transparent",
      color: step2Mode === "upload" ? "#fff" : "#888",
      border: "none",
      borderBottom: step2Mode === "upload" ? "2px solid #4a9eff" : "2px solid transparent",
      cursor: "pointer",
      fontSize: 13,
    }}
  >
    📄 上传/粘贴清单
  </button>
  <button
    onClick={() => setStep2Mode("generate")}
    style={{
      padding: "6px 16px",
      background: step2Mode === "generate" ? "#2a2a2a" : "transparent",
      color: step2Mode === "generate" ? "#fff" : "#888",
      border: "none",
      borderBottom: step2Mode === "generate" ? "2px solid #4a9eff" : "2px solid transparent",
      cursor: "pointer",
      fontSize: 13,
    }}
  >
    ✨ 自动生成清单
  </button>
</div>

{/* 上传/粘贴 Tab（现有内容，用条件包裹） */}
{step2Mode === "upload" && (
  <div>
    {/* 此处放原有的文件上传 + 文字粘贴 + 解析按钮 JSX，原样保留，整体包在这个 div 里 */}
  </div>
)}

{/* 自动生成 Tab（新内容） */}
{step2Mode === "generate" && (
  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
    <div>
      <label style={{ color: "#aaa", fontSize: 12, display: "block", marginBottom: 4 }}>
        融资阶段
      </label>
      <select
        value={genStage}
        onChange={(e) => setGenStage(e.target.value)}
        style={{ width: "100%", padding: "6px 10px", background: "#1a1a1a", color: "#fff", border: "1px solid #444", borderRadius: 4 }}
      >
        <option value="seed">种子轮（Pre-A 及更早）</option>
        <option value="series_a">A 轮</option>
        <option value="series_b">B 轮</option>
        <option value="series_c">C 轮及以后</option>
      </select>
    </div>

    <div>
      <label style={{ color: "#aaa", fontSize: 12, display: "block", marginBottom: 4 }}>
        行业类型
      </label>
      <select
        value={genSector}
        onChange={(e) => setGenSector(e.target.value)}
        style={{ width: "100%", padding: "6px 10px", background: "#1a1a1a", color: "#fff", border: "1px solid #444", borderRadius: 4 }}
      >
        <option value="general">通用</option>
        <option value="saas">SaaS / 企业软件</option>
        <option value="hardware">硬件 / 智能设备</option>
        <option value="medical">医疗 / 医械</option>
        <option value="consumer">消费品 / 新消费</option>
        <option value="fintech">金融科技</option>
      </select>
    </div>

    <div>
      <label style={{ color: "#aaa", fontSize: 12, display: "block", marginBottom: 4 }}>
        补充说明（可选）
      </label>
      <input
        type="text"
        value={genExtra}
        onChange={(e) => setGenExtra(e.target.value)}
        placeholder="例：公司在开曼注册，有外资股东"
        style={{ width: "100%", padding: "6px 10px", background: "#1a1a1a", color: "#fff", border: "1px solid #444", borderRadius: 4, boxSizing: "border-box" }}
      />
    </div>

    {matchError && (
      <div style={{ color: "#f87171", fontSize: 12 }}>{matchError}</div>
    )}

    <button
      onClick={handleGenerate}
      disabled={parsing || matchStatus === "running"}
      style={{
        padding: "8px 16px",
        background: parsing || matchStatus === "running" ? "#333" : "#2563eb",
        color: "#fff",
        border: "none",
        borderRadius: 4,
        cursor: parsing || matchStatus === "running" ? "not-allowed" : "pointer",
        fontSize: 13,
      }}
    >
      {parsing ? "生成中…" : matchStatus === "running" ? "匹配中…" : "✨ 生成清单并开始匹配"}
    </button>
  </div>
)}
```

> **注意：** "此处放原有的文件上传 + 文字粘贴 + 解析按钮 JSX" 这段注释是提示你把现有 Step 2 的 JSX 内容用 `{step2Mode === "upload" && (<div>...原有内容...</div>)}` 包裹起来，**不要删除任何原有 JSX**，只是加条件渲染。

---

## 验收标准

### 后端测试（必须全过）

```bash
cd backend
uv run --extra dev pytest tests/test_dd_checklist_parser.py -v
# 期望：11 passed（原 8 个 + 新增 3 个）

uv run --extra dev pytest tests/ -q
# 期望：不低于 641 passed，0 failed
```

### 功能验收（手动检查 2 个场景）

**场景 A：自动生成模式正常工作**
1. 打开尽调响应台
2. Step 1 完成扫描（任意文件夹）
3. Step 2 点击「✨ 自动生成清单」Tab
4. 选择「A 轮」+「SaaS」
5. 点击生成 → 等待 → 自动跳转到 Step 3
6. Step 3 应该有 25-35 条需求项，含基本情况/财务/法律等大类

**场景 B：上传模式不受影响**
1. 同上，Step 2 点击「📄 上传/粘贴清单」Tab
2. 粘贴或上传清单文件
3. 流程与之前完全相同

---

## 注意事项

1. **路由顺序**：`/sessions/generate` 必须在 `dd_response.py` 的 `@router.post("/sessions")` **之前**注册，否则 FastAPI 会把 `generate` 当作 `session_id` 路径参数解析，返回 404。

2. **前端不要改 Step 1 和 Step 3**：这次只改 Step 2 的渲染部分，Step 1 的扫描逻辑和 Step 3 的审核导出逻辑完全不动。

3. **folderPath 依赖**：`handleGenerate` 里要检查 `folderPath.trim()` 是否为空，如果用户没做 Step 1 扫描直接来到 Step 2 点生成，要给出提示而不是报 API 错误。

4. **测试用 monkeypatch 而不是 mock.patch**：新增的测试参照 `test_dd_checklist_parser.py` 里已有测试的风格，函数级 mock 用 `monkeypatch.setattr`，模块级用 `unittest.mock.patch`。

---

## 完成后更新

做完后在 `CLAUDE.md` 顶部版本历史表加一行：

```
| v0.8.1 | 05-16 | 尽调清单自动生成模式：输入融资阶段+行业 → AI 生成标准清单 → 走现有匹配流程 |
```

并在 `CHANGELOG.md` 里追加 v0.8.1 版本块。
