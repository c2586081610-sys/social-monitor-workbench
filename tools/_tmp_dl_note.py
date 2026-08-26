"""临时：Playwright 有头打开笔记页，拦截媒体响应下载（浏览器自动签名，绕过 token/cookie 过期）。"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
NOTE = "6a699ba30000000001000a87"
TOKEN = "ABuP-R_FAfVR5G7DTdtVlwfb7DkdEXfI6f0NlNObnN5qY"
URL = f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token={TOKEN}&xsec_source=pc_user"
PROFILE = ROOT / "tools" / "xhs_profile"
SAVE_DIR = ROOT / "media" / "_test_xhs" / "note_6a699ba3"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
downloaded = []


def on_response(resp):
    u = resp.url
    if ("sns-webpic" in u or "sns-video" in u or "xhscdn" in u) and resp.request.resource_type in ("image", "media", "video"):
        try:
            body = resp.body()
            if len(body) > 5000:
                ext = ".jpg"
                if "video" in u or ".mp4" in u:
                    ext = ".mp4"
                elif ".webp" in u or "webp" in resp.headers.get("content-type", ""):
                    ext = ".webp"
                fname = f"media_{len(downloaded) + 1:02d}{ext}"
                (SAVE_DIR / fname).write_bytes(body)
                downloaded.append({"file": fname, "size": len(body), "url": u[:100]})
                print(f"[下载] {fname} ({len(body)//1024}KB) {u[:80]}")
        except Exception:
            pass


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE), headless=False, viewport={"width": 1280, "height": 900},
        channel="msedge", args=["--no-proxy-server"],
    )
    page = ctx.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(10)
    # 滚动触发懒加载
    for _ in range(8):
        page.mouse.wheel(0, 2500)
        time.sleep(2)
    # 提取笔记信息
    info = None
    try:
        info = page.evaluate(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.note) return null;
                try {
                    const m = s.note.noteDetailMap;
                    const n = Object.values(m)[0].note;
                    return {
                        title: n.title || '',
                        desc: (n.desc || '').slice(0, 200),
                        type: n.type || '',
                        liked: (n.interactInfo || {}).likedCount || '',
                        imgCount: n.imageList ? n.imageList.length : 0
                    };
                } catch(e) { return {err: String(e).slice(0, 40)}; }
            }"""
        )
    except Exception as e:
        print("evaluate err:", str(e)[:50])
    print("笔记信息:", json.dumps(info, ensure_ascii=False)[:300])
    print("已下载媒体:", len(downloaded), "→", SAVE_DIR)
    ctx.close()
