# SPEC v1 — 规格契约：四平台博主监控 + 三件套 AI 笔记 + 分组/标签/Obsidian 工作台

> **版本**：v1.0（Phase 3 规格锁定）
> **作者**：首席架构师 高见远
> **日期**：2026-08-22
> **状态**：已授权开发，规格即契约（可寻址交付物，随实现保持鲜活）
> **前置文档**：《MVP_PRD_v0.2》（已授权）、《MVP架构定稿_v1》、《需求框架_v0.1》、《开源项目最终合并清单》
> **契约伴侣**：`docs/openapi-aggregator.yaml`（OpenAPI 3.0，前后端唯一联调依据）
> **配套决策**：ADR 编号见 §14（本次 SPEC 阶段新建 ADR-004/005/006，见 `docs/decisions/`）

---

## 0. 契约声明（读我）

1. 本规格是**给执行者的契约**，不是背景说明。凡规格钉死的（文件/接口/版本/范围/坑），执行者不得自由发挥；规格没写的，按"不做"处理（§3 Out-of-Scope）。
2. **接口契约唯一依据** = `docs/openapi-aggregator.yaml`。前端据此生成 TS 类型 + MSW Mock；后端据此实现。API 变更必须先改 openapi.yaml 再改代码。
3. **版本锚定**：§4 技术栈表中所有版本均为"推荐锁定版本"，实际安装后以安装版本为准——先确认已安装版本，再按该版本 API 写代码（禁止按"通用印象"编 API 签名）。
4. **活规格**：实现中发现规格与实现冲突，先改规格再改代码；被证伪的约束显式修正；本文件作为可寻址产物可审计。
5. **团队级 P0 规则**（项目总监制定，贯穿全项目）：禁 emoji 当功能图标（统一 SVG 图标库）；禁紫色→粉色渐变；禁 AI 模板味占位文案；颜色一律走设计 Token，禁止硬编码散落。

---

## 1. 产品定义

**一句话**：自动监测小红书/抖音/推特X/B站博主新作品 → 最低画质下载 → 字幕/语音转文字 → **语义对齐关键帧抽取** → WorkBuddy 生成 AI 笔记（双层标签）→ 沉淀为 Obsidian 知识库 + Web 前端可视化工作台。

**核心价值**（差异化）：
1. 四平台统一监控（RSSHub 稳定路由 + 抖音 CDP 持活会话 + changedetection.io 兜底）。
2. **语义对齐抽帧**：按转写稿时间戳判断重点 → 抽对应时间点画面，不做固定秒数/随机抽帧。
3. **词库驱动**：可增删词库，转写稿命中词库 → 量化增删关键帧。
4. 双层标签（大 #财经 + 小 #美联储）+ 手动分组（一博主一组）+ 标签检索。
5. AI 笔记零 API 成本：全部由 WorkBuddy 执行（定时自动化 + 对话手动双触发），本地 FunASR 转写。
6. 存储规范清晰：媒体库与 Obsidian 分离，AI 摘要唯一副本在 Obsidian，链接引用素材。

**目标用户**：内容/竞品调研者、自媒体运营、个人知识管理用户（技术中低，能扫码/填 cookie，不能要求写代码）。

---

## 2. 范围与阶段划分（MVP 范围明确锁定）

### 第一阶段（P1）— 博主监控主链路，发布门槛
**范围**：PRD v0.2 的 F1-F10 全部（构成闭环，缺一不可）。
| 功能 | 说明 |
|------|------|
| F1 博主管理 | 四平台添加/删除/启停，主页链接或 UID，添加时选平台 + 归组 |
| F4 定时轮询 + 增量去重 | RSSHub 平台 5-10min；抖音 CDP 会话检测间隔默认 ≥10min（可配）；按 (platform, external_id) 去重；SQLite 持久化 |
| F3 自动触发三件套 | 新作品 → 下载（最低画质）→ 转写（带时间戳）→ 语义关键帧 → AI 笔记（WorkBuddy，定时+手动双触发） |
| F7 分组管理 | 手动增删分组；一博主只归一组；目录 `Obsidian/{分组}/{博主}/...` 联动 |
| F8 双层标签 | AI 生成大标签 + 小标签；前端标签入口，点标签显示所有含该标签视频 |
| F9 语义对齐抽帧 | 转写稿时间戳 → 词库/规则命中 → 标记重点时间窗口 → 抽帧 → `frame_manifest.json` |
| F10 词库系统 | 词库 CRUD + 词条增删 + 命中接口 + 量化增删帧槽位（机制细节 B4 Backlog） |
| F2 凭据健康度 | 多平台 cookie/CDP 会话：OK / WARN / NEEDS_RELOGIN，失效不静默 |
| F6 失败重试 | 任务落库、可重试、重启恢复 pending |
| F5 聚合前端 | 博主/作品/三件套进度/关键帧/分组/标签/设置；**待分类入口 P1 空态预留** |

**P1 门禁（完成定义）**：
- 四平台各 1 位博主端到端跑通：检测 → 下载 → 转写 → 语义关键帧 → AI 笔记 → 前端全绿可打开笔记。
- 分组管理、双层标签、词库基础版可用。
- Cookie/会话失效引导闭环（重登后恢复，任务不丢）。
- 验收口径：单作品 ≤3 分钟短视频，端到端 <10 分钟（10 分钟长视频不进验收口径）。

### 第二阶段（P2）— 点赞收藏 + 待分类，增强
**范围**：F11 抖音点赞/收藏适配器（TikTokDownloader）+ F12 待分类队列完整版。
- 流程：检测新点赞/收藏 → 下载最低画质 → 转写 → AI 分析（分类/打标签，WorkBuddy）→ 落入 `media/待分组/` + `Obsidian/待分组/` → 前端"待分类"入口 → 用户手动归类后原子移入对应分组目录（media 与 Obsidian 双目录）。
- **P2 门禁**：P1 验收通过后启动；TikTokDownloader 点赞/收藏增量接口 spike#1（§13.2）通过；用户本人抖音登录态就绪。

### Backlog（不阻塞 MVP，明确不做）
- B1 公众号模块（接口预留 `POST /api/v1/wechat/import`，前端入口空态，不做自动监测、不做 AI 分析）
- B2 通知推送（Webhook/Bark/Email）
- B3 历史回填 / 批量导入博主
- B4 词库机制细化（权重合并/阈值/冲突规则）
- NAS 迁移预案（部署后）
- 多账号、评论抓取、直播监控、视频号/快手

### 明确不做（Out-of-Scope，出现即视为镀金）
1. 不购买/不接入任何 LLM API；AI 笔记一律走 WorkBuddy。
2. 不做固定秒数抽帧/随机抽帧作为主路径（仅作"无时间戳"降级）。
3. 不重写 yutto / XHS-Downloader / TikTokDownloader / jiji262 内部逻辑；只以 CLI/子进程/API 方式调用，不改其代码（许可证隔离，见 §11.3）。
4. 不做评论抓取、直播监控、多账号、历史回填。
5. 不做移动端；不引入外部字体/图片资源（离线优先）。
6. 前端"待分类"页 P1 只做路由 + 空态，不实现归类交互（归类交互随 F12 进 P2）。

---

## 3. 技术架构（每层技术 + 版本锚定）

