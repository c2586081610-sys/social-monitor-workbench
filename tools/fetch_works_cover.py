"""下载作品封面到本地 media/cover/，更新 works.cover_url 为本地路径（解决小红书/推特等防盗链）。

用法: python tools/fetch_works_cover.py [--limit N] [--platform douyin/xhs/bilibili/twitter]
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))  # for app.core.config
from app.core.config import settings  # noqa: E402

# 各平台防盗链所需 Referer
REFERERS = {
    "xhs": "https://www.xiaohongshu.com/",
    "xiaohongshu.com": "https://www.xiaohongshu.com/",
    "douyin": "https://www.douyin.com/",
    "bilibili": "https://www.bilibili.com/",
    "twitter": "https://twitter.com/",
}

# UA（部分平台校验 UA）
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _safe_name(rid: str, url: str) -> str:
    """从 cover_url 推断扩展名（默认 jpg）。"""
    m = re.search(r"\.(jpg|jpeg|png|webp|gif|avif)(\?|$)", url, re.I)
    ext = (m.group(1) if m else "jpg").lower()
    if ext == "jpeg":
        ext = "jpg"
    return f"{rid}.{ext}"


def fetch_one(platform: str, url: str) -> bytes | None:
    import httpx

    if not url or not url.startswith("http"):
        return None
    referer = REFERERS.get(platform, "https://www.google.com/")
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={
            "Referer": referer, "User-Agent": UA,
        })
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def main() -> int:
    limit = 200
    platform_filter = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--platform="):
            platform_filter = arg.split("=", 1)[1]

    cover_root = settings.media_root / "cover"
    cover_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect("aggregator.db")
    rows = conn.execute(
        """SELECT id, platform, COALESCE(cover_url,'') FROM works WHERE cover_url IS NOT NULL AND cover_url != '' AND cover_url NOT LIKE '/media/%' """
    ).fetchall()
    if platform_filter:
        rows = [r for r in rows if r[1] == platform_filter]
    rows = rows[:limit]
    print(f"待处理 {len(rows)} 条封面")

    ok = skip = fail = 0
    for rid, platform, url in rows:
        out_path = cover_root / _safe_name(str(rid), url)
        if out_path.exists() and out_path.stat().st_size > 0:
            skip += 1
            rel = f"cover/{out_path.name}"
            conn.execute("UPDATE works SET cover_url=? WHERE id=?", (f"/media/{rel}", rid))
            continue
        data = fetch_one(platform, url)
        if not data:
            fail += 1
            continue
        out_path.write_bytes(data)
        rel = f"cover/{out_path.name}"
        conn.execute("UPDATE works SET cover_url=? WHERE id=?", (f"/media/{rel}", rid))
        ok += 1
    conn.commit()
    print(f"下载成功 {ok}，已存在跳过 {skip}，失败 {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())