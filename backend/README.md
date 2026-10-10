# 智能拍照学习助手 · 后端服务

一期 MVP：**拍照答疑链路**（拍照 → 上传 → DeepSeek 多模态识图答疑 → 返回分步讲解 + 搭车打标）。

技术栈：Python 3.13 · FastAPI · SQLModel · httpx · DeepSeek-V4.1-Flash（OpenAI 兼容协议）

## 已实现

| 能力 | 说明 |
|------|------|
| 上传答疑 | `POST /api/v1/questions`：照片 + `user_id` + `client_question_id` → 同步返回分步讲解 |
| 搭车打标 | 答疑同一次模型调用顺带返回章节/知识点/难度/错因/`profile_delta`，存 `meta_json`（二期诊断模块消费） |
| 幂等去重 | `client_question_id` 唯一约束：重复提交返回已有结果；failed 记录可凭同 ID 重试（复用已存图片）——支撑端侧断网续传 |
| 图片存储 | 本地磁盘 + `StorageBackend` 抽象（二期换 OSS 零改业务代码）；格式/大小校验（jpg/png/webp/bmp，≤10MB） |
| 查询接口 | 单题详情、用户提问历史（倒序分页） |
| 健康检查 | `GET /api/v1/health`，同时暴露 `llm_configured` 便于确认 API Key 是否生效 |

## 快速开始

```bash
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

启动后：
- 接口文档（可直接调试）：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health

> 必须从 `backend/` 目录启动（`.env` 按相对路径读取）。

## 填入 API Key（必做）

编辑 `backend/.env`：

```
DEEPSEEK_API_KEY=你的密钥
```

填入后重启服务，`/api/v1/health` 的 `llm_configured` 应变为 `true`。未填 Key 时上传接口返回 503 并明确提示。

## 配置项（backend/.env）

| 变量 | 默认 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | 空 | **必填**，模型密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容协议地址 |
| `DEEPSEEK_MODEL` | `Deepseek-V4.1-Flash` | 模型名 |
| `DEEPSEEK_TIMEOUT` | `60` | 调用超时（秒） |
| `DEEPSEEK_MAX_TOKENS` | `8192` | 单次响应 token 上限；推理型模型（如 deepseek-flash）的思考 token 也计入，过小会导致正文为空（此时接口报 502 并提示调大，记录可重试） |
| `DATABASE_URL` | `sqlite:///./dev.db` | 开发默认 SQLite；切换 MySQL 见下 |
| `UPLOAD_DIR` | `./uploads` | 图片存储目录 |

## 切换 MySQL

`backend/.env` 中修改（驱动 pymysql 已装）：

```
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/photo_tutor?charset=utf8mb4
```

> 注意：SQLModel 0.0.48+ 的 datetime 列要求写入 tz-aware 值（代码已按 `datetime.now(timezone.utc)` 处理）；MVP 建表走启动时 `create_all`，表结构变更频繁后二期引入 alembic。

## 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/questions` | 上传照片答疑（multipart：`image` 文件 + `user_id` + `client_question_id`） |
| GET | `/api/v1/questions/{id}` | 单题详情（含 answer/meta/图片 URL） |
| GET | `/api/v1/users/{user_id}/questions?limit=20&offset=0` | 提问历史 |
| GET | `/api/v1/health` | 健康检查 + Key 状态 |
| GET | `/uploads/{文件名}` | 图片静态访问 |

调用示例（bash）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/questions \
  -F "image=@题目照片.png" \
  -F "user_id=1" \
  -F "client_question_id=$(uuidgen)"
```

返回示例：

```json
{
  "id": 1, "status": "answered", "duplicated": false,
  "answer": "第一步……第二步……",
  "meta": {
    "subject": "数学", "chapter": "二次函数",
    "kp_tags": ["抛物线性质"], "difficulty": 3,
    "suspected_error_type": "概念不清",
    "profile_delta": {"confusion": "平移方向与系数符号", "hint": "先补对称轴"}
  },
  "image_url": "/uploads/xxxx.png"
}
```

## 运行测试

```bash
cd backend
.venv\Scripts\python -m pytest -v
```

15 个用例全绿：LLM 输出容错解析（7）、接口全链路（8，含幂等去重、无 Key 降级 503、failed 重试、分页）。LLM 调用全部 mock，不依赖外网与真实 Key。

## 目录结构

```
backend/
├── .env                  # 实际配置（填 API Key，勿提交）
├── .env.example          # 配置模板
├── requirements.txt
├── pytest.ini
├── uploads/              # 题目图片存储
├── app/
│   ├── main.py           # FastAPI 入口 + 静态挂载
│   ├── config.py         # pydantic-settings 配置
│   ├── db.py             # 引擎/会话/建表
│   ├── models.py         # User / Question（SQLModel）
│   ├── schemas.py        # 出参 DTO
│   ├── storage.py        # 存储抽象（本地实现，留 OSS 口）
│   ├── llm/deepseek.py   # 多模态客户端 + JSON 搭车解析
│   ├── services/question_service.py   # 幂等/答疑/落库核心逻辑
│   └── routers/          # questions / health 路由
└── tests/                # pytest（LLM mock）
```

## 已知限制（按方案分期，属预期内）

- 同步答疑（等待模型返回），极端超时 60s；二期可改异步任务 + 轮询
- 无用户认证（`user_id` 由端侧传入）；二期补 auth
- 表结构走 `create_all`，无迁移工具；二期引入 alembic
- 无速率限制/风控；上线前补充
- 前端未开始（按约定：后端全部完成并通过测试后再做）