> **版本规则**：下表版本为推荐锁定值，**实际以安装为准**（`pip freeze` / `package.json` / 容器 tag 为准）。执行者先确认已安装版本，再按该版本 API 写代码。禁止凭空编造依赖与方法。

### 3.1 总体分层图

```
┌────────────────────────────────────────────────────────────────────┐
│ 前端（React SPA，本机 localhost 访问）                                 │
│ React 18 + Vite 5 + Tailwind 3 + lucide-react(SVG) + Router + Query │
└───────────────┬────────────────────────────────────────────────────┘
                │ HTTP/JSON（Bearer token） 唯一入口 = 聚合 API
┌───────────────▼────────────────────────────────────────────────────┐
│ 聚合 API（FastAPI 薄层，自研）· SQLite（唯一数据源）                    │
│ creators / works / groups / tags / unclassified / lexicon /        │
│ health / monitor / retry / analyze / classify / wechat-import      │
├────────────────────────────────────────────────────────────────────┤
│ 监控层（自研 Python 调度 + 第三方服务，解耦部署）                       │
│ RSSHub(自建) + changedetection.io(兜底) + 抖音 CDP 会话(Patchright)  │
│ + TikTokDownloader 适配器(P2)                                       │
├────────────────────────────────────────────────────────────────────┤
│ 流水线（下载 → 转写 → 语义抽帧）                                      │
│ jiji262(douyin) · yutto(bilibili) · XHS-Downloader(xhs) ·          │
│ yt-dlp(twitter) → FunASR/SenseVoice(带时间戳) → ffmpeg 抽帧+词库命中 │
├────────────────────────────────────────────────────────────────────┤
│ AI 笔记层（无 API）                                                  │
│ WorkBuddy：定时自动化 + 对话手动触发 → 读「素材就绪清单」→ 生成 Obsidian │
│ 笔记 + 双层标签（唯一 AI 摘要副本）                                    │
├────────────────────────────────────────────────────────────────────┤
│ 存储：SQLite(状态) + 文件系统 media/(素材) + Obsidian/(笔记)          │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 技术选型表（版本锚定）

| 层 | 技术 | 版本（以实际安装为准） | 许可证 | 部署形态 |
|----|------|------------------------|--------|----------|
| 前端框架 | React | 18.3.x | MIT | npm |
| 前端构建 | Vite | 5.x | MIT | npm |
| 样式 | Tailwind CSS | 3.4.x | MIT | npm |
| 图标（**唯一 SVG 图标源**） | lucide-react | 0.4xx（以安装为准） | ISC/MIT | npm |
| 路由 | react-router-dom | 6.x | MIT | npm |
| 数据请求 | @tanstack/react-query | 5.x | MIT | npm |
| 聚合 API | FastAPI | 0.115.x | MIT | pip |
| API 服务 | uvicorn | 0.30.x | BSD-3-Clause | pip |
| ORM | SQLAlchemy | 2.0.x | MIT | pip |
| 校验 | Pydantic | 2.x | MIT | pip |
| 数据库 | SQLite | 3.4x（系统自带） | 公有域 | 文件 |
| 调度 | APScheduler | 3.10.x | MIT | pip |
| RSS 解析 | feedparser | 6.x | BSD-2-Clause | pip |
| 浏览器自动化（抖音 CDP 持活会话） | Patchright（优先）/ Playwright | 1.4x | Apache-2.0 | pip |
| 监控兜底 | changedetection.io | 0.4x | Apache-2.0 | Docker（独立服务） |
| RSS 源 | RSSHub（自建实例） | 最新 release | AGPL-3.0 | Docker（独立服务） |
| 抖音下载 | jiji262/douyin-downloader | main（V2.0） | MIT | CLI 子进程 |
| B站下载 | yutto | 2.x | GPL-3.0 | CLI 子进程 |
| 小红书下载 | XHS-Downloader | 3.x | GPL-3.0 | CLI 子进程 |
| 推特下载 | yt-dlp | 2026.x | Unlicense | CLI 子进程 |
| 抖音点赞收藏（P2） | JoeanAmier/TikTokDownloader | 4.0 | GPL-3.0 | CLI / Web API（port 5555） |
| 转写 | FunASR + SenseVoice-Small | 1.x / 模型以安装为准 | MIT | pip（本地） |
| 转写增强（词级时间戳） | WhisperX（可选增强） | 3.x | BSD-2-Clause | pip |
| 抽帧 | ffmpeg | 7.x（以安装为准） | GPL/LGPL | 系统依赖 |
| 帧处理/查重 | OpenCV (opencv-python) | 4.9.x | Apache-2.0 | pip |
| 密钥加密 | cryptography (Fernet) | 42.x | Apache-2.0 | pip |

### 3.3 选型对比与决策记录（ADR 引用）

| 决策 | 选择 | 淘汰方案 | 理由 | ADR |
|------|------|----------|------|-----|
| 一体化引擎 | 自研薄监控 + 组件拼接 | CreatorHub（无 LICENSE、监控漏最新 open bug #17）、VideoMemo（无订阅监控、star 35） | 许可干净、增量去重可控、不双份下载 | ADR-001（沿用） |
| 前端 | React+Vite+Tailwind 自研 | Folo 打底（缺三件套进度/待分类）、CreatorHub 二开（无 LICENSE） | 需求"分组+标签+进度+待分类"四合一，无现成匹配 | ADR-002（沿用） |
| 抖音监控 | CDP 持活会话自研 | 静态 cookie（数小时失效）、yt-dlp 提取器（近期不稳） | 持活会话可续 cookie，风控可过 | ADR-003（沿用） |
| 抖音下载 | jiji262/douyin-downloader | yt-dlp（抖音提取器不稳） | MIT、去水印、内置 SQLite 去重、`video_quality` 支持 lowest（spike#1 已验证枚举） | **ADR-004（本次）** |
| 点赞收藏适配器 | TikTokDownloader | RSSHub xhs collect（脆弱）、biliFAV（许可仅学习） | 发布/喜欢/收藏批量 + 增量 + 记录已下ID | **ADR-005（本次）** |
| 数据库 | SQLite | PostgreSQL（无服务器、MVP 单机） | 单机个人工具，百万级足够 | ADR-006（本次） |

> 本次新建 ADR 落盘 `docs/decisions/ADR-004/005/006.md`（MADR 格式），由执行者在动工前补齐正文（Background/Decision/Consequences 已在本表与 §11 已知坑中给全素材）。

### 3.4 聚合 API 目录结构（点名文件，规格即契约）

> 遵循《代码组织规范》：入口只装配、单文件 ≤300 行、依赖只向下、按资源分包。

```
aggregator/
├── pyproject.toml            # 依赖与版本锁定（uv/pip 均可，实际为准）
├── app/
│   ├── main.py               # 入口：只装配（app 实例 + include_router + 启动），不写业务，<100 行
│   ├── core/
│   │   ├── config.py         # 配置加载（ADMIN_TOKEN / 路径 / 轮询间隔等，全部来自 env）
│   │   ├── security.py       # Bearer token 校验
│   │   ├── errors.py         # 业务异常 + 统一错误码
│   │   └── db.py             # SQLAlchemy engine/session
│   ├── models/               # ORM 模型（一表一文件）：group.py creator.py work.py tag.py
│   │                         #   work_tag.py task.py lexicon.py cookie.py poll_log.py
│   ├── schemas/              # Pydantic 请求/响应（一资源一文件）
│   ├── repositories/         # 数据访问（一资源一文件，纯查询无业务）
│   ├── services/             # 业务逻辑（一资源一文件，含事务编排，不 import HTTP）
│   ├── api/
│   │   ├── deps.py           # 依赖注入（当前用户、db session）
│   │   ├── creators.py       # /api/v1/creators*
│   │   ├── works.py          # /api/v1/works*
│   │   ├── groups.py         # /api/v1/groups*
│   │   ├── tags.py           # /api/v1/tags*
│   │   ├── unclassified.py   # /api/v1/unclassified
│   │   ├── lexicon.py        # /api/v1/lexicon*
│   │   ├── health.py         # /api/v1/health/*
│   │   ├── monitor.py        # /api/v1/monitor/*
│   │   └── wechat.py         # /api/v1/wechat/import（预留占位）
│   └── utils/                # 纯函数：文件名清洗 sanitize_filename / 时间戳工具
├── tests/                    # pytest：每资源 service/repo 单测 + API 集成
└── migrations/               # SQLite 迁移脚本（alembic 或手写 SQL 文件，实际为准）
```

监控层（独立进程，不并入 FastAPI 进程，解耦可恢复）：

```
monitor/
├── main.py                   # 调度入口：APScheduler 装配 + 各平台轮询任务注册
├── platforms/
│   ├── rsshub.py             # B站/小红书/推特（feedparser + 路由解析）
│   ├── douyin_cdp.py         # 抖音 CDP 持活会话 + aweme 轮询 + 健康度
│   ├── douyin_like.py        # TikTokDownloader 适配器（P2 才实现，P1 仅占位接口）
│   └── fallback.py           # changedetection.io 兜底对接
├── pipeline/                 # 流水线编排（下载→转写→抽帧→产出「素材就绪清单」）
│   ├── download.py           # 按平台路由下载器 CLI（quality=lowest）
│   ├── transcribe.py         # FunASR/SenseVoice 带时间戳转写
│   ├── frames.py             # 词库命中 + 语义对齐抽帧 + frame_manifest.json
│   └── notify.py             # 写「素材就绪清单」+ 触发 WorkBuddy 自动化标记
└── store/                    # 与聚合 API 共享 SQLite 的写入/查询（只经 repository 层）
```

---

## 4. 聚合 API 端点清单（方法 / 路径 / 功能 / 认证 / 请求 / 响应）

> 完整 JSON Schema 见 **`docs/openapi-aggregator.yaml`**（前后端唯一依据）。此处为速查表。统一响应格式：`{ "code": 0, "data": {...}, "message": "" }`；`code!=0` 为错误。所有端点前缀 `/api/v1`。认证：`Authorization: Bearer <ADMIN_TOKEN>`，缺失/错误返回 `401 AUTH_REQUIRED`。

| # | 方法 | 路径 | 功能 | 认证 | 请求要点 | 响应 data |
|---|------|------|------|------|----------|-----------|
| 1 | GET | /creators | 博主列表（支持 ?group_id=&platform=&q=&page=&limit=） | 必需 | query 过滤 | `{items, total, page, limit, has_more}` |
| 2 | POST | /creators | 添加博主（选平台+归组） | 必需 | `{platform, name, profile_url, external_id, group_id?}` | 新建 Creator |
| 3 | GET | /creators/{creator_id} | 博主详情 | 必需 | path | Creator（含最近作品摘要） |
| 4 | PATCH | /creators/{creator_id} | 修改博主（改名/换组/启停） | 必需 | `{name?, group_id?, enabled?}` | 更新后 Creator |
| 5 | DELETE | /creators/{creator_id} | 删除博主 | 必需 | path | `{deleted: true}` |
| 6 | GET | /creators/{creator_id}/works | 博主作品列表 + 三件套状态 | 必需 | query 分页 | `{items, total, page, limit, has_more}` |
| 7 | GET | /works | 作品库（?group_id=&creator_id=&tag=&platform=&status=&source_type=&unclassified=true&q=） | 必需 | query 过滤 | 分页 Work |
| 8 | GET | /works/{work_id} | 作品详情（状态/标签/帧/路径） | 必需 | path | WorkDetail |
| 9 | POST | /works/{work_id}/retry | 单条重试（FAILED→QUEUED） | 必需 | path | 更新后 Work |
| 10 | POST | /works/{work_id}/analyze | 手动触发 AI 笔记（对话触发入口） | 必需 | path | `{note_pending: true}` |
| 11 | POST | /works/{work_id}/classify | 待分类手动归类（设分组+标签，可选绑博主） | 必需 | `{group_id, tags?:[], creator_id?}` | 更新后 Work（status→DONE） |
| 12 | GET | /works/{work_id}/frames | 关键帧列表（读 frame_manifest.json） | 必需 | path | `{items: Frame[]}` |
| 13 | GET | /groups | 分组列表（含博主数） | 必需 | — | `{items: Group[]}` |
| 14 | POST | /groups | 创建分组 | 必需 | `{name}` | 新建 Group |
| 15 | PATCH | /groups/{group_id} | 重命名分组 | 必需 | `{name}` | 更新后 Group |
| 16 | DELETE | /groups/{group_id} | 删除分组（组内博主移入"未分组"；组内作品保留） | 必需 | path | `{deleted: true, moved_creators: n}` |
| 17 | GET | /tags | 标签列表（含作品数，kind 过滤） | 必需 | query | `{items: Tag[]}` |
| 18 | GET | /tags/{tag_name}/works | 按标签查作品（标签检索入口） | 必需 | path + 分页 | 分页 Work |
| 19 | GET | /unclassified | 待分类队列（works WHERE group_id IS NULL AND status IN (UNCLASSIFIED, NOTE_GENERATING, DONE)） | 必需 | 分页 | 分页 Work |
| 20 | GET | /lexicon | 词库词条列表 | 必需 | — | `{items: LexiconItem[]}` |
| 21 | POST | /lexicon | 新增词条 | 必需 | `{term, action, weight?, enabled?, platform_scope?}` | 新建 LexiconItem |
| 22 | PATCH | /lexicon/{entry_id} | 修改词条 | 必需 | 部分字段 | 更新后 LexiconItem |
| 23 | DELETE | /lexicon/{entry_id} | 删除词条 | 必需 | path | `{deleted: true}` |
| 24 | GET | /health/cookie | 凭据健康度（各平台 OK/WARN/NEEDS_RELOGIN + 最近轮询时间） | 必需 | — | `{items: CookieHealth[]}` |
| 25 | GET | /health/system | 系统健康（RSSHub/changedetection/下载器/转写引擎在线状态） | 必需 | — | `{items: SystemHealth[]}` |
| 26 | POST | /monitor/poll | 手动触发轮询（立即检测新作品，含平台可选） | 必需 | `{platform?}` | `{triggered: true}` |
| 27 | POST | /wechat/import | 公众号导入（预留占位，P1 返回 501 NOT_IMPLEMENTED） | 必需 | `{url, title?}` | 501 |

### 4.1 错误码约定（全 API 统一）

| code | HTTP | 含义 |
|------|------|------|
| 0 | 200/201 | 成功 |
| 401 | 401 | 未认证 / token 缺失或错误 |
| 404 | 404 | 资源不存在 |
| 409 | 409 | 冲突（如博主重复、分组重名、作品重复） |
| 422 | 422 | 参数校验失败 |
| 501 | 501 | 功能未实现（预留占位） |
| 1001 | 503 | 流水线引擎离线（下载器/转写不可用） |
| 1002 | 503 | 监控层离线 |
| 2001 | 409 | Cookie 失效，需重新登录（NEEDS_RELOGIN，业务错误非 5xx） |

---

## 5. 数据库表清单（SQLite，一库 `aggregator.db`）

> 表名蛇形复数；每表必有 `id INTEGER PRIMARY KEY AUTOINCREMENT`、`created_at TEXT`、`updated_at TEXT`。软删除用 `deleted_at`（本 MVP 直接 DELETE，不用软删）。时间统一存 ISO-8601 UTC 字符串。外键显式声明并开启 `PRAGMA foreign_keys=ON`。

### groups — 分组
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| name | TEXT | UNIQUE NOT NULL | 分组名（如"财经"） |
| created_at / updated_at | TEXT | NOT NULL | |

### creators — 博主
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| group_id | INTEGER | FK→groups.id, ON DELETE SET NULL, NULLABLE | NULL=未分组 |
| platform | TEXT | NOT NULL, CHECK IN ('douyin','bilibili','xhs','twitter','wechat') | |
| name | TEXT | NOT NULL | 博主昵称 |
| profile_url | TEXT | NOT NULL | 主页链接 |
| external_id | TEXT | NOT NULL | sec_uid / uid / user_id / handle（平台唯一标识） |
| enabled | INTEGER | NOT NULL DEFAULT 1 | 启停 |
| last_poll_at | TEXT | NULL | 最近轮询时间 |
| last_work_at | TEXT | NULL | 最近作品时间 |
| created_at / updated_at | TEXT | NOT NULL | |
| — | — | **UNIQUE(platform, external_id)** | 幂等添加 |

### works — 作品（核心状态机）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| creator_id | INTEGER | FK→creators.id, ON DELETE SET NULL, NULLABLE | 点赞收藏源作品 creator 可为 NULL |
| platform | TEXT | NOT NULL | douyin/bilibili/xhs/twitter |
| external_id | TEXT | NOT NULL | aweme_id / avid / note_id / tweet_id |
| title | TEXT | NOT NULL | |
| url | TEXT | NOT NULL | |
| published_at | TEXT | NULL | 发布时间 |
| source_type | TEXT | NOT NULL DEFAULT 'monitor' | monitor / like / favorite / manual |
| status | TEXT | NOT NULL DEFAULT 'NEW' | 状态机见下 |
| task_id | TEXT | NULL | 流水线任务 id |
| media_path | TEXT | NULL | `media/{分组}/{博主}/{日期}-{标题}/` 相对路径 |
| transcript_path | TEXT | NULL | 转写稿路径 |
| frame_manifest_path | TEXT | NULL | `frames/frame_manifest.json` |
| note_path | TEXT | NULL | Obsidian 笔记相对路径（**唯一 AI 摘要副本**） |
| group_id | INTEGER | FK→groups.id, NULLABLE | NULL = 待分类（P2） |
| retry_count | INTEGER | NOT NULL DEFAULT 0 | |
| last_error | TEXT | NULL | |
| created_at / updated_at | TEXT | NOT NULL | |
| — | — | **UNIQUE(platform, external_id)** | 跨来源幂等去重 |

**作品状态机**：
```
NEW → QUEUED → DOWNLOADING → TRANSCRIBING → FRAME_EXTRACTING → NOTE_GENERATING → DONE
   ↘ FAILED（可重试，重试上限 3 次 + 冷却）
