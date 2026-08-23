# MVP 架构定稿 v1 — 博主监控 + 视频三件套 + AI 笔记工作台

> **状态**：已定稿（产品经理 许清楚 + 首席架构师 高见远 共识，项目总监确认）
> **日期**：2026-08-22
> **前置**：基于《GitHub同类软件调研报告》Phase 1 调研 + 抖音专项深挖

---

## 一、产品定位

一句话：**自动监测抖音博主新作品 → 最低画质下载 → FunASR 转写 → AI 笔记 → 可视化三件套进度看板**的个人工作台。

首批试点平台：**抖音**（用户选定，链路最难但最刚需）。B站/小红书/推特走 RSSHub 稳定路由进 Backlog。

---

## 二、MVP 架构（方案 A' 定稿）

```
[监控层 · 自研 Python 模块 ≈1人·周]
  抖音适配器: 浏览器/CDP 持活会话(Patchright/Playwright) + 轮询博主主页 aweme 接口
    ├ 会话管理: 扫码登录持久化 profile 自动续 cookie; 健康度检测
    ├ 轮询调度: 5-30min 可配 + 随机抖动; 手动触发立即轮询
    ├ 去重: aweme_id 唯一约束(SQLite); 增量只产新作品
    └ 触发: 新 aweme_id → POST VideoMemo /api/generate_note → 记 task_id
  数据存储(SQLite): 博主表 / 作品表(aweme_id,url,task_id,状态机) / cookie 健康度
  聚合 API(FastAPI 薄层):
    GET /api/creators            博主列表+最近作品+健康度
    GET /api/creators/:id/works  作品列表+三件套状态(合并 VideoMemo task_status)
    GET /api/health/cookie       cookie 状态(OK/WARN/NEEDS_RELOGIN)+最近轮询时间
    POST /api/works/:id/retry    单条重试

[三件套 · VideoMemo(Apache-2.0, Docker, 可内嵌可改)]
   下载(quality 枚举最低画质待 spike 验证) → FunASR(SenseVoiceSmall) → LLM 笔记(SiliconFlow/DeepSeek)
   GET /api/task_status/{task_id} 五步进度(解析→下载→转写→总结→完成)

[薄聚合前端 · 自研 React, MVP 一等公民]
   博主列表 → 作品卡片(下载/转写/笔记 三状态灯+进度) → 笔记跳转(VideoMemo 笔记 URL)
   cookie 失效横幅 + 引导重新登录(调 /api/health/cookie)
```

**决策记录**：
- 不用 CreatorHub：无 LICENSE（商用风险）+ 监控漏最新作品 open bug #17 + 下载依赖已失效的 yt-dlp 抖音提取器 → 仅借鉴思路
- 用 VideoMemo：Apache-2.0 许可干净、Docker 部署、FunASR 内建、五步进度 API 现成
- 监控层自研仅 1 模块：拥有自己的去重/触发逻辑，绕开 CreatorHub 风险，避免双份下载流量
- 自研薄聚合前端（不用 VideoMemo 原生 UI）：原生仅"任务"维度，用户需要"博主→作品→三件套状态"维度

---

## 三、作品状态机（聚合层统一，映射 VideoMemo 五步）

```
NEW → QUEUED(拿到task_id) → DOWNLOADING → TRANSCRIBING → NOTE_GENERATING → DONE
                          ↘ FAILED(可重试) / COOKIE_EXPIRED(需重登, 用户可见, 不静默)
```

---

## 四、MVP 范围（锁定）

1. 博主管理：添加/删除抖音博主（主页链接或 sec_uid）
2. 定时轮询：默认 5-10 分钟，增量检测新 aweme_id
3. 自动触发：新作品 → POST VideoMemo generate_note（最低画质 → FunASR 转写 → AI 笔记）
4. 聚合前端：博主 → 新作品 → 每作品三件套状态(下载/转写/笔记) + 笔记跳转（一等公民）
5. Cookie 健康度：失效时明确报错+引导重登，不静默失败

**明确不做（Out-of-Scope）**：B站/小红书/推特监控（Backlog）、多账号、评论抓取、直播监控、视频号/快手。

---

## 五、验收口径

> 单博主 → 新作品 → 自动下载(最低画质) → FunASR 转写 → AI 笔记 → 前端进度全绿 + 可打开笔记，**端到端 < 10 分钟**。
> 建议验收作品 ≤3min 短视频（若 10min 长视频转写约 5min 仍达标但贴边）。
> 多博主 = 循环，不进验收难点。

---

## 六、风险接受清单

| # | 风险 | 等级 | 应对 |
|---|------|------|------|
| 1 | 抖音 web 接口/风控变化 → 监控失效 | 🔴 高 | cookie 维护 + 定期回归（类比 CreatorHub PR#10/12 当天修） |
| 2 | Cookie 过期 → 需重新扫码 | 🟡 中 | 健康度检测 + 横幅引导，已入 MVP 验收 |
| 3 | VideoMemo quality 枚举最低画质未确认 | 🟢 低 | 实现期 spike#1 验证，必要时小改其后端（Apache-2.0 可改） |
| 4 | B站/小红书/推特无抖音式稳定监控 | 📋 Backlog | RSSHub 稳定路由进 Backlog |

---

## 七、开发量粗估

| 模块 | 工作量 |
|------|--------|
| 监控层（会话+轮询+去重+健康度） | ~1 人·周 |
| 聚合 API + SQLite | ~0.5 人·周 |
| 薄聚合前端 | ~1 人·周 |
| 对接/联调/spike 验证 | ~0.5 人·周 |
| **合计** | **~3 人·周**（单人 3 周，AI 加持可压缩） |

---

## 八、下一步

- [ ] 用户确认 MVP 定稿 → PM 产出完整 PRD（功能 RICE 排序 + 验收标准 + 埋点）
- [ ] Spec 锁定：技术栈版本、API 契约(openapi)、页面清单、设计 Token
- [ ] spike#1：验证 VideoMemo generate_note 的 quality 枚举是否含最低画质档
- [ ] 开发：监控层 → 聚合 API → 薄前端 → 联调
