"""抖音监测适配器：复用本地 MediaCrawler（cookie 登录态 + DouYinClient 签名）。

来源：用户原仓库 douyin-video-archive/dy_daily_incremental.py（真增量、低风控）思路：
  - 只请求博主首页 1 页（count=18 最新视频）→ aweme_list → 与 works 表对比去重由 jobs 层完成
  - 单次爬取仅 1 个 API 请求；子进程隔离（MediaCrawler venv 执行，主进程无需 cv2/PIL）

依赖：
  - tools/mediacrawler（完整安装 + .venv）
  - tools/mediacrawler/config/base_config.py 的 COOKIES 已填有效抖音 cookie
    （tools/export_dy_cookie_edge.py 可从 Edge 真实 profile 提取）
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("monitor.douyin_mediacrawler")

_FETCH_SCRIPT = Path(__file__).resolve().parent / "dy_mediacrawler_fetch.py"


class DouyinMediaCrawlerAdapter:
    """抖音博主最新作品抓取（子进程调用 MediaCrawler venv）。"""

    def __init__(self, mediacrawler_dir: Path) -> None:
        self.dir = Path(mediacrawler_dir)

    def _venv_python(self) -> Path | None:
        for p in ("Scripts/python.exe", "bin/python"):
            cand = self.dir / ".venv" / p
            if cand.exists():
                return cand
        return None

    def available(self) -> bool:
        """MediaCrawler 安装完整 + COOKIES 已配置 + venv 存在。"""
        import re

        if not self.dir.exists():
            return False
        cfg = self.dir / "config" / "base_config.py"
        if not (cfg.exists() and (self.dir / "media_platform" / "douyin" / "client.py").exists()):
            return False
        if not self._venv_python():
            return False
        m = re.search(r'^COOKIES\s*=\s*"([^"]*)"', cfg.read_text(encoding="utf-8", errors="ignore"), re.M)
        return bool(m and m.group(1).strip())

    def poll_creator(self, sec_uid: str, count: int = 18) -> list[dict]:
        """抓取博主首页最新 count 条作品（子进程隔离，超时 150s）。"""
        py = self._venv_python()
        if not py:
            return []
        env = dict(os.environ)
        env["MEDIACRAWLER_DIR"] = str(self.dir)
        try:
            proc = subprocess.run(
                [str(py), str(_FETCH_SCRIPT), sec_uid, str(count)],
                capture_output=True,
                text=True,
                timeout=150,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("douyin 抓取超时（>150s）")
            return []
        out = (proc.stdout or "").strip()
        if not out or proc.returncode != 0:
            logger.warning("douyin 抓取失败 rc=%s err=%s", proc.returncode, (proc.stderr or "")[-300:])
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            logger.warning("douyin 抓取输出非 JSON: %s", out[:200])
            return []
        if isinstance(data, dict) and data.get("error"):
            logger.warning("douyin 抓取 error: %s", data["error"])
            return []
        if not isinstance(data, list):
            return []
        checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for item in data:
            if not isinstance(item, dict):
                continue
            item["metadata_checked_at"] = checked_at
            published_at = item.get("published_at")
            if isinstance(published_at, str) and published_at:
                item["published_time_source"] = "douyin_mediacrawler_create_time"
                item["published_time_precision"] = "second"
                item["published_time_timezone"] = "UTC"
        return data