NEW(like/favorite) → ... → NOTE_GENERATING → UNCLASSIFIED（group_id=NULL，待分类池）
UNCLASSIFIED →(POST /works/:id/classify)→ DONE（group_id 已设）
任何状态检测到 Cookie 失效 → 状态保留 + cookie 标记 NEEDS_RELOGIN（不静默、不丢任务）
```

### tags — 标签
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| name | TEXT | UNIQUE NOT NULL | 标签名（不带 #，展示时加 #） |
| kind | TEXT | NOT NULL DEFAULT 'small' | big=大标签 / small=小标签 |
| created_at / updated_at | TEXT | NOT NULL | |

### work_tags — 作品×标签（多对多）
| 字段 | 类型 | 约束 |
|------|------|------|
| work_id | INTEGER | FK→works.id ON DELETE CASCADE, PK |
| tag_id | INTEGER | FK→tags.id ON DELETE CASCADE, PK |

### tasks — 任务（阶段级状态，一作品多阶段记录）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| work_id | INTEGER | FK→works.id ON DELETE CASCADE, NOT NULL | |
| stage | TEXT | NOT NULL | parse / download / transcribe / frames / note |
| status | TEXT | NOT NULL | pending / running / succeeded / failed |
| attempts | INTEGER | NOT NULL DEFAULT 0 | |
| error | TEXT | NULL | |
| created_at / updated_at | TEXT | NOT NULL | |
| — | — | **UNIQUE(work_id, stage)** | 每作品每阶段一行（重试更新同行） |

### lexicon — 词库（语义对齐抽帧驱动）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| term | TEXT | UNIQUE NOT NULL | 触发词（如"A股""走势""表格"） |
| action | TEXT | NOT NULL DEFAULT 'increase' | increase=增加关键帧 / decrease=减少关键帧 |
| weight | REAL | NOT NULL DEFAULT 1.0 | 权重（B4 细化，预留字段） |
| enabled | INTEGER | NOT NULL DEFAULT 1 | 启停 |
| platform_scope | TEXT | NULL | NULL=全平台生效（预留按平台隔离） |
| created_at / updated_at | TEXT | NOT NULL | |

### cookies — 凭据健康度（每平台一条）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| platform | TEXT | UNIQUE NOT NULL | douyin / bilibili / xhs / twitter |
| status | TEXT | NOT NULL DEFAULT 'UNKNOWN' | OK / WARN / NEEDS_RELOGIN / UNKNOWN |
| last_checked_at | TEXT | NULL | |
| expires_at | TEXT | NULL | |
| note | TEXT | NULL | 失效原因（403/461/471/验证码/空响应） |
| updated_at | TEXT | NOT NULL | |

> **凭据本体不落数据库**：抖音 CDP 会话 profile 存浏览器数据目录（加密/权限受限目录），各下载器 cookie 存各自 config（加密存储 Fernet，密钥存 env）；仅健康度元数据落 cookies 表。

### poll_logs — 轮询日志（诊断用，P1 必写）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| platform | TEXT | NOT NULL | |
| started_at / finished_at | TEXT | NULL | |
| status | TEXT | NOT NULL | ok / fail |
| detail | TEXT | NULL | 失败原因分类（风控/cookie/网络/路由失效） |

### 索引清单（MVP 阶段索引，不过度建）
1. `works(status)` — 待分类/失败队列查询
2. `works(group_id)` — 分组浏览
3. `works(creator_id)` — 博主作品列表
4. `works(platform, external_id)` — 唯一约束自带索引（幂等去重）
5. `work_tags(tag_id)` — 标签检索
6. `creators(group_id)` — 分组博主列表
7. `cookies(platform)` — 唯一约束自带索引

---

## 6. 页面清单（页面 → 路由 → 核心组件 → 对应 API）

> 前端为 React SPA，路由前缀 `/`。所有页面为中文界面（预留 i18n 结构）。组件按功能拆分，API 调用统一封装在 `src/services/`。

| # | 页面 | 路由 | 核心组件 | 对应 API |
|---|------|------|----------|----------|
| 1 | 仪表盘（默认） | `/` | CreatorList、WorkCard、HealthBanner | GET /creators、GET /works（最近）、GET /health/cookie |
| 2 | 博主管理 | `/creators` | CreatorTable、AddCreatorModal（平台选择+归组）、GroupSidebar | GET/POST/PATCH/DELETE /creators；GET /groups |
| 3 | 博主详情 | `/creators/:id` | WorkList、StatusBadge（三状态灯+进度）、OpenNoteButton | GET /creators/:id、GET /creators/:id/works |
| 4 | 作品库 | `/works` | WorkList（过滤条）、StatusBadge、FrameThumb | GET /works |
| 5 | 作品详情 | `/works/:id` | StageProgress、FrameGallery、TagList、OpenNote、RetryButton、ClassifyPanel | GET /works/:id、GET /works/:id/frames、POST retry/analyze/classify |
| 6 | 分组管理 | `/groups` | GroupList、AddGroupModal、DeleteGroupConfirm | GET/POST/PATCH/DELETE /groups |
| 7 | 标签检索 | `/tags` | TagCloud、TagWorkList | GET /tags、GET /tags/:name/works |
| 8 | 待分类 | `/unclassified` | UnclassifiedQueue（**P1 空态占位**，P2 完整：归类表单） | GET /unclassified、POST /works/:id/classify |
| 9 | 词库管理 | `/lexicon` | LexiconTable、AddEntryModal、ActionBadge | GET/POST/PATCH/DELETE /lexicon |
| 10 | 设置 | `/settings` | CookieHealthList、SystemHealthList、WechatImportPlaceholder | GET /health/cookie、GET /health/system、POST /wechat/import（预留） |

**全局组件**：Layout（侧边导航 + 顶栏）、HealthBanner（凭据失效横幅，任意页可见）、StatusBadge（下载/转写/笔记三状态灯 + 关键帧数）、EmptyState（空态引导，禁 AI 模板味文案）、ConfirmDialog。

**前端目录结构（点名文件）**：
```
frontend/
├── src/
│   ├── main.tsx               # 入口：只装配
│   ├── App.tsx                # 路由装配
│   ├── pages/                 # 一页面一目录
│   ├── components/            # 全局组件 + 页面私有组件就近放页面目录
│   ├── services/              # API 调用封装（每资源一文件，类型来自 openapi 生成）
│   ├── types/                 # TS 类型（由 openapi-aggregator.yaml 生成/对齐）
│   ├── hooks/                 # react-query hooks
│   ├── utils/                 # 纯函数（highlightText 等）
│   ├── styles/                # Tailwind 入口 + design tokens
│   └── config/                # API base URL（env）
```

---

## 7. 设计 Token 要点（前端视觉契约）

> 完整 token 落盘 `docs/design-tokens.json` + Tailwind `theme.extend`（执行者按此落地）。**前端代码禁止裸 hex/裸色值**，一律引用 token。

### 7.1 色彩（语义化 token，禁硬编码）
| Token | 值 | 用途 |
|-------|-----|------|
| color.bg.default | `#F8FAFC` | 页面背景（slate-50） |
| color.bg.surface | `#FFFFFF` | 卡片/面板 |
| color.bg.sidebar | `#F1F5F9` | 侧边栏 |
| color.text.primary | `#0F172A` | 主文本（slate-900） |
| color.text.secondary | `#475569` | 次要文本（slate-600） |
| color.text.muted | `#94A3B8` | 弱化/占位（slate-400） |
| color.border | `#E2E8F0` | 边框/分隔（slate-200） |
| color.primary | `#2563EB` | 主色（blue-600，按钮/选中/链接） |
| color.primary.hover | `#1D4ED8` | 主色 hover（blue-700） |
| color.success | `#16A34A` | 完成/健康（green-600） |
| color.warning | `#D97706` | 警告/WARN（amber-600） |
| color.danger | `#DC2626` | 失败/失效（red-600） |
| color.info | `#0891B2` | 进行中/信息（cyan-600） |

