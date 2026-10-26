"""抖音抓取子进程（由 MediaCrawler venv 的 python 执行，主进程 subprocess 调用）。

用法: <mediacrawler_venv_python> dy_mediacrawler_fetch.py <sec_uid> [count]
输出: JSON 数组到 stdout（[{external_id,title,url,published_at,content_type}]）
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_MC_DIR = Path(os.environ.get("MEDIACRAWLER_DIR", "tools/mediacrawler")).resolve()
sys.path.insert(0, str(_MC_DIR))
os.chdir(_MC_DIR)  # MediaCrawler help.py 相对路径读 libs/*.js


def _iso(ts) -> str | None:
    try:
        timestamp = int(ts)
        if timestamp <= 0:
            return None
        published = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if published.year <= 1970:
            return None
        return published.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


async def _fetch(sec_uid: str, count: int) -> list[dict]:
    import config  # noqa: F401  COOKIES
    from media_platform.douyin.client import DouYinClient
    from tools import utils

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser_context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(_MC_DIR / "browser_data" / "dy_user_data_dir"),
            headless=True,
            args=["--no-proxy-server"],
        )
        context_page = await browser_context.new_page()
        await context_page.goto("https://www.douyin.com/")
        for k, v in utils.convert_str_cookie_to_dict(config.COOKIES).items():
            await browser_context.add_cookies([{"name": k, "value": v, "domain": ".douyin.com", "path": "/"}])
        await browser_context.add_cookies([{"name": "LOGIN_STATUS", "value": "1", "domain": ".douyin.com", "path": "/"}])
        await context_page.reload()
        await asyncio.sleep(3)

        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context, urls=["https://www.douyin.com/", "https://douyin.com"]
        )
        client = DouYinClient(
            proxy=None,
            headers={
                "User-Agent": await context_page.evaluate("() => navigator.userAgent"),
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=context_page,
            cookie_dict=cookie_dict,
        )
        res = await client.get_user_aweme_posts(sec_user_id=sec_uid, max_cursor="")
        aweme_list = res.get("aweme_list") or []
        items = []
        for aw in aweme_list:
            aid = str(aw.get("aweme_id") or "")
            if not aid:
                continue
            # 封面：video.cover.url_list[0]（原平台封面）
            cover = ""
            try:
                cover = (aw.get("video") or {}).get("cover", {}).get("url_list") or []
                cover = cover[0] if cover else ""
            except Exception:
                cover = ""
            items.append(
                {
                    "platform": "douyin",
                    "external_id": aid,
                    "title": aw.get("desc") or "",
                    "url": f"https://www.douyin.com/video/{aid}",
                    "published_at": _iso(aw.get("create_time")),
                    "content_type": "video",
                    "cover_url": cover or None,
                }
            )
        return items


def main() -> int:
    if len(sys.argv) < 2:
        print("[]", file=sys.stderr)
        return 2
    sec_uid = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 18
    try:
        items = asyncio.run(_fetch(sec_uid, count))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(items, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
