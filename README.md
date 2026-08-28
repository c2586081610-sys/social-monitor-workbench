# 博主监控工作台（Social Monitor Workbench）

自动监测小红书/抖音/推特/B站博主的新作品，完成「下载(最低画质) → 字幕/语音转文字 → AI笔记」三件套，双端沉淀：**Obsidian 文件体系**（存储+查看）+ **Web 前端**（可视化进度）。

## 核心架构

```
[监控层]  RSSHub(自建) + 抖音CDP会话 + 关键词/博主轮询
   → 检测新作品(去重)
[下载层]  jiji262(抖音) + yutto(B站) + XHS-Downloader(小红书) + yt-dlp/curl_cffi(推特)
   → 最低可用画质
[评论层]  MediaCrawler(小红书/抖音/B站 全量评论+子评论，按赞排序+置顶识别)
[转写层]  FunASR paraformer-zh（中文最优，句级时间戳，CPU 远超实时）
[素材归档] media/{分组}/{博主}/{日期-标题}/ {video, transcript, frames/, images/, comment_images/}
[AI笔记层] WorkBuddy（读转写稿/图文+语义对齐关键帧+评论榜单）→ 生成笔记+双层标签
[Obsidian] Obsidian/{分组}/{博主}/{日期-标题}.md（唯一AI总结，链接引用素材）
[Web前端]  博主列表/作品三件套进度/分组管理/标签检索/待分类队列/Cookie健康
```

## 目录结构

| 目录 | 说明 |
|------|------|
| `docs/` | 规格文档（SPEC/OpenAPI/设计Token） |
| `backend/` | FastAPI 聚合 API（27 端点 + SQLite 状态机） |
| `monitor/` | 监控层（RSSHub/CDP/调度/流水线：下载→转写→抽帧） |
| `frontend/` | React + Vite + Tailwind 前端（8 路由：仪表盘/创作者作品/作品详情/分组/标签/待分类/词库/设置） |
| `tools/` | 自研脚本（cookie 捕获/笔记提取/评论抓取/流水线测试）+ 第三方工具目录 |
| `config/` | 运行时配置（cookie 等**敏感文件不入库**，见 `.gitignore`） |

### tools/ 自研脚本（入库）

| 脚本 | 用途 |
|------|------|
| `capture_xhs_login.py` | 小红书 Playwright 交互登录 → cookie 导出 |
| `extract_xhs_cookie.py` | 从浏览器 cookie 库提取小红书 cookie（Edge 被 AppContainer 保护时不可用） |
| `extract_douyin_cookie.py` | 抖音 cookie 提取（DPAPI + AES-GCM） |
| `export_dy_cookie_edge.py` / `export_xhs_cookie_edge.py` | **从 Edge 真实 profile 提取抖音/小红书 cookie**（AppContainer 保护下唯一可行路径；前提 Edge 已关闭） |
| `xhs_fetch_notes.py` | 小红书博主笔记列表（**SSR state 提取为主** + user_posted 拦截兜底；note_id+xsec_token+time+cover，2026-08-28 修复 API 降级漏新作品） |
| `xhs_fetch_comments.py` | 小红书单笔记评论（拦截 comment API，含置顶识别/按赞排序） |
| `xhs_voice_extract.py` | 小红书语音评论转写提取（DOM audio-comment-container 服务端转写，需日常 Edge CDP 9222） |
| `xhs_comment_analyze.py` | 评论完整分析（层级重组/置顶/点赞排序/图片/语音标记） |
| `xhs_note_dl.py` | 小红书作品图文下载（浏览器拦截，带 xsec_token） |
| `mc_xhs_comments.py` | MediaCrawler 评论采集封装（detail 模式全量，上限 1000，需带 xsec_token 的完整 URL） |
| `xhs_pull_all.py` | **小红书博主作品批量扒取**（自动拉列表 → 逐篇 MediaCrawler detail 内容+全量评论；断点续传/风控间隔） |
| `fetch_works_cover.py` | **作品封面下载到本地**（各平台防盗链需对应 Referer，存 media/cover/{id}.jpg，DB cover_url 改本地路径） |
| `mc_comment_report.py` | 评论报告汇总 |
| `xhs_comments_full.py` | 评论全量采集（旧版） |

### 第三方工具（git clone 安装，不入库）

| 工具 | 来源 | 用途 |
|------|------|------|
| jiji262/douyin-downloader | GitHub | 抖音视频下载（480p） |
| yutto | PyPI | B站视频下载 |
| XHS-Downloader | GitHub JoeanAmier | 小红书图文/视频下载 |
| MediaCrawler | GitHub NanmiCoder | 全量评论采集（小红书/抖音/B站） |
| RSSHub | GitHub DIYgod | 博主更新监控源（自建实例） |
| yt-dlp / curl_cffi | PyPI | 通用下载 / 推特抓取 |

## 快速开始（本机 Windows）

