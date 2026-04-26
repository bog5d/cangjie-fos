# 仓颉 FOS — 发布验收清单

供发布前自检与同事环境对齐。逐项打勾。

## 0. 外发「一体化压缩包」怎么打（发版人）

### 纯净外发包（默认 `-Profile Release`）指什么

- **目标**：接收方**解压到英文路径后**能按指引启动并访问 `http://127.0.0.1:8000`；包内是**可运行双仓**（`CangJie_FOS` + `AI_Pitch_Coach` 含 `src`）、`packaging` 派生的启动/指引/说明、空桥目录 `.fos_data\`，以及**必要元数据**（如 `pyproject`/`uv.lock`/`requirements` 等由脚本实际拷入者）。
- **默认不应出现**：软著长文与申请材料树、历史「交付」子树、大体积样本/说明海、内部 zip 自引用、调试日志、与运行无关节点（由 `build_release_zip.ps1` 的 **Release** 排除表与 Coach 顶层的**模式排除**实现；**不得**为瘦身而 `/XD` 掉 `CangJie_FOS\frontend\dist`）。
- **全量/调试用包**：`build_release_zip.ps1 -Profile Full`（仍排除 `node_modules`/`.venv` 等；**不**按 Release 规则剔除软著/Coach 大目录等）。变更默认排除表须在脚本**注释**或本清单中留痕。

### 外发铁律（对 AI / 发版人）

- **必须**在机器上**实际执行** `build_release_zip.ps1` 并生成**真实 .zip 文件**；**必须**向接收方提供 **zip 绝对路径 + SHA256 + 一级根目录结构说明**；**必须**在英文路径自测一次启动与 `http://127.0.0.1:8000` / `/api/v1/ready`。未做到以上任一项，**不得**称「外发已就绪」。详见 `.cursor/rules/cangjie-fos-external-release.mdc` 与 `.cursor/rules/cangjie-fos-quality-gate.mdc`。
- **发版/PR 前**应跑通 `tools/ci_check.ps1`（或等价），并在答复/说明中**明确已绿或失败项**；不得虚构「已出包/已自测通过」。  
- 发给同事时的**推荐固定一句**见外发规则；要点：**英文完整路径解压** → **先看 00+使用指引** → **双击** `点击开始-仓颉FOS.bat`。

在**已含 `AI_Pitch_Coach` 与已构建的 `frontend/dist`** 的机器上，于 `CangJie_FOS` 根或 `tools` 下执行例如：

```powershell
# 默认 -Profile Release（纯净外发）；与历史 CangJie_FOS_Release_YYYYMMDD.zip 命名一致可用 -ZipBaseName
& .\tools\build_release_zip.ps1 -OutDir D:\发版输出 -ZipBaseName CangJie_FOS_Release_20260422 -ErrorIfNoCoach
# 若需现打前端，加上 -BuildFrontend
# 全量/内部调试包：-Profile Full
```

