# 作品元数据与本地归档实施计划

> **For agentic workers:** Execute the approved plan sequentially; use one scoped implementer and an independent reviewer for each task. Keep all feature edits limited to their task files.

**目标：** 在现有项目中统一下载作品的平台、原作品链接、发布时间、下载完成时间与本地文件信息；自动更新单作品和合集 CSV，增加可筛选、可核对、可导出的本地归档页，并回填指定历史母库。

**架构：** 在现有 SQLite、FastAPI 和 React/Vite 结构内增加受允许根约束的归档索引与持久扫描任务。FastAPI lifespan 启动带 DB lease 的归档 Worker，恢复扫描/同步任务；它独立于监控媒体流水线与下载队列。数据库保存可检索的统一记录；同一个序列化服务以原子写入方式生成目录旁单作品信息和合集 CSV。下载凭据、来源时间的精度及同步状态决定是否更新时间。历史扫描只索引既有目录，绝不新建媒体下载任务。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy、SQLite、React 18、TypeScript、Vite、标准库 CSV。

**规格：** [`docs/superpowers/specs/2026-09-30-local-archive-design.md`](../specs/2026-09-30-local-archive-design.md)

## 全局约束

- 目标仓库：`c2586081610-sys/social-monitor-workbench`；本地基线 `7b88ff5013dec30dec1543ffc9d26e6f4899065a`。
- 本机 `main` 工作区有大量未提交源码、配置、媒体和数据。开始实现前复查状态；工作在单独的 Git worktree/功能分支。仅将本计划列明的改动提交和推送。
- 归档筛选、API 和 CSV 使用项目当前支持的平台枚举（包含前端 `wechat` 值）；CSV、UI 与新目录的显示名映射集中定义。元数据刷新只使用真实可用的平台来源；无能力或无证据时保留未知。
- 数据库存 UTC ISO 8601；网页、CSV 与目录时间用北京时间。所有来源和时间精度均可追溯。
- 发布时间为空或发布时间不可查询时保持未知；文件系统时间、扫描时间与数据库编辑时间不冒充发布时间或下载时间。
- `downloaded_at` 仅因本次下载写入了非空、经验证的媒体而更新；复用媒体、失败、纯文本和后续转写不更改它。
- 未核实元数据及匹配冲突保留原值、来源和状态，不因解析失败覆盖可信信息。
- 历史媒体不移动、更名、删除或重下载；归类更新数据库、索引和清单并维持已存媒体路径稳定。Obsidian 笔记按现有规则处理，若移动必须同步修正 `note_path` 与链接。
- 根目录通过服务端根标识配置；请求仅使用根标识与相对目录；拒绝盘符、父级路径和解析后越出根目录的路径。
- 单作品与合集共用版本化记录。CSV 为带 UTF-8 BOM 的标准 CSV，保护 Excel 公式型单元格；用户导出覆盖全部筛选记录。
- 单作品可有多个媒体文件；清单和大小使用同一索引快照，文件路径限定在当前归档记录内。
- 不在 GitHub 放媒体、数据库、`.env`、Cookie、机器私有目录映射、真实历史作品 CSV、下载报告或本地扫描数据。不得修改第三方下载器源码。
- 下列任务按顺序执行；下一任务消费上一任务已通过审查的接口。

## 评审重点

1. **旧文件被误当成新下载：** 下载命令失败但目标目录已有 MP4；由 Task 3 的 `test_download_result_*` 验证成功/复用/失败和时间语义。
2. **源元数据冲突及精度：** 同名作品、多候选、平台 ID 不同、只到分钟的发布时间；由 Task 2/4 的元数据匹配测试验证不会错连、伪造或降级已有值。
3. **越界访问：** `..`、盘符绝对路径、目录联接指向其他盘；由 Task 4 的允许根路径测试验证拒绝。
4. **并发及中断重试：** 同博主同时两条成功下载、CSV 写一半崩溃、扫描服务重启；由 Task 2/4 的并发同步和任务断点测试验证无丢行、无重复及可继续。
5. **标题和时间边界：** Excel 公式字符、CSV 双引号/换行、跨日时区、中文非法文件名、长 Windows 路径、缺失发布时间；由 Task 2/5 的序列化测试验证输出可安全打开、可逆读取并正确标注未知。