> 状态灯语义：下载=info、转写=info、笔记=info、DONE=success、FAILED=danger、COOKIE 失效=danger 横幅、WARN=warning。

### 7.2 字体
- `font.sans`：系统字体栈（中文优先）：`-apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`（离线优先，不引外部字体）。
- `font.mono`：`ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace`（用于时间戳、ID、路径、manifest 查看）。

### 7.3 图标（P0 规则：统一 SVG 图标库）
- **锁定 `lucide-react` 为全项目唯一图标源**（SVG、stroke 风格统一、tree-shakable、MIT/ISC）。依赖随之锁定，**全项目统一不混用**。
- 图标语义映射（执行者落地时统一登记）：添加=`Plus`、删除=`Trash2`、下载=`Download`、转写=`AudioLines`/`FileText`、笔记=`FileText`/`NotebookPen`、分组=`Folder`/`FolderPlus`、标签=`Tag`/`Tags`、待分类=`Inbox`、重试=`RotateCcw`、打开=`ExternalLink`、刷新=`RefreshCw`、设置=`Settings`、警告=`AlertTriangle`、成功=`CheckCircle2`、进行中=`Loader2`（旋转动画）、失败=`XCircle`。
- **禁止**：emoji 当功能图标；引入第二套图标库。
- 关键帧缩略图用小图预览（img），不用图标代替。

