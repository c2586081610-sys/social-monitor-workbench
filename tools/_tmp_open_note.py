"""临时：Playwright 打开小红书笔记页提取信息与媒体直链。"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
NOTE = "6a699ba30000000001000a87"
TOKEN = "ABuP-R_FAfVR5G7DTdtVlwfb7DkdEXfI6f0NlNObnN5qY"
URL = f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token={TOKEN}&xsec_source=pc_user"
PROFILE = ROOT / "tools" / "xhs_profile"
media = []


def on_request(req):
    u = req.url
    if "xhscdn.com" in u and req.resource_type in ("media", "video", "image") and "formula-static" not in u:
        media.append({"type": req.resource_type, "url": u})


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE), headless=True, viewport={"width": 1280, "height": 900},
        channel="msedge", args=["--no-proxy-server"],
    )
    page = ctx.new_page()
    page.on("request", on_request)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    time.sleep(9)
    try:
        print("页面标题:", page.title()[:50])
    except Exception as e:
        print("title err:", str(e)[:60])
    print("媒体请求数:", len(media))
    for m in media[:8]:
        print(" ", m["type"], m["url"][:120])
    # 稳定后尝试提取笔记信息（try 包裹）
    for attempt in range(3):
        try:
            info = page.evaluate(
                """() => {
                    const s = window.__INITIAL_STATE__;
                    if (!s) return null;
                    try {
                        const m = s.note.noteDetailMap;
                        const n = Object.values(m)[0].note;
                        return { title: n.title || '', type: n.type || '', xsec: (n.xsecToken || '').slice(0,20) };
                    } catch(e) { return {err: String(e).slice(0,40)}; }
                }"""
            )
            print("笔记信息:", json.dumps(info, ensure_ascii=False)[:200])
            break
        except Exception as e:
            print(f"evaluate retry {attempt}: {str(e)[:50]}")
            time.sleep(2)
    ctx.close()
