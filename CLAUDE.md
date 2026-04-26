# CangJie FOS — AI 开发标准

## 核心原则：代码改动必须有测试覆盖，不依赖人工点 UI 验证

### 测试运行命令
```bash
cd backend
uv run --extra dev pytest tests/ -q   # 全套，133+ passed 才算通
uv run --extra dev pytest tests/test_pipeline_e2e.py tests/test_wizard_pipeline_e2e.py -v  # 核心链路
```

---

## 强制测试标准（每次改动后必须执行）

### 1. 改了后端任何 service / route / schema
- 必须跑 `pytest tests/` 全套
- 新增功能必须同步新增对应测试，不允许"先上线后补测试"

### 2. 改了 pipeline 链路（pitch_upload_pipeline / pitch_wizard_runner）
- 必须确认 `test_pipeline_e2e.py` 和 `test_wizard_pipeline_e2e.py` 全过
- 这两个测试覆盖了「数据异常」的根因链路：DB写入 → Review API → 前端可读

### 3. 新增后台任务（BackgroundTask）
- 必须同步写 DB（`db_job_update`），不能只写内存 store
- 必须在 E2E 测试中验证 DB 状态，不能只 mock

### 4. 新增 API 端点
- 必须在对应 `test_p*_*.py` 文件中覆盖：200正常流、404异常、字段结构

---

## 禁止行为

- ❌ 改完代码说"应该好了，你去试一下" — 必须先跑测试证明
- ❌ 只 mock 外部服务而不验证 DB 写入 — DB 才是审查台的数据源
- ❌ 新增 pipeline 步骤后不同步更新 E2E 测试
- ❌ 依赖人工上传音频来验证流程 — 用 `make_wav()` 生成测试音频

---

## 测试分层架构

| 层级 | 文件 | 覆盖范围 | mock范围 |
|------|------|---------|---------|
| 单元/接口 | `test_pitch_job_db.py` `test_p0_review_endpoints.py` 等 | 单个函数/端点 | 全mock |
| Pipeline E2E | `test_pipeline_e2e.py` | 简单上传全链路 | mock ASR+LLM |
| Wizard E2E | `test_wizard_pipeline_e2e.py` | 向导提交全链路 | mock ASR+LLM |
| 启动检查 | preflight.py（lifespan自动跑） | 依赖包完整性 | 无mock |

---

## 新增功能时的标准流程

1. 写代码
2. 写测试（参照现有 E2E 测试的 mock 模式）
3. `pytest tests/ -q` 全绿
4. 报告：`X passed`，不说"可以了你试试"

---

## 关键架构约定（不要推翻）

- Review API 读 SQLite（`db_job_get`），不读内存 store
- 所有 pipeline 必须同时写内存（`job_update`）和 SQLite（`db_job_update`）
- 音频文件永久路径：`backend/data/audio/{job_id}{suffix}`
- HTML报告路径：`backend/data/html_reports/{job_id}.html`，通过 `/reports/` 静态服务

## 依赖管理
- 缺包用 `uv add <package>`，不用 pip
- 新增依赖后必须重启 uvicorn（热重载不可靠）
- 启动时 preflight.py 自动检查必选依赖，缺失会阻断启动并提示安装命令