### 7.4 其他
- 圆角：`rounded-md`（组件）/ `rounded-lg`（卡片）/ `rounded-full`（徽标）。
- 阴影：`shadow-sm`（卡片）/ `shadow-md`（弹窗）；不用夸张阴影。
- 动效：仅 `transition-colors`/`opacity` 轻量过渡；Loader2 旋转用于加载态；不引入动画库。
- 空态文案：明确引导（如"还没有博主，点击右上角添加第一位博主"），**禁 AI 模板味占位**（Welcome to / Lorem ipsum / 敬请期待等）。

---

## 8. 存储与目录规范（文件系统契约）

```
工作区根（用户指定，env 配置）/
├── media/                            # 媒体库（与 Obsidian 分离，只放素材）
│   └── {分组}/{博主}/{日期}-{标题}/
│       ├── video/                    # 原始视频（最低画质）
│       ├── transcript/               # 字幕/转写稿（带时间戳：.srt + .json）
│       └── frames/                   # 关键帧 + frame_manifest.json
├── Obsidian/                         # Vault（AI 摘要唯一副本，链接引用 media）
│   ├── {分组}/{博主}/{日期}-{标题}.md
│   └── 待分组/{日期}-{标题}.md        # P2：点赞收藏未归类草稿
├── aggregator.db                     # SQLite
└── workbuddy/                        # AI 笔记对接区（见 §10）
    └── pending/                      # 「素材就绪清单」*.json（WorkBuddy 读取）
```

### 8.1 命名规则（硬约束）
- 目录：`{日期}-{标题}`；日期 `YYYY-MM-DD`（发布时间，取不到用检测时间）。
- 文件名清洗 `sanitize_filename()`：移除 `/\:*?"<>|`、控制字符、首尾空格；超长（>120 字符）截断；Windows 保留名（CON/PRN 等）加前缀；**emoji 可保留在标题但清洗为安全字符**（统一替换为 `_`，避免跨平台编码坑）。
- Obsidian 笔记 frontmatter（预留，WorkBuddy 写入时按此契约）：
  ```yaml
  ---
  platform: douyin
  blogger: 张三
  url: https://...
  publish_date: 2026-08-22
  duration: 185
  tags: [财经]          # 大标签
  subtags: [美联储, A股] # 小标签
  media_path: media/财经/张三/2026-08-22-xxx/
  status: done
  ---
  ```