## 文件地图

| 文件 | 职责 |
|---|---|
| `backend/app/models/archive_entry.py` | 已索引本地目录、作品身份、元数据快照及文件同步状态 |
| `backend/app/models/archive_job.py` | 可恢复历史扫描/补齐任务、游标及 worker lease |
| `backend/app/models/archive_revision.py` | 人工元数据修正的前后值、时间和来源审计记录 |
| `backend/app/repositories/archive_repo.py` | 归档和扫描任务数据库查询、幂等写入、筛选、分页 |
| `backend/app/services/archive_metadata_service.py` | 标准记录、时间/来源/精度和匹配状态归一化 |
| `backend/app/services/archive_sync_service.py` | CSV/JSON/Markdown 生成、原子替换、合集串行重建、重试 |
| `backend/app/utils/archive_paths.py` | 根标识解析、相对路径和 Windows 路径边界校验 |
| `backend/app/services/archive_scan_service.py` | 历史目录扫描、精确匹配、来源查询、断点及冲突统计 |
| `backend/app/services/archive_worker.py` | 独立领取、恢复并执行归档任务，不进入媒体下载队列 |
| `backend/app/services/archive_service.py` | 分页、导出、编辑、刷新和同步重试应用逻辑 |
| `backend/app/api/archive.py` | `/api/v1/archive` 页面、导出和持久任务 API |
| `backend/app/core/db.py` | SQLite 兼容迁移和建表 |
| `backend/app/core/config.py` | `media` 与允许的历史根映射 |
| `backend/app/models/__init__.py` | 注册归档实体 |
| `backend/app/models/work.py`, `schemas/work.py`, `services/work_service.py` | 下载时间、下载时间来源、核对时间/状态和关联归档信息 |
| `backend/app/services/link_analysis_service.py` | 新 Work 分配目录前尝试解析手动链接元数据 |
| `backend/app/main.py` | 挂载归档 API；启动时恢复未完成的归档任务 |
| `backend/app/services/classify_service.py` | 归类时不移动已有媒体并同步元数据 |
| `backend/app/schemas/archive.py`, `backend/app/repositories/archive_repo.py` | API 输入、筛选、任务进度与导出响应 |
| `monitor/pipeline/download.py` | 新下载、已登记文件复用和失败的可验证下载结果 |
| `monitor/pipeline/twitter_image.py`, `monitor/jobs.py` | 视频/图文/纯文本分流、下载时间 checkpoint、失败不影响已有下载记录 |
| `tools/bili_download_transcribe_29.py` | 项目自研批量入口复用同一归档/下载处理 |
| `backend/tests/test_archive_models.py` | 旧库迁移、新实体与幂等扫描契约 |
| `backend/tests/test_archive_sync.py`, `test_archive_paths.py` | CSV/JSON、原子替换、清单并发、路径安全 |
| `backend/tests/test_archive_scan_jobs.py` | 历史索引、匹配冲突、断点恢复和“无下载” |
| `backend/tests/test_archive_api.py` | API 认证、筛选、全量导出、任务和人工修正 |
| `backend/tests/test_archive_metadata.py`, `test_download_result.py` | 元数据来源与精度、新写入/复用/失败凭据与时间 checkpoint |
| `backend/tests/test_works.py` | 归类后原文件路径不变 |
| `frontend/src/services/archive.ts` | 归档请求、筛选参数、带 Bearer 的全量 CSV Blob 下载 |
| `frontend/src/services/http.ts` | 带 Bearer 的原始文件/Blob 请求，保留现有错误封套与 401 处理 |
| `frontend/src/utils/format.ts` | 显示时间显式使用 `Asia/Shanghai` 并呈现精度/未知值 |
| `frontend/src/pages/ArchivePage.tsx` | 本地归档筛选、进度、核对、CSV 导出 |
| `frontend/src/components/archive/*` | 筛选、归档行、单条核对编辑器 |
| `frontend/src/App.tsx`, `components/layout/Sidebar.tsx` | 页面路由和导航 |
| `frontend/src/types/api.d.ts` | 归档记录、任务进度和来源字段类型 |
| `frontend/src/components/work/WorkListItem.tsx`, `pages/WorkDetailPage.tsx` | 作品发布时间/下载时间/平台链接/核对状态 |
| `frontend/src/pages/SettingsPage.tsx` | 当前规则、允许根和北京时间说明 |
| `docs/openapi-aggregator.yaml` | 归档 REST API 契约 |
| `README.md`, `docs/本地归档说明.md` | 新下载约定、历史扫描操作、Git 数据边界 |
| `.gitignore` | 屏蔽本机媒体母库、凭据配置、数据库、历史作品清单和运行报告 |

