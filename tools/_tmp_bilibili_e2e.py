"""B站端到端链路测试：凯圣王《碳水循环上集》完整流水线（下载→转写→抽帧→pending清单）。

用法：python tools/_tmp_bilibili_e2e.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor.store.shared_db import SessionLocal  # noqa: E402
from app.models import Group, Work  # noqa: E402
from app.repositories import creator_repo, group_repo, work_repo  # noqa: E402
from monitor.jobs import _process_work  # noqa: E402

BVID = "BV1Gh411479A"
URL = f"https://www.bilibili.com/video/{BVID}"
TITLE = "【收藏向】碳水循环上集~饮食计划一站式分享（减脂必备）"
CREATOR_MID = "2100737396"
CREATOR_NAME = "凯圣王"
GROUP_NAME = "健身"
PUBLISHED_AT = "2021-11-17T22:31:36+08:00"


def _retry(fn, tries=12, delay=4):
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"[retry {i+1}/{tries}] {type(exc).__name__}: {str(exc)[:80]}")
            time.sleep(delay)


def run():
    with SessionLocal() as db:
        # 1. 分组（幂等）
        group = db.query(Group).filter(Group.name == GROUP_NAME).first()
        if group is None:
            group = group_repo.create(db, name=GROUP_NAME)
            print(f"创建分组: {GROUP_NAME} id={group.id}")
        # 2. 博主（幂等）
        creator = creator_repo.get_by_platform_external(db, "bilibili", CREATOR_MID)
        if creator is None:
            creator = creator_repo.create(
                db,
                platform="bilibili",
                external_id=CREATOR_MID,
                name=CREATOR_NAME,
                profile_url=f"https://space.bilibili.com/{CREATOR_MID}",
                group_id=group.id,
                enabled=1,
            )
            print(f"创建博主: {CREATOR_NAME} id={creator.id}")
        else:
            creator.group_id = group.id
        # 3. 作品（幂等）
        work = work_repo.upsert(
            db,
            "bilibili",
            BVID,
            title=TITLE,
            url=URL,
            creator_id=creator.id,
            group_id=group.id,  # work 自身挂分组（_work_media_dir 取 work.group.name）
            published_at=PUBLISHED_AT,
            source_type="manual",
            status="NEW",
        )
        db.commit()
        print(f"work_id={work.id} status={work.status}")
        # 同 session 内 relationship 可能缓存旧值（group），expire 强制重载后再跑流水线
        db.expire(work)

        # 4. 完整流水线（下载→转写→抽帧→pending）
        _retry(lambda: (_process_work(db, work), db.commit()))
        db.refresh(work)
        print("=== 流水线完成 ===")
        print(f"最终状态: {work.status}")
        print(f"media_path: {work.media_path}")
        print(f"transcript: {work.transcript_path}")
        print(f"frames: {work.frame_manifest_path}")
        print(f"last_error: {work.last_error}")


if __name__ == "__main__":
    run()