```bash
# 1. 后端
cd backend && pip install -r requirements.txt
cp .env.example .env   # 配置 ADMIN_TOKEN 等
# 可选：MEDIA_BASE_URL=http://127.0.0.1:8000（默认已是此值；NAS/局域网部署时改为实际地址，
#        否则前端跨源加载作品封面/媒体会 404 —— 后端返回的 /media/... 相对路径会被浏览器按前端域名解析）
uvicorn app.main:app --port 8000

# 2. 前端
cd frontend && npm install && npm run build
# 或 npm run dev（开发模式）

# 3. 监控层（可选，跑流水线）
cd monitor && python main.py

# 4. 一键启动全部（后端+前端预览+监控）
start_all.bat
```

## 媒体与封面机制（v0.6）

```
平台封面(cover_url) → fetch_works_cover.py 下载到 media/cover/{work_id}.jpg（带平台 Referer 绕防盗链）
  → DB cover_url 更新为 /media/cover/{work_id}.jpg
  → FastAPI /media 静态服务（main.py mount）
  → 序列化时按 MEDIA_BASE_URL 拼绝对 URL（前端不同源可加载）
```

- 各平台适配器落库时写入 cover_url：小红书=SSR `cover.urlPre`、抖音=MediaCrawler `video.cover.url_list[0]`、B站/推特=RSSHub 条目 `image`（推文取首图）
- 新爬取的作品封面自动落库；历史作品用 `python tools/fetch_works_cover.py` 一次性回填下载
- 纯文本推文/无封面笔记无图可提取 → 前端占位兜底
- **部署注意**：`backend/.env`（不是项目根 .env，config.py 按 backend/ 定位）设 `MEDIA_BASE_URL=<本机后端地址>`，否则封面为相对路径在跨源时 404

## 平台接入状态（端到端实测已通，2026-08-28 四平台自动监测 + 封面就绪）

| 平台 | 自动监测 | 下载 | 转写/图文 | 评论 | 封面 | 说明 |
|------|----------|------|-----------|------|------|------|
| 抖音 | ✅ MediaCrawler DouYinClient（Edge cookie，首页 1 页增量） | ✅ jiji262 480p | ✅ paraformer+词库抽帧 | ✅ MediaCrawler | ✅ 20/20 | cookie 过期重跑 `export_dy_cookie_edge.py` |
| B站 | ✅ RSSHub bilibili 路由 | ✅ yutto 360P | ✅ paraformer+301帧 | ✅ MediaCrawler | ✅ 2/2 | 无需登录 |
| 小红书 | ✅ Playwright 拦截 user_posted + **SSR state 提取**（cookie 降级不漏新作品） | ✅ XHS-Downloader（带 xsec_token） | ✅ 图文直存+评论榜单 | ✅ MediaCrawler 全量（上限 1000）/自研 | ✅ 94/104 | cookie 过期重跑 `export_xhs_cookie_edge.py`；批量扒取用 `xhs_pull_all.py` |
| 推特X | ✅ RSSHub twitter 路由（需代理） | ✅ yt-dlp/curl_cffi | ✅ 图文直存 | ⏳ 需海外 VPS | ✅ 7/13（纯文本无图） | 国内需代理；TLS 指纹须 curl_cffi；封面=推文首图 |

> 监测方式说明：抖音/小红书用本地 cookie + 浏览器方案（不依赖 RSSHub）；B站/推特走 RSSHub 稳定路由。
> "立即爬取"按钮 = 后端拉起一次性爬取子进程（onetime_poll.py），跑完自动关闭，无常驻。

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
3. **抖音/小红书 cookie 用 Playwright 持久化 profile 捕获**——浏览器 cookie 库被 Windows 安全机制保护（Edge AppContainer / DPAPI），浏览器会话最稳
4. **小红书 2024 后强制 xsec_token**——作品 URL 必须带 token，笔记列表用拦截 API 方式获取
5. **小红书置顶评论识别（第一性原理）**——评论列表第一条若点赞非全局最高，即为置顶
6. **梯子全局代理会挡小红书**——所有 Playwright/MediaCrawler 抓取须 `msedge channel + --no-proxy-server`
7. **AI 笔记零 API**——全部由 WorkBuddy 执行（定时自动化 + 对话手动）

## 安全说明

- **敏感文件一律不入库**：cookie（`config/*.json`）、浏览器登录态（`tools/*_profile/`）、数据库（`aggregator.db`）、个人 Obsidian 笔记、媒体素材
- 第三方工具源码/二进制不入库，clone 安装后按 README 配置
- 详见 `.gitignore`

## 许可说明

本项目为个人知识库工具。集成的第三方组件均采用开源许可证（yt-dlp/Unlicense、FunASR/MIT、jiji262/MIT、MediaCrawler/非商用学习、XHS-Downloader/GPL-3.0 等），详见各子目录 LICENSE 或项目主页。