实现中不重复创建接口若已存在；增补功能文件的职责保持表中边界。

---

### 任务 1：持久归档模型、迁移与 API 契约

**文件：** `archive_entry.py`、`archive_job.py`、`archive_revision.py`、`models/__init__.py`、`core/db.py`、`core/config.py`、`schemas/archive.py`、`schemas/work.py`、`models/work.py`、`repositories/archive_repo.py`、`work_repo.py`、`docs/openapi-aggregator.yaml`、TS 类型；新增 `backend/tests/test_archive_models.py`。

**接口：** `ArchiveEntry` 唯一物理目录键为 `(root_key, relative_directory)`，含可空 `work_id`、平台身份、完整元数据 JSON、同步状态；`ArchiveJob` 持久化类型、根键、相对目录、进度游标、统计、状态和错误。`Work` 新增 nullable `downloaded_at` 与 `download_time_source`。归档列表筛选共享固定字段：`platform, creator_id, group_id, work_id, root_key, q, check_status, time_field, date_from, date_to, include_unknown_time, page, limit`。`time_field` 仅为 `published_at` 或 `downloaded_at`；日期按北京时间日历解释，`date_to` 包含当天，服务端转换为 UTC 半开区间。导出使用相同筛选器且不应用页面限制。

- [ ] **步骤 1：** 在 `test_archive_models.py` 增加旧 `works` 表迁移前/迁移后、重复 `init_db()`、同一物理路径幂等 upsert（不重复建条目）及旧 Work 下载时间为 `None` 的测试；运行测试确认新增断言失败。
- [ ] **步骤 2：** 增加可空 Work 下载字段、ArchiveEntry、ArchiveJob 与 ArchiveRevision 模型，注册模型；人工修改的旧值和来源可审计。
- [ ] **步骤 3：** 按当前 `PRAGMA table_info` / `ALTER TABLE ADD COLUMN` 迁移约定为 `works` 幂等加列；配置只加载已声明根键并由服务器解析真实路径。
- [ ] **步骤 4：** 增加数据库仓库的 upsert、按筛选分页、无分页筛选导出以及可恢复任务进度方法。
- [ ] **步骤 5：** 为 API schema、TS 类型及 OpenAPI 契约定义统一归档/任务/下载时间字段与状态。
- [ ] **步骤 6：** 运行 `python -m pytest tests/test_archive_models.py -q`（工作目录 `backend`）；确认两次迁移均通过且已有字段值不变。

### 任务 2：统一元数据记录、路径校验及文件同步

**文件：** `services/archive_metadata_service.py`、`services/archive_sync_service.py`、`utils/archive_paths.py`、归档仓库；新增 `backend/tests/test_archive_sync.py`、`test_archive_paths.py` 与 `test_archive_metadata.py`。

