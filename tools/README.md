# tools/ 工具链说明

博主监控工作台下载引擎与辅助工具就绪清单。所有工具位于本目录，供监控层流水线
（`monitor/pipeline/download.py`）以**子进程方式**调用（许可证进程隔离）。

| 工具 | 平台 | 用途 | 位置 | 状态 |
|------|------|------|------|------|
| yutto 2.3.0 | B站 | 视频下载（多清晰度，流水线用 360p） | Python Scripts + `bin/yutto.cmd` 包装 | 就绪 |
| ffmpeg 7.1 | 全平台 | 抽帧/转码 | `bin/ffmpeg.exe` | 就绪 |
| jiji262/douyin-downloader | 抖音 | 视频/图集下载（最低画质） | `douyin-downloader/` | 就绪 |
| XHS-Downloader | 小红书 | 图文/视频下载（GPL-3.0） | `xhs-downloader/` | 就绪（源码） |
| MediaCrawler | 全平台 | 采集兜底（预留，非商业许可） | 未落地 | 预留 |

---

## 1. yutto（B站下载器）

- **安装方式**：managed Python 3.13.12 安装
  ```bash
  C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe -m pip install --no-cache-dir yutto
  ```
- **安装位置**：`C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\Scripts\yutto.exe`
  （pip 默认 Scripts 目录不在 PATH，故提供包装脚本 `tools/bin/yutto.cmd`）
- **验证**：`python -m yutto --version` → `yutto 2.3.0`
- **流水线调用**：`yutto <url> -d <media_dir> -q 360p`（`shutil.which("yutto")` 经
  `tools/bin` 加入 PATH 后解析到 `yutto.cmd`）
- **注意事项**：
  - B站下载可能触发风控，需在 yutto 交互登录或用 `-c` 指定 cookie 文件；
    正式使用请参考官方文档（yutto-dev/yutto，以 GitHub 为准）。
  - yutto 默认输出目录带多级结构，`_find_video` 只扫描一级目录，若未命中请手动指定 `-d` 的扁平目录。

---

## 2. ffmpeg（系统级，抽帧用）

- **来源**：`imageio_ffmpeg` 包自带二进制（ffmpeg 7.1 essentials build）
  ```
  C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe
  ```
- **落地**：已复制为 `tools/bin/ffmpeg.exe`，并附 `ffmpeg.cmd` 兜底包装
- **验证**：`tools/bin/ffmpeg.exe -version`
- **PATH 说明（两种方式任选）**：
  1. 一键脚本：`start_all.bat` 已自动将 `tools\bin` 加入进程 PATH（推荐，仅对启动的进程生效）
  2. 全局 PATH：控制面板 → 系统属性 → 环境变量 → Path 增加 `C:\Users\Administrator\WorkBuddy\2026-08-22-18-25-30\tools\bin`，
     重开终端后 `ffmpeg -version` 可直接执行
- **流水线调用**：`monitor/pipeline/frames.py` 直接 `subprocess.run(["ffmpeg", ...])`，
  依赖 ffmpeg 在 PATH 中（`tools\bin` 已满足）。

---

## 3. douyin-downloader（jiji262，抖音）

- **位置**：`tools/douyin-downloader/`（已就绪）
- **启动方式**（供流水线调用，cwd 必须在仓库根目录）：
  ```bash
  cd tools/douyin-downloader
  C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe run.py -c config.yml -u <url> -p <输出目录>
  ```
- **配置**：最小配置（流水线自动生成 `config.yml`）：
  ```yaml
  video_quality: lowest
  thread: 3
  retry_times: 3
  progress:
    quiet_logs: true
  ```
- **环境变量**：`DOUYIN_DOWNLOADER_DIR` 指向本目录（download.py 据此定位）
- **注意事项**：
  - 抖音风控严格，建议使用 Playwright 持久化 profile（见 §5）人工过验证码后复用登录态；
  - 依赖安装：`python -m pip install -r requirements.txt`（如未装）。

---

## 4. XHS-Downloader（小红书，GPL-3.0）

- **仓库**：JoeanAmier/XHS-Downloader（GPL-3.0，进程隔离调用不内嵌代码），默认分支 `master`
- **落地状态**：`tools/xhs-downloader/`（源码已就绪，依赖已按 `requirements.txt` 安装）
- **启动方式**（版本以官方 GitHub README 为准，默认分支 master）：
  ```bash
  cd tools/xhs-downloader
  # TUI 交互模式（默认）
  C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe main.py
  # API 模式（端口 5556，适合二次开发/流水线）
  C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe main.py api
  # 命令行模式（直接下载）
  C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe -m source.CLI.main -u "小红书链接"
  ```
- **注意事项**：
  - 小红书强风控，**Cookie 非强制**但推荐配置：不设置 Cookie 时视频只能下载低分辨率；
    手动获取 Cookie 写入 `Volume/settings.json`（配置方法见官方 README）；
  - 本项目流水线仅以 `xhs <url> -d <media_dir>` 契约调用（download.py 预留），
    接入前需按官方 README 校准参数与登录方式；
  - 未完整跑通前不阻塞主流程：监控层对 xhs 平台先走 RSSHub 采集（platforms/rsshub.py）；
  - 需要 Python >= 3.12（当前 3.13.12 满足）。

---

## 5. Cookie 方案（抖音/小红书共用）

- **目录**：`tools/dy_profile/` — Playwright 持久化浏览器 profile
  （Chrome 用户数据目录，含登录态 cookie）
- **用途**：抖音 CDP 轮询（`ENABLE_DOUYIN_CDP=true` 时）与下载器复用登录态，
  减少人工过验证码次数
- **配套脚本**：`tools/extract_douyin_cookie.py` — 提取抖音 cookie 到
  `config/cookies.json`（供需要 cookie 的下载器使用）
- **刷新时机**：登录态过期或风控后重新登录，建议每 1~2 周人工刷新一次。

---

## 6. 一键启停

| 脚本 | 作用 |
|------|------|
| `start_all.bat`（工作区根） | 依次启动 后端(:8000) + 前端(:5173) + 监控层(monitor/main.py)，自动把 `tools\bin` 与 Python Scripts 加入 PATH |
| `stop_all.bat`（工作区根） | 按 窗口标题 → 监听端口 → 命令行 三层兜底停止全部服务 |

- 前端若 `dist` 未构建，先执行：`cd frontend && npm run build`
- 重复启动前务必先 `stop_all.bat`，避免 8000/5173 端口冲突。
