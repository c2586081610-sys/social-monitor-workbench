"""流水线·下载：按平台路由 CLI 下载器（最低画质，许可证进程隔离 K11/K12）。

平台路由（SPEC ADR-004 + 本项目下载层设计）：
  douyin   -> jiji262/douyin-downloader（主路径，video_quality=lowest）
  bilibili -> yutto（多清晰度，360p 最低）
  xhs      -> XHS-Downloader（GPL 子进程）
  twitter  -> yt-dlp（-f worst 最低画质）
  任意平台 -> MediaCrawler 适配器（预留接口：全平台采集/下载兜底，含热评+子评论）
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("monitor.pipeline.download")


class PipelineOfflineError(Exception):
    """流水线引擎不可用（错误码 1001，SPEC §4.1）。"""


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _find_video(media_dir: Path) -> str:
    """在下载目录中查找视频文件（mp4/mov/mkv/flv/webm）。"""
    for f in media_dir.iterdir():
        if f.suffix.lower() in (".mp4", ".mov", ".mkv", ".flv", ".webm"):
            return str(f)
    raise PipelineOfflineError("下载完成但未找到视频文件")


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
    """下载最低画质视频，返回视频文件绝对路径。引擎缺失抛 PipelineOfflineError。"""
    media_dir.mkdir(parents=True, exist_ok=True)
    if platform == "douyin":
        # jiji262/douyin-downloader：python run.py -c config.yml -u <url> -p <out>
        jiji_dir = __import__("os").getenv("DOUYIN_DOWNLOADER_DIR", "")
        if not jiji_dir:
            raise PipelineOfflineError("抖音下载器 jiji262 未配置（DOUYIN_DOWNLOADER_DIR）")
        cfg = Path(jiji_dir) / "config.yml"
        if not cfg.exists():
            # 生成最小配置（video_quality=lowest 省流量）
            cfg.write_text(
                "video_quality: lowest\nthread: 3\nretry_times: 3\nprogress:\n  quiet_logs: true\n",
                encoding="utf-8",
            )
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
        if not _which("yutto"):
            raise PipelineOfflineError("yutto 未安装（GPL 子进程调用）")
        subprocess.run(["yutto", url, "-d", str(media_dir), "-q", "360p"], check=False)
    elif platform == "xhs":
        if not _which("xhs"):
            raise PipelineOfflineError("XHS-Downloader 未配置（GPL 子进程调用）")
        subprocess.run(["xhs", url, "-d", str(media_dir)], check=False)
    elif platform == "twitter":
        if not _which("yt-dlp"):
            raise PipelineOfflineError("yt-dlp 未安装")
        subprocess.run(
            ["yt-dlp", "-f", "worst", url, "-o", str(media_dir / "%(title)s.%(ext)s")],
            check=False,
        )
    else:
        # 兜底：尝试 MediaCrawler 适配器（全平台预留）
        if platform in MEDIACRAWLER_PLATFORMS:
            return download_via_mediacrawler(platform, url, media_dir)
        raise PipelineOfflineError(f"平台 {platform} 无下载器")

    return _find_video(media_dir)