**接口：** `build_archive_metadata(work, root_key, relative_directory, downloaded_files) -> dict`；`resolve_archive_path(root_key, relative_path) -> Path`；`sync_archive_entry(entry_id) -> ArchiveEntry` 原子输出三种单作品信息，并从数据库完整查询重建所属合集和总表；记录只在所有文件写成后标记 `ready`。

- [ ] **步骤 1：** 测试跨平台路径和保留名、长目录保留作品 ID、UTC 跨日北京时区、精度来源、未知值、CSV 双引号/换行和公式字符。
- [ ] **步骤 2：** 测试带 BOM CSV 在 Python `utf-8-sig` 回读后字段无损，多媒体作品聚合成一行且媒体大小准确。
- [ ] **步骤 3：** 测试目录联接、相对越界路径、绝对盘符路径、未知 root key 一律拒绝。
- [ ] **步骤 4：** 先实现统一元数据归一化、版本化 JSON schema、CSV/Markdown 渲染和旧列保留，再实现同目录临时文件 + 原子替换。
- [ ] **步骤 5：** 实现物理目录锁和基于完整 DB 快照的合集/总表重建；同步失败持久记错，重试只重写信息文件。
- [ ] **步骤 6：** 运行 `python -m pytest tests/test_archive_sync.py tests/test_archive_paths.py tests/test_archive_metadata.py -q`；制造中断后确认目标文件保持旧完整版本、重试成功并未产生作品副本。

### 任务 3：可靠下载凭据、元数据接入及稳定归档路径

**文件：** `monitor/pipeline/download.py`、`pipeline/twitter_image.py`、`monitor/jobs.py`、`backend/app/services/link_analysis_service.py`、`services/classify_service.py`、自研 `tools/bili_download_transcribe_29.py`；新增 `backend/tests/test_download_result.py`，扩展 `test_link_analysis_runner.py` 与分类测试。

**接口：** 下载适配器返回 `DownloadResult(disposition: Literal['downloaded','reused','not_required'], files: list[MediaFile], completed_at: str | None)`。适配器失败抛既有流水线错误，调用层不能从目录中旧文件推断成功。`reused` 只允许依据已登记且仍有效的文件清单；`not_required` 表示无需媒体下载的纯文本。项目入口调用 `archive_service.record_download_checkpoint(db, work, result)`，仅 `downloaded` 结果写入 UTC `downloaded_at`；同步意图先提交 DB。

- [ ] **步骤 1：** 测试下载成功、新增非空媒体、复用未改媒体、复用既有非空媒体、下载器非零退出但目录含旧文件、空文件、输出验证失败。
- [ ] **步骤 2：** 记录调用前已存在媒体及文件指纹；验证平台 CLI 退出码和返回文件存在/非空，以实际结果判定新写入或复用。既有 `download() -> str` 调用者继续得到兼容结果。
- [ ] **步骤 3：** 新增图文 receipt：至少一张本次新写入的有效图片才生成实际下载时间；无图纯文本不会报告已下载媒体。
- [ ] **步骤 4：** 在 `link_analysis_service`、监控入库和历史刷新共用的 resolver 接口中，在分配新目录前先复用平台现有元数据；为 B 站详情查询补充时间来源和分钟/秒精度，其他平台复用各自已有采集响应并明确记录离线/缺字段。查询错误不得伪造时间或覆盖旧值。
- [ ] **步骤 5：** 在分配新目录前解析实际标题、ID、发布时间；使用发布日+平台代码/显示名+清洗标题+稳定作品 ID；旧 Work 的已存 `media_path` 不重算。
- [ ] **步骤 6：** 视频/图文下载真实成功后先独立提交作品时间、已验证媒体清单与 `pending` 归档意图，再尝试信息同步并进入原有转写/笔记流程。sidecar 同步失败不撤销成功下载记录，也不重下媒体；转写失败仍保留已下载信息；只重试转写不得改变下载时间。
- [ ] **步骤 7：** 修改分类服务为更新数据库、归档索引和合集 CSV；新旧媒体/笔记目录均不移动。自研 B 站批处理调用相同下载凭据及归档服务。
- [ ] **步骤 8：** 运行下载、流水线与分类针对性测试；给 `downloaded`、`reused`、`failed` 各一条断言，检查再次运行不会改变真实成功时间或重复行。

