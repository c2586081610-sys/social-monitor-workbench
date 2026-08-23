# MVP 后端 — 聚合 API + 监控层

四平台（B站/小红书/推特X/抖音）博主监控 + 三件套（下载→转写→语义关键帧→AI 笔记）聚合后端。

- 聚合 API：FastAPI 薄层 + SQLite（`backend/`）
- 监控层：独立进程 + APScheduler（`monitor/`），与 API 解耦可恢复
- AI 笔记对接：`workbuddy/pending/*.json` 素材就绪清单（WorkBuddy 消费）

## 环境要求

- Python 3.11+（本仓库按 3.11 验证）
- 依赖见 `backend/requirements.txt`：
  `fastapi uvicorn sqlalchemy pydantic apscheduler feedparser cryptography httpx`

## 安装

```bash
pip install -r backend/requirements.txt
```

## 配置

环境变量（全部可选，默认开箱即用；生产必改 `ADMIN_TOKEN`）：

```bash
ADMIN_TOKEN=your-admin-token        # Bearer token，默认 dev-admin-token-change-me
DATABASE_PATH=.../aggregator.db     # 默认工作区根/aggregator.db
MEDIA_ROOT=.../media                # 默认工作区根/media
OBSIDIAN_ROOT=.../Obsidian          # 默认工作区根/Obsidian
WORKBUDDY_DIR=.../workbuddy         # 默认工作区根/workbuddy（pending 清单目录）
RSSHUB_BASE_URL=http://127.0.0.1:1200   # 自建 RSSHub（B站/小红书/推特轮询用）
MONITOR_HEARTBEAT_TIMEOUT=60        # 监控层心跳超时（秒）
ENABLE_DOUYIN_CDP=false             # 抖音 CDP 会话开关（P1 占位）
MONITOR_RUN_PIPELINE=false          # 流水线自动执行（需安装下载/转写引擎，Phase 5）
```

完整项见 `backend/.env.example`。

## 启动

### 1. 聚合 API

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
# 交互文档 http://127.0.0.1:8000/docs
```

### 2. 监控层（可选，独立进程）

```bash
python monitor/main.py
```

### 3. 快速验证

```bash
TOKEN=your-admin-token
# 无 token → 401
curl http://127.0.0.1:8000/api/v1/creators
# 带 token → 200
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/creators
# 系统健康
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/health/system
```

## 测试

```bash
cd backend
python -m pytest tests -q
# 覆盖：creators CRUD、works 列表/详情/重试/分析/归类/关键帧、groups/tags/lexicon、
#       unclassified、health、monitor/poll（离线 1002）、wechat 501 占位
```

## 目录结构

```
backend/
├── app/
│   ├── main.py            # 入口：只装配
│   ├── core/              # config/security/errors/db
│   ├── models/            # 一表一文件（9 张表）
│   ├── schemas/           # Pydantic 请求/响应
│   ├── repositories/      # 数据访问
│   ├── services/          # 业务逻辑
│   ├── api/               # 路由（27 端点）
│   └── utils/             # 纯函数
├── tests/                 # pytest 冒烟 + 集成
└── migrations/            # SQLite 迁移存档
monitor/
├── main.py                # APScheduler 调度入口
├── platforms/             # rsshub / douyin_cdp / douyin_like(P2) / fallback
├── pipeline/              # download / transcribe / frames / notify
└── store/                 # 共享 SQLite
workbuddy/pending/         # 素材就绪清单（WorkBuddy 消费）
```

## 接口契约

唯一依据：`docs/openapi-aggregator.yaml`。统一响应 `{code, data, message}`，错误码见 SPEC §4.1（401/404/409/422/501/1001/1002/2001）。
