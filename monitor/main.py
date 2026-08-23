"""监控层调度入口（独立进程，与聚合 API 解耦可恢复）。

启动：
    python monitor/main.py
行为：
    - 心跳写盘（聚合 API 据此判断在线）
    - 定时轮询 RSSHub 平台（B站/小红书/推特）
    - 抖音 CDP 占位轮询（ENABLE_DOUYIN_CDP=true 时启用）
    - 消费 /monitor/poll 写下的 trigger 文件
    - MONITOR_RUN_PIPELINE=true 时执行流水线（下载→转写→抽帧→清单）
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# 支持 `python monitor/main.py` 直接运行：先把工作区根加入 sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 再导入 shared_db（把 backend 加入 sys.path），随后导入 app.* 与 monitor.*
from monitor.store.shared_db import settings  # noqa: E402

from app.core.db import init_db  # noqa: E402

from monitor import jobs  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("monitor")


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        jobs.write_heartbeat,
        IntervalTrigger(seconds=settings.heartbeat_interval),
        id="heartbeat",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        jobs.consume_triggers,
        IntervalTrigger(seconds=settings.poll_trigger_interval),
        id="consume_triggers",
        max_instances=1,
        coalesce=True,
    )
    for platform in jobs.RSSHUB_PLATFORMS:
        scheduler.add_job(
            jobs.poll_rsshub_platform,
            IntervalTrigger(seconds=settings.poll_rsshub_interval),
            args=[platform],
            id=f"poll_rsshub_{platform}",
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        jobs.poll_douyin,
        IntervalTrigger(seconds=settings.poll_douyin_interval),
        id="poll_douyin",
        max_instances=1,
        coalesce=True,
    )
    if settings.monitor_run_pipeline:
        scheduler.add_job(
            jobs.run_pipeline,
            IntervalTrigger(seconds=30),
            id="run_pipeline",
            max_instances=1,
            coalesce=True,
        )
    return scheduler


def main() -> None:
    init_db()
    jobs.write_heartbeat()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("监控层已启动 pid=%s", __import__("os").getpid())
    logger.info(
        "配置: rsshub=%s changedetection=%s douyin_cdp=%s pipeline=%s",
        settings.rsshub_base_url or "(未配置)",
        settings.changedetection_url or "(未配置)",
        settings.douyin_cdp_enabled,
        settings.monitor_run_pipeline,
    )
    try:
        import time

        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        logger.info("监控层退出")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