### 任务 4：历史扫描、人工核对与恢复 API

**文件：** `services/archive_scan_service.py`、`services/archive_service.py`、`services/archive_worker.py`、`api/archive.py`、`backend/app/main.py`、`core/config.py`、OpenAPI 文档；新增 `backend/tests/test_archive_scan_jobs.py`、`test_archive_api.py` 与 Worker 恢复测试。

**接口：** 在静态路径之前注册动态 ID 路由。实现 `GET /archive`、`GET /archive/policy`、`GET /archive/export.csv`、`GET /archive/{id}`、`GET /archive/{id}/info.csv`、`GET /archive/{id}/files/{file_id}`、`POST /archive/scan`、`GET /archive/jobs/{job_id}`、`POST /archive/{id}/refresh`、`PATCH /archive/{id}/metadata`、`POST /archive/{id}/sync`。扫描 body 仅包含 `root_key` 与可选的相对 `relative_directory`；任务执行逐目录持久化进度，重启后续跑，不写媒体下载任务。`GET /archive?work_id=...` 返回作品关联的全部物理目录，供作品详情页展示；媒体访问仅按登记文件 ID 经过根路径校验并受 Bearer 保护。

- [ ] **步骤 1：** 使用仅含媒体副本的临时目录测试重复扫描无重复记录、稳定 ID 唯一关联、标题冲突进入人工核对、多作品目录报告冲突。
- [ ] **步骤 2：** 测试扫描任务中断后凭据标注保留、恢复后续跑且总数准确；断言无新增 `works` 下载 stage。
- [ ] **步骤 3：** 实现扫描入口、由 FastAPI lifespan 启动的独立 ArchiveJob Worker 与每目录提交游标；worker lease 防止多个 API 进程重复领取任务。Worker 与 `MONITOR_RUN_PIPELINE` 及媒体下载队列独立；扫描不创建 `Work` 或媒体下载 Task，服务重启后从最后完成目录续跑。
- [ ] **步骤 4：** 实现 bearer 保护的筛选/详情、无分页全量 CSV、单作品 CSV、规则读取、平台刷新、人工修正与同步重试路由。
- [ ] **步骤 5：** 不存在平台权威结果时保留空时间和失败/待核实状态；人工修正保留前值来源；平台地址格式和可解析 ID 必须与平台匹配。
- [ ] **步骤 6：** 测试无认证访问 401；验证下载导出筛选超过 200 条仍返回所有匹配作品；验证任务进度覆盖 ready、partial、failed、resume 状态。
- [ ] **步骤 7：** 运行 `python -m pytest tests/test_archive_scan_jobs.py tests/test_archive_api.py -q`；检查串行/并行同身份请求均不会越权或重复归档，FastAPI 启动后可以恢复 ArchiveJob，且不依赖 `MONITOR_RUN_PIPELINE`。

### 任务 5：网页归档、核对和全量导出

**文件：** `frontend/src/pages/ArchivePage.tsx`、`components/archive/*`、`services/archive.ts`、`services/http.ts`、`utils/format.ts`、`types/api.d.ts`、`App.tsx`、`components/layout/Sidebar.tsx`、作品详情/作品列表/设置页。

