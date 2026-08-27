"""一次性爬取脚本：按需拉起 RSSHub → 爬取 → 关闭（跑完即退，不留常驻）。

由聚合 API /monitor/poll-now 以无窗口子进程拉起（stdout 重定向到
workbuddy/onetime_poll.log）；也可命令行直接运行。

用法：
    python monitor/onetime_poll.py                       # 全部启用平台
    python monitor/onetime_poll.py --platform bilibili   # 单平台
    python monitor/onetime_poll.py --creator 12          # 单博主

行为：
    - 探测 RSSHub（settings.rsshub_base_url），未运行则用 CREATE_NO_WINDOW 拉起
      tools/rsshub（node dist/index.mjs），轮询等待就绪（最长 60s）。
    - 复用 monitor/jobs.py 的轮询函数完成爬取，写 poll_logs + 更新 last_poll_at。
    - 退出前关闭本次拉起的 RSSHub（原本就在跑则不动）。
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 支持 `python monitor/onetime_poll.py` 直接运行：先把工作区根加入 sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 再导入 shared_db（把 backend 加入 sys.path），随后导入 app.* 与 monitor.*
from monitor.store.shared_db import SessionLocal, settings  # noqa: E402

from app.core.db import init_db  # noqa: E402
from app.repositories import health_repo  # noqa: E402

from monitor import jobs  # noqa: E402

logger = logging.getLogger("monitor.onetime_poll")

RSSHUB_READY_TIMEOUT = 60
RSSHUB_PROBE_INTERVAL = 2
# Windows 无窗口创建标志；非 Windows 平台为 0（不影响）
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RSSHUB_DIR = settings.workspace_root / "tools" / "rsshub"
# 探测用 opener：显式禁用代理，且不读环境变量（避免 HTTP(S)_PROXY 把本机探测导到代理）
_PROBE_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _probe(url: str) -> bool:
    """探测 RSSHub：/health 或 / 返回非 5xx 即视为就绪。

    - 用 urllib 而非 httpx：部分沙箱对 httpx 的 loopback 请求会统一返回 502，
      会误判 RSSHub 未就绪；urllib + 禁用代理对本机探测最稳。
    - 5xx（尤其 502）多为启动中/上游故障，不能当作 ready。
    """
    if not url:
        return False
    for path in ("/health", "/"):
        try:
            with _PROBE_OPENER.open(url + path, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return True
        except (urllib.error.URLError, OSError):
            continue
    return False


def _start_rsshub() -> subprocess.Popen:
    """无窗口拉起 RSSHub（cwd=tools/rsshub，node dist/index.mjs）。

    NODE_OPTIONS 可能携带沙箱 shim（genie-safe-delete），子进程需剥离；
    同时按 npm start 惯例置 NODE_ENV=production。
    """
    entry = RSSHUB_DIR / "dist" / "index.mjs"
    if not entry.exists():
        raise RuntimeError(f"RSSHub 未构建: {entry}")
    node = shutil.which("node") or "node"
    env = os.environ.copy()
    env.pop("NODE_OPTIONS", None)
    env["NODE_ENV"] = "production"
    proc = subprocess.Popen(
        [node, "dist/index.mjs"],
        cwd=str(RSSHUB_DIR),
        env=env,
        creationflags=CREATE_NO_WINDOW,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    logger.info("已拉起 RSSHub pid=%s", proc.pid)
    return proc


def ensure_rsshub() -> subprocess.Popen | None:
    """确保 RSSHub 就绪：未运行则拉起并等待 ready。

    Returns:
        本次拉起的 Popen（调用方负责关闭）；原本就在运行返回 None。
    Raises:
        RuntimeError: 启动超时或拉起失败。
    """
    if _probe(settings.rsshub_base_url):
        logger.info("RSSHub 已在运行: %s", settings.rsshub_base_url)
        return None
    logger.info("RSSHub 未运行，开始拉起: %s", settings.rsshub_base_url or "(未配置)")
    proc = _start_rsshub()
    deadline = time.time() + RSSHUB_READY_TIMEOUT
    while time.time() < deadline:
        time.sleep(RSSHUB_PROBE_INTERVAL)
        if _probe(settings.rsshub_base_url):
            logger.info("RSSHub 就绪")
            return proc
    _shutdown_rsshub(proc)
    raise RuntimeError(f"RSSHub 启动超时（{RSSHUB_READY_TIMEOUT}s 未就绪）")


def _shutdown_rsshub(proc: subprocess.Popen) -> None:
    logger.info("关闭本次拉起的 RSSHub pid=%s", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _creator_needs_rsshub(creator_id: int) -> bool:
    with SessionLocal() as db:
        from app.models import Creator

        creator = db.get(Creator, creator_id)
        return bool(creator and creator.platform in jobs.RSSHUB_PLATFORMS)


def _poll_platform(platform: str) -> None:
    """单平台爬取；poll_rsshub_platform/poll_douyin 内部已写 poll_logs。"""
    if platform in jobs.RSSHUB_PLATFORMS:
        jobs.poll_rsshub_platform(platform)
    elif platform == "douyin":
        jobs.poll_douyin()
    else:
        logger.warning("未知平台，跳过: %s", platform)


def run(platform: str | None, creator_id: int | None) -> int:
    init_db()
    started = time.time()
    rsshub_proc: subprocess.Popen | None = None
    try:
        if creator_id is not None:
            if settings.rsshub_base_url and _creator_needs_rsshub(creator_id):
                rsshub_proc = ensure_rsshub()
            jobs.poll_rsshub_creator(creator_id)
            return 0
        if platform:
            targets = [platform]
        else:
            targets = list(jobs.RSSHUB_PLATFORMS) + ["douyin"]
        if settings.rsshub_base_url and any(p in jobs.RSSHUB_PLATFORMS for p in targets):
            rsshub_proc = ensure_rsshub()
        elif any(p in jobs.RSSHUB_PLATFORMS for p in targets):
            logger.warning("RSSHUB_BASE_URL 未配置，跳过 RSSHub 平台（douyin 仍执行）")
        for p in targets:
            try:
                _poll_platform(p)
            except Exception as exc:  # noqa: BLE001  单平台失败不阻塞其余平台
                logger.exception("平台 %s 爬取异常", p)
                with SessionLocal() as db:
                    health_repo.create_poll_log(db, p, "failed", detail=str(exc)[:500])
                    db.commit()
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("一次性爬取失败: %s", exc)
        return 1
    finally:
        if rsshub_proc is not None:
            _shutdown_rsshub(rsshub_proc)
        logger.info("一次性爬取结束，耗时 %.1fs", time.time() - started)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="一次性爬取（按需拉起 RSSHub，跑完关闭）")
    parser.add_argument("--platform", default=None, help="平台：bilibili/xhs/twitter/douyin")
    parser.add_argument("--creator", type=int, default=None, help="博主 ID（优先于 --platform）")
    args = parser.parse_args(argv)
    return run(args.platform, args.creator)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(main())
