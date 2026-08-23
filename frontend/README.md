# aggregator-frontend — 博主监控 + AI 笔记工作台（Web 前端）

React 18 + Vite 5 + Tailwind CSS 3 的 SPA 前端，纯读聚合 API（`docs/openapi-aggregator.yaml`），
覆盖博主监控、三件套进度（下载→转写→AI 笔记）、分组/双层标签/待分类/词库/凭据健康度等工作台页面。

- 图标：lucide-react（唯一 SVG 图标源，无 emoji）
- 路由：react-router-dom 6
- 数据请求：原生 fetch + 轻量自研 hooks（`useAsyncData` / `usePolling` / `useMutation`），统一
  `Bearer token` + envelope `{code, data, message}` 解包（见 `src/services/http.ts`）
- 颜色：全部来自 `docs/design-tokens.json` → `tailwind.config.cjs` 的 `theme.extend`，代码内无硬编码色值

## 页面清单

| 路由 | 页面 |
|------|------|
| `/` | 博主列表（首页）：博主卡片 + 添加博主 + 手动轮询 + 引擎在线状态 + 分组过滤 |
| `/groups` | 分组管理：分组侧边栏 + 分组 CRUD + 按分组过滤博主 |
| `/creators/:id` | 博主作品列表：三件套进度条 + 状态筛选 Tab（全部/新作品/排队/下载中/转写中/笔记中/已完成/失败）+ 重试 + 打开笔记 |
| `/works/:id` | 作品详情：下载/转写/AI 笔记三张状态卡 + 打开 AI 笔记 + 失败原因 + 重试 + 关键帧 + 标签 |
| `/tags` | 标签检索：大/小标签云 → 点击显示含该标签作品 |
| `/unclassified` | 待分类队列：未归类作品池 + 手动归类（选择分组 + 可选标签） |
| `/lexicon` | 词库管理：词条 CRUD + 启停 + 权重/动作 |
| `/settings` | 设置：API 口令 + cookie 健康度 + 重新登录引导 + 轮询间隔配置 + 系统健康 |

全局：Cookie 失效横幅（NEEDS_RELOGIN 红 / WARN 黄）、Loading/Empty/Error 三态、状态徽标、
重新登录弹窗（扫码引导）、确认弹窗。

## 环境要求

- Node.js ≥ 18（开发验证于 22.x）
- npm ≥ 9

## 安装

```bash
cd frontend
npm install
```

## 启动（开发）

```bash
npm run dev
# 访问 http://localhost:5173
```

## 如何连接后端

1. 启动聚合 API（后端仓库 `backend/`）：

   ```bash
   cd backend
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. 前端默认 API 基地址 `http://127.0.0.1:8000`（CORS 已放行 5173）。
   如需覆盖，复制 `.env.example` 为 `.env.development` 并设置：

   ```dotenv
   VITE_API_BASE_URL=http://127.0.0.1:8000
   VITE_ADMIN_TOKEN=your-admin-token   # 可选；开发兜底为 dev-admin-token-change-me
   ```

3. 认证：前端自动携带 `Authorization: Bearer <ADMIN_TOKEN>`。默认 token 与后端
   `.env.example` 一致（`dev-admin-token-change-me`）。后端改了 `ADMIN_TOKEN` 时，
   在页面「设置 → API 连接与口令」填写新口令并保存（存浏览器 localStorage）。

## 构建 / 自检

```bash
npm run build        # tsc --noEmit + vite build（类型与构建双重校验）
npm run typecheck    # 仅类型检查
npm run preview      # 预览构建产物
```

## 目录结构

```
frontend/
├── src/
│   ├── main.tsx / App.tsx      # 入口装配 + 路由装配
│   ├── config/api.ts           # API 基地址 + token 管理
│   ├── types/api.d.ts          # 对齐 openapi-aggregator.yaml 的类型契约
│   ├── services/               # 每资源一文件 API 封装 + http.ts 统一客户端
│   ├── hooks/useApi.ts         # useAsyncData / usePolling / useMutation
│   ├── state/relogin.tsx       # 全局重新登录弹窗状态
│   ├── utils/                  # 常量 / 时间格式化 / 三件套阶段推导 / 事件总线
│   ├── components/
│   │   ├── layout/             # 侧栏 + 布局
│   │   ├── common/             # 状态徽标 / 三态 / 横幅 / 弹窗 / 分页
│   │   ├── creator/            # 博主卡片 + 添加博主弹窗（P9）
│   │   ├── work/               # 作品列表项 / 进度条 / 打开笔记
│   │   └── relogin/            # 重新登录弹窗（P10）
│   └── pages/                  # 8 个页面
└── tailwind.config.cjs         # 设计 Token 落地（docs/design-tokens.json）
```

## 已知范围说明（MVP 诚实边界）

- 作品封面/关键帧为本地媒体文件，后端未挂静态服务，前端以占位缩略展示，不请求不存在的外链图片。
- 「打开 AI 笔记」复制 Obsidian 笔记相对路径（无后端文件服务，不直接预览）。
- P9 添加博主弹窗中的「轮询间隔 / 最低画质」为展示性字段（P1 由监控层统一调度），不随 API 提交。
- 待分类手动归类（P6）已对接 `POST /works/:id/classify`；抖音点赞/收藏自动检测属 P2，前端已就绪。
- 轮询间隔配置（P8）为展示 + 说明，实际由监控层环境变量控制。