- **同一作品在媒体库只存一份；AI 摘要只存 Obsidian 一份**（避免双份不同步）。Obsidian 正文用相对/绝对链接引用 media 素材。

### 8.2 语义对齐抽帧契约（F9）
- 输入：带时间戳转写稿（`transcript/*.json`：`[{start, end, text}]`）+ 词库命中结果。
- 流程：转写稿 → 逐段文本 → 词库/规则匹配 → 命中词所在时间窗口标记为"重点窗口" → 在窗口内抽帧（每窗口默认 1 帧，命中词条 action=increase 按权重增帧、decrease 减帧）→ 感知哈希去重 → 输出。
- 输出：`frames/frame_0001.jpg ...` + `frames/frame_manifest.json`：
  ```json
  {
    "work_id": 12,
    "semantic_aligned": true,
    "fallback": false,
    "frames": [
      {
        "file": "frames/frame_0001.jpg",
        "time_seconds": 42.5,
        "window_start": 40.0,
        "window_end": 45.0,
        "hits": [{"term": "A股", "action": "increase", "weight": 1.0}],
        "confidence": 0.9
      }
    ]
  }
  ```
- 降级：转写稿无时间戳 → 兜底抽帧（均匀 N 帧）并 `semantic_aligned: false, fallback: true`，前端明确标注"非语义对齐"。

---

## 9. 验收标准（EARS 格式）

> EARS：Ubiquitous（恒真）/ State（状态）/ Event（事件）/ Unwanted（异常）/ Optional（可选）。每条可独立验收，验收人只对照本条判定。

| # | 类型 | 验收标准 |
|---|------|----------|
| AC-1 | Event | **当**任一平台（B站/小红书/推特X/抖音）的已启用博主发布新作品，且对应凭据有效（RSSHub 路由 / 抖音 CDP 会话 / cookie），**系统应**在约定间隔内检测到（RSSHub 平台 5-10min、抖音 ≥10min 可配置），按 (platform, external_id) 去重后自动将三件套任务入队，前端出现该作品且进度从"待处理"开始。 |
| AC-2 | Event | **当**作品进入流水线并依次完成各阶段，**系统应**使状态依次经 下载中→转写中→关键帧抽取中→笔记生成中→完成，前端三状态灯 + 关键帧数实时可见（轮询聚合 API），完成后可打开 AI 笔记。 |
| AC-3 | State | **当**作品处于已归档状态（DONE 且已归组），**系统应**将素材存放于 `media/{分组}/{博主}/{日期}-{标题}/`（video/transcript/frames/），AI 摘要唯一副本存放于 `Obsidian/{分组}/{博主}/{日期}-{标题}.md`，且两处路径与数据库记录一致。 |
| AC-4 | Event | **当**用户在标签入口点击某标签（如"美联储"），**系统应**显示所有含该标签的作品；大标签（#财经）与小标签（#美联储）在笔记 frontmatter 与前端均可见。 |
| AC-5 | Event | **当**用户创建分组并把博主归入该组，**系统应**将该博主的新作品归档到对应分组目录；**当**删除分组时，**系统应**将组内博主移入"未分组"且不删除其作品。 |
| AC-6 | Unwanted | **如果**任一平台凭据失效（CDP 会话断开/风控/403/461/471/验证码/空响应），**则系统应**将该平台 cookie 标记为 NEEDS_RELOGIN，前端任意页顶部横幅显示"需要重新登录"并引导重登，**且**该平台未完成任务保留不丢失、不静默。 |
| AC-7 | Event | **当**同一作品被重复检测（网络重试/重复轮询/点赞收藏与博主监控同时命中），**系统应**按 (platform, external_id) 唯一约束只入队一次。 |
| AC-8 | Event | **当**流水线某环节失败（下载失败/转写空文本/WorkBuddy 未触发），**系统应**标记任务 failed/retry（默认重试上限 3 次 + 冷却），保留错误信息，且可通过 `POST /works/:id/retry` 手动重试；**当**服务重启，**系统应**恢复 pending 状态任务。 |
| AC-9 | Event | **当**转写稿含时间戳且命中语义规则（如词库含"A股"），**系统应**在命中词所在时间窗口抽取画面（而非固定秒数/随机帧），产出 `frames/` + `frame_manifest.json`（含时间窗口/命中词/置信度）。 |
| AC-10 | Event | **当**转写稿命中启用中的词库词条（action=increase/decrease），**系统应**按该词条动作与权重量化增删对应时间窗口的关键帧；**当**词条被删除或停用，**系统应**不再因其触发抽帧。 |
| AC-11 | Unwanted | **如果**转写稿无时间戳或转写为空文本，**则系统应**分别执行：无时间戳→降级兜底抽帧并标注"非语义对齐"；空文本→跳过 AI 总结并在前端提示，任务可重试。 |
| AC-12 | Event | **当**用户手动触发 AI 笔记（对话手动入口 `POST /works/:id/analyze`），**系统应**生成/更新「素材就绪清单」（`workbuddy/pending/`），供 WorkBuddy 读取执行；笔记完成前作品状态保持 NOTE_GENERATING/pending，前端提示"待 AI 生成"。 |
| AC-13 | Event（P2） | **当**抖音点赞/收藏监控启用且检测到新点赞/收藏，**系统应**完成下载→转写→AI 分析后落入"待分类"池（`media/待分组/` + `Obsidian/待分组/`，group_id=NULL），前端"待分类"入口可见；**当**用户选择分组+确认标签并归类，**系统应**原子移动 media 与 Obsidian 双目录并更新状态为 DONE。 |
| AC-14 | Ubiquitous | **系统应**在所有列表接口支持分页（page/limit/has_more），聚合 API 读接口 p95 < 500ms；**系统应**对所有写接口在无认证时返回 401，对参数错误返回 422，对重复创建返回 409。 |
| AC-15 | Event | **当**执行端到端验收（四平台各 1 位博主，作品 ≤3 分钟），**系统应**在单作品从检测到前端全绿可打开笔记耗时 <10 分钟。 |
| AC-16 | Ubiquitous | **系统应**不出现 emoji 功能图标、不出现紫色→粉色渐变、不出现 AI 模板味占位文案；前端颜色一律来自设计 Token。 |

---

## 10. WorkBuddy 对接契约（AI 笔记层，零 API）

WorkBuddy 无 API，触发 = **定时自动化 + 对话手动**，系统侧只负责"备料"与"落盘"：

1. **素材就绪清单**：流水线完成转写+关键帧后，写入 `workbuddy/pending/{work_id}-{日期}-{标题}.json`：
   ```json
   {
     "work_id": 12,
     "platform": "douyin",
     "blogger": "张三",
     "title": "...",
     "url": "...",
     "publish_date": "2026-08-22",
     "transcript_path": "media/财经/张三/2026-08-22-xxx/transcript/xxx.json",
     "frames_dir": "media/财经/张三/2026-08-22-xxx/frames",
     "lexicon_hits": [{"term": "A股", "action": "increase"}],
     "expected_output": "Obsidian/财经/张三/2026-08-22-xxx.md",
     "status": "pending"
   }
   ```
