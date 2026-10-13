# 后端服务

后端代码与详细说明已上移至**工作区根目录的 [README.md](../README.md)**（项目总览）。

快速索引：

- 运行方式、API Key 配置、接口一览 → 见根 README「快速开始（后端）」
- 已实现功能 / 待实现功能 → 见根 README「功能状态」
- 测试与排障 → `../README.md` 的「运行测试」章节
- 个性化服务设计 → `../docs/个性化服务功能计划.md`

## 快速启动

```bash
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

必须从 `backend/` 目录启动（`.env` 按相对路径读取）。