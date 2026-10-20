# 智能拍照学习助手（高数拍搜）

> 拍照 → 多模态大模型识图答疑 → 学习画像 → 薄弱点诊断 → 针对性练习
>
> 一句话区别：作业帮回答「这道题怎么做」，我们回答「**你到底哪里不会**」。

技术栈：Vue 3 + Vite（前端）· FastAPI + SQLModel + DeepSeek 多模态（后端）

---

## 快速开始（Windows，三步）

### 前置条件

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 安装时务必勾选 **Add Python to PATH** |
| Node.js | 18+ | 前端构建与开发服务器 |
| DeepSeek API Key | — | [platform.deepseek.com](https://platform.deepseek.com) 申请；**不填也能跑通除 AI 之外的全部功能** |

### 三步启动

```
① 双击 setup.bat      → 自动创建虚拟环境、装依赖、生成 .env
② 编辑 backend\.env   → 填入 DEEPSEEK_API_KEY=你的密钥
③ 双击 start.bat      → 自动起前后端并打开浏览器
```

启动后：

- 前端：http://127.0.0.1:5173
- 接口文档（可在线调试）：http://127.0.0.1:8000/docs
- 题库人工校对页：http://127.0.0.1:8000/review

> 后端首次启动会自动建表；`dev.db` 已随仓库提供，**题库和知识点开箱即用**，无需重新提取。

### 手动启动（macOS / Linux / 不想用 bat）

```bash
# 后端
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
cp .env.example .env                           # 填入 API Key
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

依赖安装慢可换国内镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
npm install --registry=https://registry.npmmirror.com
```

---

## 自带数据说明

仓库内 `backend/dev.db` 与 `backend/kb_images/` 已包含构建好的知识库，克隆即可用：

| 内容 | 规模 |
|---|---|
| 知识点体系 | 12 章 / 82 节 / **900 个细粒度知识点**（含说明、核心公式、难度） |
| 题库 | 吉米多维奇精选精解题，含题干 / 选项 / 答案 / 解析 / 知识点标注 / 难度 |
| 题目图片 | 每题三张：**题干图**（练习时展示）、**解析图**（判分后展示）、整题图 |
| 演示用户 | **user_id = 1001**，含一周学习轨迹、错题本、画像与诊断报告 |

**查看演示数据**：进入「我的」页 → 点击「演示数据（1001）」按钮 → 切到「诊断」页看雷达图与报告。

> 想从原始 PDF 重新构建？见下文「知识库管线」。原始教材 PDF 未入库（版权与体积限制）。

---

## 功能一览

| 模块 | 能力 |
|---|---|
| **拍照答疑** | 图片直接上传多模态大模型，返回分步讲解；同一次调用顺带返回学科/章节/知识点/难度/错因候选（搭车打标，零额外成本） |
| **错因反馈** | 学生自选「卡在哪」（多选 + 自定义），注入画像；粗心/看错题权重仅 0.2，**不污染知识画像** |
| **学习画像** | 掌握度 = EMA + 错因加权 + 30 天时间衰减；存 `backend/profiles/{user_id}.md`，答疑后即时更新 |
| **诊断报告** | 规则算分 + LLM 撰写；**规则版零 token 兜底**；含原题证据与版本对比 |
| **雷达图** | 章节总览（全书 12 章正十二边形，未练习章节为 0）→ **点击章节下钻**到该章知识点掌握度 |
| **针对性练习** | 按薄弱点组卷（难度阶梯 3:5:2）；答题只给题干图，**判分后才给解析** |
| **考试式判分** | 客观题点选自动判；主观题**拍照上传 → 模型按答案等价性阅卷**（无法判定时回退自评） |
| **解析求助** | 看完解析还不懂 → 选「卡在哪」→ **困惑注入 prompt**，模型换个讲法，可连续追问 |
| **错题本** | 答疑未解决 + 自测错题自动收录；标记掌握联动画像 |
| **Token 计量** | 按场景统计 prompt/completion/推理/缓存命中与延迟 |

**可靠性设计**

- 幂等：`client_question_id` 唯一约束，重复提交返回已有结果，失败凭同一 ID 重试
- 断网续传：Room/WorkManager 侧约束 + 服务端去重（移动端设计目标）
- 空响应防护：模型返回空正文或截断时显式报错（502），绝不静默返回空答案
- 规则与 LLM 分工：算分、组卷、判分走规则（可复现、可降级），LLM 只做讲解与撰写

---

## 目录结构

```
智能拍照学习助手/
├── setup.bat / start.bat        # 一键安装 / 一键启动（Windows）
├── frontend/                    # Vue 3 + Vite，移动端四屏
│   └── src/
│       ├── views/               # 拍照 / 练习 / 诊断 / 我的
│       ├── components/          # RadarChart（手绘 SVG）/ MarkdownView
│       ├── utils/markdown.js    # Markdown + KaTeX 公式渲染
│       └── api/index.js         # 后端接口封装
└── backend/                     # FastAPI 服务
    ├── app/
    │   ├── main.py              # 入口 + 静态挂载
    │   ├── config.py            # 配置（以 backend/ 为绝对基准）
    │   ├── db.py                # 引擎 / 建表 / 轻量迁移
    │   ├── models.py            # SQLModel（11 张表）
    │   ├── llm/deepseek.py      # 多模态客户端 + 容错解析 + usage 采集
    │   ├── services/            # 画像 / 诊断 / 自测 / 错题 / 上下文 / token
    │   └── routers/             # 28 个接口路径
    ├── scripts/kb/              # 知识库构建管线（01~08）
    ├── kb_images/problems/      # 题目图片（入库）
    ├── profiles/                # 用户画像 md（运行时生成）
    ├── tests/                   # pytest（33 用例，LLM 全 mock）
    ├── dev.db                   # 题库 + 知识点（入库）
    └── requirements.txt
```

---

## 常用接口

完整清单见 http://127.0.0.1:8000/docs 。核心几个：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/questions` | 拍照答疑（multipart：`image` + `user_id` + `client_question_id`） |
| POST | `/api/v1/profile/questions/{id}/feedback` | 提交错因反馈，立即重算画像 |
| GET | `/api/v1/profile/users/{id}/radar` | 雷达图 JSON（章节骨架，含未练习章节） |
| POST | `/api/v1/tests/users/{id}/sessions` | 按薄弱点组卷 |
| POST | `/api/v1/tests/sessions/{sid}/submit` | 提交判分 + 回流画像 + 错题入库 |
| POST | `/api/v1/tests/questions/{qid}/judge-image` | 主观题拍照阅卷 |
| POST | `/api/v1/tests/questions/{qid}/explain` | 看解析还不懂 → 带着困惑重讲 |
| POST | `/api/v1/diagnose/users/{id}?use_llm=false` | 生成诊断报告（规则版 0 token） |
| GET | `/api/v1/tokens/summary` | token 消耗汇总 |

---

## 配置项（backend/.env）

| 配置 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | **必填**（不填时 AI 功能返回 503，其余功能正常） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容地址 |
| `DEEPSEEK_MODEL` | `Deepseek-V4.1-Flash` | 模型名 |
| `DEEPSEEK_MAX_TOKENS` | `32000` | 单次上限。**推理模型思考 token 计入**，过小会导致正文为空 |
| `DEEPSEEK_TIMEOUT` | `60` | 超时（秒） |
| `DATABASE_URL` | `sqlite:///./dev.db` | 切 MySQL：`mysql+pymysql://user:pwd@host:3306/photo_tutor?charset=utf8mb4` |
| `UPLOAD_DIR` | `./uploads` | 用户上传图片目录 |

---

## 常见问题

**Q：没有 API Key 能用吗？**
除 AI 相关功能（答疑、诊断报告 LLM 版、阅卷、解析求助）外，其余全部可用：题库浏览、组卷、客观题判分、画像统计、雷达图、错题本。

**Q：端口被占用？**
后端改端口：`.venv\Scripts\python -m uvicorn app.main:app --port 8001`
前端同步改：`set VITE_BACKEND=http://127.0.0.1:8001` 后再 `npm run dev`。

**Q：题目图片显示不出来？**
确认 `backend/kb_images/` 存在（仓库自带）；启动后端即挂载在 `/kb_images/...`。

**Q：`llm_configured` 一直是 false？**
`.env` 没填 Key 或后端未重启。改动 `.env` 后需重启服务。

**Q：全量提取报「空正文」？**
推理模型的思考与正文共享 `max_tokens`，调大 `DEEPSEEK_MAX_TOKENS`（提取脚本内已设 32000）。

---

## 知识库管线（可选，重新构建题库时用）

原始数据源为扫描版 PDF（501 页、无文本层），走「渲染成图 → 多模态结构化提取」：

```bash
cd backend/scripts/kb
python 01_skeleton.py        # 书签目录 → 章节骨架
python 02_knowledge_points.py # 细分 L3 知识点
python 03_render.py          # 页面渲染
python 05_ocr_probe.py --pages 1-501        # OCR 题号定位（切图边界）
python 04_extract.py --pages 1-501 --crop --ingest   # 提取 + 裁剪 + 入库
python 08_recrop_all.py      # 统一重裁（改了切分逻辑后跑）
```

**分工原则**：OCR 只做「眼睛」（定位题号坐标、精确切图），内容理解全部交给多模态模型；OCR 对数学公式识别极差，不能作为题干来源。

切分逻辑：模型给「题干/解析」分界点 → OCR 行边界校正（选项行下限 + 语义锚点 + 行顶部吸附）→ 题干图 / 解析图分离。

---

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest -q      # 33 用例，LLM 全 mock，不依赖外网
```

---

## 设计原则

**规则引擎定骨架，LLM 填内容**：薄弱度算分、组卷抽题、客观判分走确定性规则（可复现、可降级、零 token）；LLM 只负责打标、讲解、报告撰写与按需阅卷。

关键取舍记录在 `docs/`（未入库，仓库外仅供团队参考）：

- 错因权重为**乘性主因子**而非微调项 —— 粗心永远被压在低系数上，不进薄弱池
- 答疑与打标**搭车同一次调用** —— 画像系统的成本前提
- 画像注入经 A/B 实测为净增成本约 5%，因此默认只在诊断/报告场景注入