2. **WorkBuddy 定时自动化**：周期性扫描 `workbuddy/pending/*.json`（status=pending）→ 读转写稿 + 关键帧 → 生成笔记（AI 总结 + 双层标签）→ 写 Obsidian → 更新清单 status=done。
3. **对话手动**：用户对话中手动触发（前端 `POST /works/:id/analyze` → 生成/刷新清单）→ WorkBuddy 会话读取该清单执行。
4. **失败处理**：WorkBuddy 未执行/未配置 → 作品状态保持 NOTE_GENERATING/pending，前端提示"待 AI 生成"，不误报完成。
5. 系统不参与 AI 生成，不存 AI 摘要副本到 media/（**唯一副本在 Obsidian**）。

---

## 11. 边界与约束 + 已知坑（内嵌硬约束）

### 11.1 平台/风控类
| # | 坑 | 应对（硬约束） |
|---|----|----------------|
| K1 | 抖音 aweme 接口分页被风控卡 20 条 | CDP 会话 + browser_fallback（手动过人验）兜底；轮询间隔默认 ≥10min 可配置，带随机抖动 |
| K2 | 抖音静态 cookie 数小时失效 | 不用静态 cookie 做监控主路径；CDP 持活会话 + 自动续 cookie；健康度检测 |
| K3 | 403/461/471/验证码/空响应 | 分类为"风控/cookie/网络/路由失效"写 poll_logs；cookie 状态迁移 OK→WARN→NEEDS_RELOGIN；不静默 |
| K4 | RSSHub 公共实例不稳 | **自建 RSSHub 实例**；路由失效 → changedetection.io 兜底 → 仍失败明确报错 |
| K5 | changedetection.io 是通用网页变更检测 | 对抖音/各平台需配置正确 selector，防误报；**仅作兜底非主路径** |
| K6 | 平台改版导致监控失效 | 降级为明确报错而非静默；风险接受清单内（对标 CreatorHub PR#10/12 当天修） |

### 11.2 Cookie/凭据类
| # | 坑 | 应对 |
|---|----|------|
| K7 | cookie 落明文日志风险 | cookie/会话凭据**加密存储**（Fernet，密钥走 env），日志禁止打印 cookie 原文 |
| K8 | TikTokDownloader 扫码登录已失效 | 需手动粘贴 cookie；P2 适配器文档写明此步骤 |
| K9 | 点赞/收藏数据只返回发布日期、不返回操作日期 | P2 需全量拉取再日期筛选，增量效率低 → 用 `max_pages` 控制 + 已下 ID 对比；P2 设计要点 |

### 11.3 许可证类（合规硬约束）
| # | 坑 | 应对 |
|---|----|------|
| K10 | AGPL-3.0（RSSHub） | 自托管自用无碍；**若修改后对外提供网络服务需开源衍生代码** → 本项目自用 OK，禁止将修改版对外商用发布 |
| K11 | GPL-3.0（yutto / XHS-Downloader / TikTokDownloader） | **以外部 CLI/子进程方式调用，不改其代码**（进程隔离避免传染）；如确需修改 → 需按 GPL 开源，走 ADR 评审 |
| K12 | MIT（jiji262/douyin-downloader） | 可内嵌可改；优先 CLI 调用，改动走 ADR |
| K13 | 借鉴 UI 不抄代码 | CreatorHub 无 LICENSE，只借鉴交互不复制代码（前端组件全部自研） |

### 11.4 流水线/数据类
| # | 坑 | 应对 |
|---|----|------|
| K14 | 语义对齐抽帧依赖时间戳 | FunASR 需配置输出带时间戳转写；无时间戳 → 降级兜底并标注 |
| K15 | 转写空文本（无字幕无有效语音） | 跳过 AI 总结 + 前端提示，任务可重试 |
| K16 | 文件名非法字符/超长/Windows 保留名 | `sanitize_filename()` 统一清洗（§8.1） |
| K17 | 并发重复触发（跨来源命中同一作品） | works UNIQUE(platform, external_id) 幂等 upsert |
| K18 | FunASR 首次运行需下载模型 | 首次部署脚本预下载模型；离线可用 |
| K19 | 磁盘空间不足 | 下载失败明确报错（错误码 1001 类），任务可重试 |
| K20 | 词库命中冲突（同窗多词条、增删矛盾） | 取权重高者，冲突写日志；B4 细化机制 |
| K21 | 归类的原子性（media + Obsidian 双目录） | P2 classify 走事务：先移动文件再更新 DB，失败回滚并报错 |

### 11.5 性能与部署约束
- 轮询：RSSHub 平台 5-10min；抖音 CDP 检测间隔默认 ≥10min（可配置）；下载并发默认 1（防风控），可调。
- 聚合 API p95 < 500ms（读）；列表接口强制分页（page/limit 上限 100）。
- 部署：本机 Windows（脚本/Docker 一键启动）；未来 NAS 迁移（记录为待办，不做预案实现）。
- 浏览器兼容：Chrome 最新 2 版（CDP 会话依赖）。

---

## 12. 端到端验证步骤（规格收尾 = 可执行验收）

> 覆盖核心成功流 + 关键错误流。P1 验收执行此清单，全部通过 + AC-1..16 满足 + 回归率为零才算交付完成。

### 12.1 准备（一次性）
```bash
# 1. 依赖安装（版本以实际安装为准）
pip install -r aggregator/requirements.txt        # FastAPI/SQLAlchemy/Pydantic/APScheduler/feedparser/cryptography
npm install --prefix frontend                      # React/Vite/Tailwind/lucide-react/react-query
docker compose up -d rsshub changedetection        # 自建 RSSHub + changedetection.io 兜底
# 2. 配置 env（ADMIN_TOKEN / 路径 / 轮询间隔 / FunASR 模型路径）
cp .env.example .env
# 3. 首次部署：预下载 SenseVoice 模型 + 初始化 SQLite（alembic upgrade head 或等价脚本）
```

### 12.2 核心成功流（四平台各 1 位博主）
```bash
# 4. 启动聚合 API + 监控层 + 前端
uvicorn app.main:app --port 8000 &                # 聚合 API
python monitor/main.py &                           # 监控层（APScheduler）
npm run dev --prefix frontend &                    # 前端 localhost:5173

# 5. 添加博主（POST /api/v1/creators ×4，各平台 1 位，带 group_id）
# 6. 手动触发一次轮询
curl -X POST http://localhost:8000/api/v1/monitor/poll \
     -H "Authorization: Bearer $ADMIN_TOKEN"

# 7. 断言：新作品检测 → 任务入队 → 流水线执行
#    轮询 GET /api/v1/works?status=... 观察状态迁移
#    直至 status=DONE，记录耗时（验收 ≤10min）
curl -s http://localhost:8000/api/v1/works?limit=10 -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.data.items[].status'

# 8. 断言文件落盘
ls "media/财经/张三/2026-08-22-*/video"            # 最低画质视频
ls "media/财经/张三/2026-08-22-*/transcript"       # 带时间戳转写
ls "media/财经/张三/2026-08-22-*/frames/frame_manifest.json"  # 语义对齐 manifest
ls "Obsidian/财经/张三/2026-08-22-*.md"            # AI 摘要唯一副本（WorkBuddy 生成）

# 9. 前端走查：仪表盘全绿 → 打开笔记 → 分组浏览 → 标签检索（点"美联储"出结果）
```