- [ ] **步骤 1：** 确认 Task 1/4 最终 OpenAPI 类型，然后定义列表、筛选器、任务进度及 metadata patch 类型和 `services/archive.ts`。
- [ ] **步骤 2：** 创建“本地归档”路由与导航；筛选全部现有平台枚举、博主、分组、标题、核对状态，明确选择发布时间或下载时间和北京时间日期范围，并可单独查看缺少所选时间的条目。
- [ ] **步骤 3：** 列表按后端分页加载；CSV 导出将相同筛选条件交给全量导出接口，使用带 Bearer 的二进制请求安全下载，绝不只导出页面数据。
- [ ] **步骤 4：** 显示每行来源/精度、未知时间、原平台链接、本地相对目录、媒体文件和核对状态；媒体经 Bearer 文件 API 安全访问；接入单条修正、元数据刷新、同步重试与扫描进度。
- [ ] **步骤 5：** WorkList/WorkDetail 增加下载完成时间、原链接及核对状态；WorkDetail 通过 `work_id` 列出全部关联归档目录；Settings 展示生效的时区和 allowlist 根标识/友好名，不展示机器绝对路径。
- [ ] **步骤 6：** 时间格式化固定到 `Asia/Shanghai`，对日期过滤使用北京时间日界；原始 CSV helper 复用 Bearer、401/错误封套处理，不能把 JSON 错误下载为 CSV。执行 `npm run build`（工作目录 `frontend`）；访问 `/archive`，用超过 200 项的 API 数据确认导出使用全量服务端响应并保留中文标题/逗号。

### 任务 6：指定历史母库回填与文件一致性验收

**本机目标（仅本地运行，仓库相对路径）：** `健身/谭成义-b站/「用户521903482」的全部投稿视频` 与 `健身/谭成义-b站/合集_2026-04-25_16-14_哔哩哔哩`。

- [ ] **步骤 1：** 备份将改的 CSV/JSON/Markdown 与使用 SQLite 在线备份 API 备份活动库；确认文件/媒体基线清单及哈希。
- [ ] **步骤 2：** 在归档页面/受保护任务 API 创建只扫描指定子目录的报告任务；人工报告新识别、可靠匹配、冲突/候选、查询失败与时间缺失总数。
- [ ] **步骤 3：** 先补具有平台证据的发布时间/作品 ID/平台链接；现有 114 条缺 ID/发布时间的候选以精确平台身份校验。限速和断点恢复已通过小样本验收后再跑全目录。
- [ ] **步骤 4：** 写入单作品标准清单并保留原有 CSV 每媒体文件行和用户附加列；按作品聚合新标准合集。原有 1 条视频的人工合集保留精确成员，不扩充至完整投稿总表。
- [ ] **步骤 5：** 核对目录数量、媒体 SHA-256/大小、CSV 可回读、作品唯一性和网页筛选数；确认无媒体被移位、删改或重下载。不能核实的时间保持未知，报告明细和剩余数量。
- [ ] **步骤 6：** 回归检查旧作品详情、归类、重试、转写、导出；不对生产 `aggregator.db` 或原素材运行测试。

### 任务 7：长期项目约定、选择性提交与 GitHub 推送

**文件：** `README.md`、新增 `docs/本地归档说明.md`、`docs/openapi-aggregator.yaml`、`.gitignore` 与本功能代码/测试；从列表删除任何媒体或报告路径。

- [ ] **步骤 1：** 写明“未来下载自动生成哪些文件、缺失时间如何表示、怎样刷新/重试归档、如何扫描历史、媒体目录稳定”和仓库内的通用目录规则及 Git 数据边界；不在公共文档写入机器私有绝对路径。
- [ ] **步骤 2：** 为 `/健身/`、本机 `config/`、历史清单/扫描报告、运行日志和数据库增加精确忽略规则；确认不会隐藏 source、reference docs、单元测试。
- [ ] **步骤 3：** 汇总 `git status`、`git diff --cached` 与全部候选新增路径；精确暂存和提交本功能，任何用户原有工作不合并或删改。
- [ ] **步骤 4：** 检查 `origin` 所有者和仓库，获取远端目标分支并正常同步；若已有远端新提交，先 rebase/merge 功能提交后再推送，不 force push。
- [ ] **步骤 5：** 推送到用户已明确指定的 GitHub 仓库；取得并验证远端 commit URL，不把 C 盘临时报告、GPT 对话、媒体/作品 CSV、数据库或秘密推送。
- [ ] **步骤 6：** 重建前端产物、受控重启本机后端和前端，检查健康状态、归档路由、筛选、CSV 下载和 API 认证。关闭本次任务结束后不再需要的临时端口服务。

