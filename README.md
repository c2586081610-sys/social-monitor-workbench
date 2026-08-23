# 博主监控工作台（Social Monitor Workbench）

自动监测小红书/抖音/推特/B站博主的新作品，完成「下载(最低画质) → 字幕/语音转文字 → AI笔记」三件套，双端沉淀：**Obsidian 文件体系**（存储+查看）+ **Web 前端**（可视化进度）。

## 核心架构

```
[监控层]  RSSHub + 抖音CDP会话 + changedetection.io 兜底 + 点赞收藏监控
   → 检测新作品(去重)
[下载层]  jiji262(抖音) + yutto(B站) + XHS-Downloader(小红书) + yt-dlp/cobalt(通用)
   → 最低可用画质
[转写层]  FunASR/SenseVoice + paraformer-zh（中文最优，CPU 远超实时）
[素材归档] media/{分组}/{博主}/{日期-标题}/ {video, transcript, frames/}
[AI笔记层] WorkBuddy（读转写稿+语义对齐关键帧）→ 生成笔记+双层标签
[Obsidian] Obsidian/{分组}/{博主}/{日期-标题}.md（唯一AI总结，链接引用素材）
[Web前端]  博主列表/作品三件套进度/分组管理/标签检索/待分类队列/Cookie健康
```

## 目录结构

| 目录 | 说明 |
|------|------|
| `docs/` | 规格文档（SPEC/OpenAPI/设计Token） |
| `backend/` | FastAPI 聚合 API（27 端点 + SQLite 状态机） |
| `monitor/` | 监控层（RSSHub/CDP/调度/流水线：下载→转写→抽帧） |
| `frontend/` | React + Vite + Tailwind 前端（10 页面） |
| `tools/` | 第三方工具集成（jiji262 等）与 cookie 提取脚本 |

## 快速开始（本机 Windows）

```bash
# 1. 后端
cd backend && pip install -r requirements.txt
cp .env.example .env   # 配置 ADMIN_TOKEN 等
uvicorn app.main:app --port 8000

# 2. 前端
cd frontend && npm install && npm run dev

# 3. 监控层（可选，跑流水线）
cd monitor && python main.py
```

## 文档索引

- `项目总览与实施计划.md` — 总目录 + Phase 0-5+ 计划 + 端到端验证记录
- `需求框架_v0.1.md` — 需求澄清固化（分组/标签/语义对齐抽帧/词库/公众号）
- `MVP_PRD_v0.2.md` — 产品需求（四平台、两阶段、12 条验收）
- `SPEC_v1.md` — 规格契约（技术栈/API/页面/Token/验收）
- `docs/openapi-aggregator.yaml` — 聚合 API OpenAPI 3.0 契约
- `GitHub同类软件调研报告.md` — 竞品全景 + 抖音专项深挖
- `开源项目最终合并清单.md` — 选型交叉验证版

## 关键发现（端到端实测）

1. **抖音下载用 jiji262，`video_quality` 建议 480p**——`lowest` 档无音轨（实测确认），无法转写
2. **转写用 FunASR paraformer-zh**——中文带标点，支持句级时间戳扩展（供语义对齐抽帧）
3. **抖音 cookie 用 Playwright 持久化 profile** 捕获（Edge v20 加密解不开，浏览器会话最稳）
4. **AI 笔记零 API**——全部由 WorkBuddy 执行（定时自动化 + 对话手动）

## 许可说明

本项目为个人知识库工具。集成的第三方组件均采用开源许可证（yt-dlp/Unlicense、FunASR/MIT、jiji262/MIT 等），详见各子目录 LICENSE 或项目主页。