### 12.3 关键错误流
```bash
# A. 失败重试：停掉下载器 → 触发流水线 → 任务 FAILED（带 last_error）→ 重启下载器 → POST /works/:id/retry → DONE
# B. Cookie 失效：手动将 cookies.status 置 NEEDS_RELOGIN → 前端横幅出现 → 按引导重登 → POST 后恢复 OK，任务不丢
# C. 去重：对同一作品重复 POST 触发 → 断言仅一条记录（409 或幂等）
# D. 空文本：喂无语音视频 → 转写空 → 跳过总结 + 前端提示 + 可重试
# E. 无时间戳：模拟无时间戳转写 → 兜底抽帧 + "非语义对齐"标注
# F. 鉴权：无 token 请求 → 401；参数错误 → 422；重复添加博主 → 409
```

### 12.4 验收报告
- 执行结果写入 `验收报告.md`：每项 AC 通过/失败、耗时记录、暴露问题沉淀为回归用例。

---

## 13. spike#1 验证计划（实现期第一优先）

> 目标：验证两个"实现依赖"是否成立，结论决定下载层与 P2 适配器的落地方式。**P1 动工前必须先完成 spike#1 并回填结论到本节**。spike#2（语义对齐抽帧算法）、spike#4（RSSHub 四平台路由实测）已登记为后续 spike，可在开发期并行执行。

### 13.1 目标一：jiji262/douyin-downloader 最低画质枚举

**前置已知（外部调研已验证）**：`config/default_config.py` 存在 `video_quality` 配置：
```
"video_quality": "highest"   # 可选值: highest / lowest / 1440p / 1080p / 720p / 540p / 480p / 360p
```
即"最低画质"已有原生枚举 `lowest`（省流量）与显式分辨率档位。spike 需在**实际安装版本**上确认其行为。

**验证步骤（在隔离临时目录执行，不污染主项目）**：
1. `git clone https://github.com/jiji262/douyin-downloader /tmp/spike-douyin && cd /tmp/spike-douyin`
2. `pip install -r requirements.txt`；`cp config.example.yml config.yml`
3. config.yml 设置：`video_quality: "lowest"`、`thread: 1`、`rate_limit: 2`、`increase.post: false`，写入测试用 cookie
4. 单条下载：`python run.py -c config.yml -u "https://www.douyin.com/video/{测试aweme_id}" -p /tmp/spike-out`
5. 断言清单：
   - [ ] 下载成功，输出为无水印视频文件
   - [ ] 实测分辨率 ≤ 目标档（用 ffprobe 查 width/height，记录实际档位）
   - [ ] 对照 `video_quality: "360p"` 显式档位行为一致（lowest 语义 = 阶梯最低可用档）
   - [ ] 边界：源视频无低档时的自动降级行为记录（不 crash、选最接近档）
   - [ ] 记录：`video_quality` 在**当前安装版本**中的实际枚举与默认值（diff 检查是否有变）
6. 通过标准：`lowest` 枚举存在且实测为最低可用档、下载成功。**若语义不符**（如 lowest 仍取最高），则聚合层在调用时显式传 `360p` 档位，并在 ADR-004 记录修正。

**回填**：验证通过后，下载层统一约定：**抖音下载一律 `video_quality=lowest`**（节省流量为产品刚需）。

### 13.2 目标二：TikTokDownloader 点赞/收藏能力（P2 前置）

**前置已知（外部调研已验证）**：JoeanAmier/TikTokDownloader（4.0，项目已更名 DouK-Downloader）支持"批量下载抖音账号发布/喜欢/收藏作品"、"记录已下载作品 ID"、"支持账号作品增量下载"、"Web API 模式（port 5555）"；**已知坑**：扫码登录已失效需手动粘贴 cookie；喜欢/收藏仅返回发布日期不返回操作日期，需全量拉取再日期筛选。

**验证步骤**：
1. `git clone -b 4.0 https://github.com/JoeanAmier/TikTokDownloader /tmp/spike-ttd && cd /tmp/spike-ttd`
2. `python -m venv venv && venv\Scripts\activate && pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`（或 `uv sync --no-dev`）
3. 手动写入用户 cookie（配置 `settings.json`）；以 **Web API 模式**启动（`http://127.0.0.1:5555/docs`）
4. 验证清单：
   - [ ] 能拉取当前登录账号的**喜欢/收藏**作品列表（返回作品元数据：作者/标题/发布时间/链接）
   - [ ] **增量识别**：与本地"已下 ID"对比，能识别"新增"条目（记录接口路径与参数）
   - [ ] 日期筛选可行性：记录全量拉取耗时与 `max_pages` 控制效果（K9 已知坑实测）
   - [ ] 作品下载（最低画质）可用性：确认该工具是否支持低画质（若仅最高画质，P2 适配器下载可复用 jiji262）
   - [ ] 记录 Web API 契约（路径/请求/响应字段）供 P2 适配器对接
5. 通过标准：能拉取喜欢/收藏列表 + 能增量识别新条目。**风险记录**：加密参数算法部分失效风险（调研已标注）→ 若失效，P2 适配器需评估替代（changedetection 兜底或放弃），在 OPEN-DECISIONS 登记，不阻塞 P1。

---

## 14. 依赖与影响面 / 待办登记

### 14.1 依赖
- 上游：RSSHub 自建实例、changedetection.io 服务（Docker 或本机）必须可用。
- 契约影响：前端类型由 `docs/openapi-aggregator.yaml` 生成；后端按同一文件实现；变更先改 yaml。
- 目录联动：`media/` 与 `Obsidian/` 目录结构由分组/博主命名驱动，分组改名/博主换组需迁移目录（P1 提供迁移脚本或明确"改名仅影响后续作品"的取舍，**默认后者**，避免重命名风暴）。

### 14.2 ADR 登记（本次 SPEC 新建，正文由执行者补齐）
- ADR-004：抖音下载选型 jiji262/douyin-downloader（MIT，`video_quality=lowest` 支持，spike#1 结论回填）
- ADR-005：点赞收藏适配器选型 TikTokDownloader（GPL-3.0，进程隔离调用）
- ADR-006：数据库选型 SQLite（单机个人工具，百万级足够）

### 14.3 悬而未决（OPEN-DECISIONS 登记）
- 词库机制细化（权重合并/阈值/冲突）→ B4 Backlog
- AI 笔记定时自动化频率 → 用户确认后配置
- 分组改名/换组的目录迁移策略 → 默认"仅影响后续作品"
- TikTokDownloader 加密参数有效性 → spike#1 回填

### 14.4 里程碑
| 阶段 | 产出 | 门禁 |
|------|------|------|
| Phase 3（本次） | SPEC_v1.md + openapi-aggregator.yaml + design-tokens + ADR | 用户确认规格 |
| spike#1 | 本节结论回填 | P1 动工前 |
| Phase 4 | 监控层 → 聚合 API → 前端 → 词库/抽帧 → 联调 | lint/type-check/test 3 轮内通过 |
| Phase 5 | 验收报告.md | AC-1..16 全过 + 端到端 <10min |

---

*规格即契约：本文档为可寻址交付物，任何实现冲突先改本文档再改代码。*
