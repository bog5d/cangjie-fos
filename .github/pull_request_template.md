## 本次变更说明

<!-- 一句话描述做了什么，为什么 -->

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 重构 / 性能优化
- [ ] 文档 / 注释
- [ ] 测试补充

## 强制检查清单（AI 和人类都必须完成）

- [ ] `cd backend && uv run --extra dev pytest tests/ -q` → **全绿**（当前基线 228 passed）
- [ ] `cd frontend && npm run build` → **零错误**
- [ ] 改了后端 service/route/schema → **已补对应测试**
- [ ] 改了 pipeline 链路 → **`test_pipeline_e2e.py` 和 `test_wizard_pipeline_e2e.py` 全过**
- [ ] **已更新 `CHANGELOG.md`**（在 `[Unreleased]` 下记录变更）
- [ ] 无 `.env` / API Key / SQLite 文件入库

## CHANGELOG 更新

<!-- 粘贴你在 CHANGELOG.md [Unreleased] 下新增的内容 -->

```markdown
### Added / Changed / Fixed
- ...
```

## 测试结果截图或输出

```
228 passed in XX.XXs
```