- 产出：`.zip` 及同名的 `.sha256`、`.meta.txt`（`.meta.txt` 含 `Profile`）。  
- 压缩包**根目录**会带上：`00_先看这一行.txt`、**《仓颉FOS-使用指引（收到压缩包后请读）.md》**、`点击开始-仓颉FOS.bat`，以及 `CangJie_FOS\`、`AI_Pitch_Coach\`、空桥目录 `.fos_data\`（含说明）。  
- 打 Coach 时脚本**始终**排除 `node_modules`、`.venv`、**`dist`/`build`/`output`**、历史 `*.zip`、`.env` 等；`Profile Release` 下另排除 Coach 的 `client_reports`、`docs/tests` 等及**按目录名**匹配的 `01_*` 风格号段、名中含「软著」「交付」、**顶层目录名以 `AI` 起头**（历史版本/副本树；**不**含 `src/`，因 `src` 不在 `AI*` 名下）等；FOS 侧在 Release 下另排除如 `软著申请材料`、`html_reports` 等，且**永不**用 `/XD` 排除 `frontend\dist`。  
- 内部预演与对策见 `docs/外发_灾难预演与交付对策.md`。

## 1. 目录布局（必须）

工作区父目录（例如 `C:\FOS` 或 `D:\AI_Workspaces`）下应**并列**存在：

| 路径 | 说明 |
|------|------|
| `…/CangJie_FOS/` | 本系统 Monorepo（含 `backend/`、`frontend/dist/`） |
| `…/AI_Pitch_Coach/` | 路演评估依赖仓，**必须**含 `src/` 子目录 |

若 `AI_Pitch_Coach` 不在默认位置，在 `CangJie_FOS/backend/.env` 中设置：

```env
CANGJIE_PITCH_COACH_ROOT=D:\path\to\AI_Pitch_Coach
```

## 2. 前端

- [ ] 存在 `CangJie_FOS/frontend/dist/index.html`（预构建 SPA）

开发机可运行 `build_frontend.ps1` 或 `cd frontend && npm run build` 生成。

## 3. 环境变量（`backend/.env`）

- [ ] `SILICONFLOW_API_KEY` 已填（主 LLM）
- [ ] `DEEPSEEK_API_KEY` 已填（若产品要求）
- [ ] `DASHSCOPE_API_KEY` 已填（语音转写需要时）

可选：

- `CANGJIE_FSS_DATA_DIR`：若与默认不一致，指向**与仓颉资产台账 FSS 写入相同的** `.fos_data` 父目录或该目录本身（与运行时代码一致：桥接文件为 `…/asset_index.json`）。

默认桥接目录：`CangJie_FOS` 的**上一级**目录下的 `.fos_data/`（与 `get_fos_bridge_data_dir()` 一致）。

## 4. 数据桥（资产台账）

- FSS 执行「向上扫描」后，应在上述 `.fos_data` 下生成 `asset_index.json`；FOS 与 FSS 需指向**同一**桥目录，否则「资产台账」为空。

## 5. 自动化预检与合入门禁

- **发版/PR 前（与代码合入同一条）**：在仓库根执行 `& .\tools\ci_check.ps1`（`uv` 约定子集 pytest + `frontend` 的 `npm run build`；失败非零）。与 `.cursor/rules/cangjie-fos-quality-gate.mdc` 对齐。  
- **运行后/环境**：`tools/preflight_local.ps1`（或启动后请求 `GET /api/v1/ready`）确认无阻塞项。

## 6. 版本锁定

- Python `>=3.11`（见 `backend/pyproject.toml`）
- 使用 `uv sync` 或 `uv lock` 锁定依赖的发布机应保留 `uv.lock`（若仓库内提供）

## 7. 可选安全（单用户/内网）

- `CANGJIE_API_KEY`：设置后，API 需带 `Authorization: Bearer <key>` 或 `X-API-Key`
- 默认仅本机访问时，启动使用 `--host 127.0.0.1`

## 8. 稳态与硬化相关环境变量（可选）

| 变量 | 默认 | 说明 |
|------|------|------|
| `CANGJIE_STRICT_STARTUP` | 关 | 为 `1`/`true` 时，就绪检查失败则进程不启动 |
| `CANGJIE_MAX_UPLOAD_MB` | 200 | 单文件上传上限 |
| `CANGJIE_MAX_JSON_BODY_MB` | 8 | JSON 请求体上限 |
| `CANGJIE_MAX_CONCURRENT_JOBS` | 2 | 后台 Pitch 任务并发槽 |
| `CANGJIE_MAX_REQUESTS_PER_MINUTE` | 300 | 每 IP 每分钟 `/api` 请求数 |
| `CANGJIE_MAX_ASSET_INDEX_MB` / `CANGJIE_MAX_ASSET_COUNT` | 32MB / 50000 | 桥接索引 |
| `CANGJIE_EXPOSE_ERROR_DETAIL` | 关 | 为 `true` 时 500 返回更多内部信息（仅排障） |
| `CANGJIE_NPC_MAX_OUTPUT_TOKENS` | 1200 | 豆区单轮输出上限 |

前端若启用 API Key：构建时设置 `VITE_CANGJIE_API_KEY`（与 `CANGJIE_API_KEY` 一致）。

---

*与 `同事上手指南.md` 同步维护。*