## 顺序核对与风险覆盖

| 生产者任务 | 消费者任务 | 检查点 |
|---|---|---|
| Task 1：根键、Job/Entry schema、列表筛选、下载时间 DTO | Tasks 2–5：同步、扫描、UI | 字段只有一份定义；DTO/OAS/TS 等价；nullable 下载时间向前兼容 |
| Task 2：统一记录、原子 sidecar、锁、路径 resolver | Tasks 3/4：下载与历史扫描 | 两入口均调用同一同步接口；`root_key + relative_path` 不接受原始盘符 |
| Task 3：下载凭据及 download checkpoint | Tasks 4/5/6：扫描复用规则、API/列表字段、历史核对 | 成功→persist pending→sidecar sync attempt→transcribe 顺序一致；sync 失败不撤销下载；`reused` 不更新字段 |
| Task 4：分页/导出/任务/核对及受保护媒体 endpoints | Task 5：页面和 Blob 导出 | 列表/导出过滤一份实现；媒体链接限登记文件；动态路由不遮挡静态路由 |
| Task 5：归档状态和分类更新 | Task 6：历史页面/工作流核对 | 分类不移动路径；已有媒体摘要仍有效 |
| Task 6：历史 CSV/API 本地验收 | Task 7：可提交范围 | 历史报告和用户 CSV 不进入 Git index |

| 任务 | 文件引用内部一致性 | 结果 |
|---|---|---|
| Task 1 | 定义后端实体/API schema、迁移、TS/OpenAPI | 任务 2–5 使用这些字段，迁移不要求原库非空新列 |
| Task 2 | 输入归档身份→输出 sidecars 与同步状态 | Task 3/4 共享同一入口和同一根校验 |
| Task 3 | 新下载/媒体复用/平台数据→Work 时间与 pending 意图 | 只有本次下载 receipt 生成时间；task 4/5 展示同字段 |
| Task 4 | API 与可恢复扫描运行器 | Task 5 使用给定 query/status；Task 6 通过 root/subdir 接口 |
| Task 5 | 后端契约→页面与全量 Blob 下载 | API key/分页/导出路径与 Task 1/4 一致 |
| Task 6 | 指定目录只做 index/upsert/info CSV | 与用户保留路径一致；无来源时输出待核实/未知 |
| Task 7 | 路径忽略与提交 allowlist | 只提交本功能并正常快进推送 |

## 交接与执行

本计划对应用户已指定的当前对话内 Agent 协作，模型为 GPT‑6 Luna、max 思考等级；两份前后端只读梳理已纳入计划，原始报告留在临时工作区，不进入仓库。用户已明确授权推送到现有 GitHub 仓库；发布时不得重复询问推送许可。

按 `superpowers:writing-plans` 要求，交给用户审阅本计划。用户已说“继续”及重开两个 Agent，因此实施方式定为本对话内 subagent-driven 执行；由于数据与接口先后依赖，实施工作逐项串行推进，由不同 Agent 实施和审查。取得计划认可后运行：

1. 在项目仓库读取 Git worktree 状态；若无原生隔离功能，根据 `superpowers:using-git-worktrees` 为 `main` 另建忽略的功能 worktree，并检查干净基线。
2. 用 `superpowers:subagent-driven-development` 执行本计划，每任务先派实现 Agent，再用独立 reviewer 核对规格符合度和代码质量。
3. 只读基线含其他用户改动，保留另存取证；测试只用临时 DB 和文件目录；Task 6 实际母库更新前做可恢复备份。
4. 所有任务和最终代码审查通过后，按 Task 7 发布到已确认远端；只在远端为同一仓库且 push 不需要覆盖时推送，禁止强推。
