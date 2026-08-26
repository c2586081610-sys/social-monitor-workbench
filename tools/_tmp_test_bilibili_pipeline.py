"""临时验证脚本：B站作品完整流水线（下载→转写→抽帧→pending 清单）。

用法：python tools/_tmp_test_bilibili_pipeline.py
跑完清理测试记录，正式博主配置走 API。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 工作区根

from monitor.store.shared_db import SessionLocal  # noqa: E402
from app.repositories import creator_repo, work_repo  # noqa: E402
from monitor.jobs import _process_work  # noqa: E402

BV = "BV11S826nE2Z"
URL = f"https://www.bilibili.com/video/{BV}"
TITLE = "【B站链路验证】Attention 注意别喝多"
CREATOR = "链路验证-莫梓艺大笑"

with SessionLocal() as db:
    creator = creator_repo.get_by_platform_external(db, "bilibili", "test-e2e-1108")
    if creator is None:
        creator = creator_repo.create(
            db, platform="bilibili", external_id="test-e2e-1108", name=CREATOR,
            profile_url=f"https://space.bilibili.com/test-e2e-1108", enabled=1,
        )
    work = work_repo.upsert(
        db, "bilibili", BV,
        title=TITLE, url=URL, creator_id=creator.id,
        source_type="manual", status="NEW",
    )
    db.commit()
    work_id = work.id
    print(f"work_id={work_id} status={work.status}")

    _process_work(db, work)
    db.commit()
    db.refresh(work)
    print(f"最终状态: {work.status}")
    print(f"media_path: {work.media_path}")
    print(f"transcript: {work.transcript_path}")
    print(f"frames: {work.frame_manifest_path}")
