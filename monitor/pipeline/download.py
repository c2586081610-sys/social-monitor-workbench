"""流水线·下载：按平台路由 CLI 下载器（最低可用画质，许可证进程隔离 K11/K12）。

平台路由（SPEC ADR-004 + 本项目下载层设计）：
  douyin   -> jiji262/douyin-downloader（主路径，video_quality=480p，见 _ensure_jiji_config）
  bilibili -> yutto（多清晰度，360p 最低）
  xhs      -> XHS-Downloader（GPL 子进程）
  twitter  -> yt-dlp（-f worst 最低画质）
  任意平台 -> MediaCrawler 适配器（预留接口：全平台采集/下载兜底，含热评+子评论）

实现注意（Windows）：
  - 统一用 [sys.executable, "-m", <module>] 调 yutto/yt_dlp，XHS 用 [sys.executable, main.py]
    —— subprocess 直接调 .cmd 包装会 WinError 2（CreateProcess 不解析 .cmd/.bat）。
  - 平台 cookie 从 config/platform_cookies.json 读取（推特=Netscape cookies.txt 路径，小红书=cookie 串），
    未配置时推特/小红书下载抛 PipelineOfflineError 提示补 cookie。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("monitor.pipeline.download")

# 平台 cookie 配置文件（config/platform_cookies.json），下载器按需读取
_COOKIE_CONFIG = os.getenv("PLATFORM_COOKIES_FILE", "")


def _load_platform_cookies() -> dict:
    """读取 config/platform_cookies.json；缺失/损坏返回 {}（不阻断 B站等免登录平台）。"""
    path = Path(_COOKIE_CONFIG) if _COOKIE_CONFIG else Path(__file__).resolve().parents[3] / "config" / "platform_cookies.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning("platform_cookies.json 解析失败: %s", path)
        return {}


class PipelineOfflineError(Exception):
    """流水线引擎不可用（错误码 1001，SPEC §4.1）。"""


def _find_video(media_dir: Path) -> str:
    """在下载目录中查找视频文件（mp4/mov/mkv/flv/webm）。"""
    for f in media_dir.iterdir():
        if f.suffix.lower() in (".mp4", ".mov", ".mkv", ".flv", ".webm"):
            return str(f)
    raise PipelineOfflineError("下载完成但未找到视频文件")


# 抖音 jiji262 画质档位。实测：lowest 档无音轨（仅 HEVC 视频流）→ 转写失败；
# 480p 含 AAC 128kbps 音轨，为最低可用档（端到端实测结论，替代 lowest）。
_JIJI_VIDEO_QUALITY = "480p"
_JIJI_QUALITY_NOTE = (
    "# 注意：lowest 档无音轨（实测仅 HEVC 视频流），480p 为最低可用档（含 AAC 音轨）\n"
)


def _ensure_jiji_config(cfg: Path) -> None:
    """生成/更新 jiji262 config.yml，保证 video_quality=480p。

    实测结论：lowest 无音轨 → 下游转写必然失败；480p 含 AAC 128kbps 音轨，
    是满足"省流量 + 可转写"的最低可用档。已存在的 lowest 配置就地升级为 480p。
    """
    if not cfg.exists():
        cfg.write_text(
            _JIJI_QUALITY_NOTE
            + f"video_quality: {_JIJI_VIDEO_QUALITY}\n"
            + "thread: 3\n"
            + "retry_times: 3\n"
            + "progress:\n"
            + "  quiet_logs: true\n",
            encoding="utf-8",
        )
        logger.info("生成 jiji262 配置: %s (video_quality=%s)", cfg, _JIJI_VIDEO_QUALITY)
        return
    text = cfg.read_text(encoding="utf-8")
    if re.search(r"^video_quality:\s*lowest\s*$", text, re.M):
        text = re.sub(r"^video_quality:\s*lowest\s*$", f"video_quality: {_JIJI_VIDEO_QUALITY}", text, flags=re.M)
        cfg.write_text(text, encoding="utf-8")
        logger.info("jiji262 配置升级 lowest -> %s: %s", _JIJI_VIDEO_QUALITY, cfg)
    elif "video_quality:" not in text:
        # 已有配置缺质量项：在头部显式补 480p（含注释，避免后续误改回 lowest）
        cfg.write_text(_JIJI_QUALITY_NOTE + f"video_quality: {_JIJI_VIDEO_QUALITY}\n" + text, encoding="utf-8")
        logger.info("jiji262 配置补充 video_quality=%s: %s", _JIJI_VIDEO_QUALITY, cfg)
    else:
        logger.info("jiji262 配置已含 video_quality，跳过更新: %s", cfg)


# ---------------------------------------------------------------
# MediaCrawler 全平台适配器（预留接口）
# ---------------------------------------------------------------
# MediaCrawler（github.com/NanmiCoder/MediaCrawler，63k★）支持 7 平台
# （小红书/抖音/快手/B站/微博/贴吧/知乎）的帖子与评论（含二级评论）抓取。
# 它既可做"全平台采集兜底"，也可做"评论区采集"（热评+子评论）。
#
# ⚠️ 许可约束：MediaCrawler 为自定义非商业许可（禁商用、禁大规模爬取），
#    个人知识库自用 OK；接入时仅作 CLI 子进程调用（进程隔离），不内嵌代码。
#
# 接入方式（启用后）：
#   MEDIACRAWLER_DIR 指向 MediaCrawler 仓库根目录
#   命令：uv run main.py --platform {p} --lt qrcode --type detail
#   输出：CSV/JSON/JSONL 数据文件（需后处理提取视频直链再下载）
MEDIACRAWLER_PLATFORMS = {"xhs", "douyin", "bilibili", "weibo", "tieba", "zhihu", "kuaishou"}


def download_via_mediacrawler(platform: str, target: str, out_dir: Path) -> str:
    """MediaCrawler 适配器：采集指定帖子/主页并提取视频。

    Args:
        platform: xhs/douyin/bilibili/weibo/tieba/zhihu/kuaishou
        target: 帖子 ID 或主页链接
        out_dir: 输出目录
    Returns:
        视频文件路径（若 MediaCrawler 输出为数据文件，返回其路径供后处理）
    """
    mc_dir = __import__("os").getenv("MEDIACRAWLER_DIR", "")
    if not mc_dir:
        raise PipelineOfflineError("MediaCrawler 未配置（MEDIACRAWLER_DIR）")
    mc_dir = Path(mc_dir)
    if not (mc_dir / "main.py").exists():
        raise PipelineOfflineError(f"MediaCrawler 目录无效: {mc_dir}")
    # 注意：MediaCrawler 默认从 config/base_config.py 读目标，
    # CLI 支持 --platform/--type；此处为预留契约，实际参数按版本校准
    cmd = ["uv", "run", "main.py", "--platform", platform, "--lt", "qrcode", "--type", "detail"]
    logger.info("MediaCrawler: %s", " ".join(cmd))
    subprocess.run(cmd, cwd=str(mc_dir), check=False)
    # 输出为数据文件（CSV/JSONL），返回目录供下游处理
    return str(out_dir)


def download(platform: str, url: str, media_dir: Path) -> str:
    """下载最低可用画质视频，返回视频文件绝对路径。引擎缺失抛 PipelineOfflineError。"""
    media_dir.mkdir(parents=True, exist_ok=True)
    if platform == "douyin":
        # jiji262/douyin-downloader：python run.py -c config.yml -u <url> -p <out>
        jiji_dir = __import__("os").getenv("DOUYIN_DOWNLOADER_DIR", "")
        if not jiji_dir:
            raise PipelineOfflineError("抖音下载器 jiji262 未配置（DOUYIN_DOWNLOADER_DIR）")
        cfg = Path(jiji_dir) / "config.yml"
        _ensure_jiji_config(cfg)
        subprocess.run(
            [
                "C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe",
                "run.py",
                "-c",
                str(cfg),
                "-u",
                url,
                "-p",
                str(media_dir),
            ],
            cwd=jiji_dir,
            check=False,
        )
    elif platform == "bilibili":
        # yutto：python -m yutto download <url> -d <dir> -q 16（360P 最低画质省流量；B站全清晰度均含音轨）
        try:
            import yutto  # noqa: F401
        except ImportError as exc:
            raise PipelineOfflineError("yutto 未安装（pip install yutto）") from exc
        subprocess.run(
            [sys.executable, "-m", "yutto", "download", url, "-d", str(media_dir), "-q", "16"],
            check=False,
        )
    elif platform == "xhs":
        # XHS-Downloader：python main.py --url <url> --work_path <dir> --folder_mode False --cookie <ck>
        # folder_mode=False 保证视频直落 work_path 根目录（_find_video 非递归查找）
        xhs_dir = Path(__file__).resolve().parents[3] / "tools" / "xhs-downloader"
        if not (xhs_dir / "main.py").exists():
            raise PipelineOfflineError("XHS-Downloader 未配置（tools/xhs-downloader）")
        cookies = _load_platform_cookies().get("xhs", {})
        cookie_str = cookies.get("cookie", "")
        if not cookie_str:
            raise PipelineOfflineError("小红书下载需网页版 cookie（config/platform_cookies.json -> xhs.cookie）")
        subprocess.run(
            [
                sys.executable,
                str(xhs_dir / "main.py"),
                "--url",
                url,
                "--work_path",
                str(media_dir),
                "--folder_mode",
                "False",
                "--cookie",
                cookie_str,
            ],
            cwd=str(xhs_dir),
            check=False,
        )
    elif platform == "twitter":
        # yt-dlp：python -m yt_dlp -f worst <url> --cookies <file> --proxy <proxy> -o <dir>/%(title)s.%(ext)s
        # v0.4：国内访问 x.com 必须注入代理（TWITTER_PROXY 可覆盖默认 127.0.0.1:7892）
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise PipelineOfflineError("yt-dlp 未安装（pip install yt-dlp）") from exc
        cookies = _load_platform_cookies().get("twitter", {})
        cookies_file = cookies.get("cookies_file", "")
        proxy = os.getenv("TWITTER_PROXY", "http://127.0.0.1:7892")
        cmd = [sys.executable, "-m", "yt_dlp", "-f", "worst", url]
        if cookies_file:
            cmd += ["--cookies", str(cookies_file)]
        else:
            logger.warning("推特未配置 cookies_file，匿名下载大概率失败")
        cmd += ["--proxy", proxy, "-o", str(media_dir / "%(title)s.%(ext)s")]
        subprocess.run(cmd, check=False)
    else:
        # 兜底：尝试 MediaCrawler 适配器（全平台预留）
        if platform in MEDIACRAWLER_PLATFORMS:
            return download_via_mediacrawler(platform, url, media_dir)
        raise PipelineOfflineError(f"平台 {platform} 无下载器")

    return _find_video(media_dir)
