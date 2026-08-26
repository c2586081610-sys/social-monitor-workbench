"""临时：拦截 feed API 响应提取笔记真实图片列表（imageList）并下载。"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
NOTE = "6a699ba30000000001000a87"
TOKEN = "ABuP-R_FAfVR5G7DTdtVlwfb7DkdEXfI6f0NlNObnN5qY"
URL = f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token={TOKEN}&xsec_source=pc_user"
PROFILE = ROOT / "tools" / "xhs_profile"
SAVE_DIR = ROOT / "media" / "_test_xhs" / "note_6a699ba3" / "real_images"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
feed_data = []


def on_response(resp):
    try:
        if "api/sns/web/v1/feed" in resp.url:
            d = resp.json()
            items = (d.get("data") or {}).get("items") or []
            for it in items:
                card = it.get("note_card") or {}
                if card.get("noteId") == NOTE or card.get("note_id") == NOTE or card.get("display_title"):
                    feed_data.append(card)
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
    ctx.close()

if not feed_data:
    print("未捕获 feed 响应")
else:
    card = feed_data[-1]
    imgs = card.get("imageList") or card.get("image_list") or []
    print("标题:", card.get("title") or card.get("display_title"))
    print("图片列表数:", len(imgs))
    # 下载图片
    from curl_cffi import requests as creq
    saved = []
    for i, img in enumerate(imgs):
        url = img.get("urlDefault") or img.get("url") or ""
        if not url:
            continue
        try:
            r = creq.get(url, impersonate="chrome120", headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=30)
            if r.status_code == 200 and len(r.content) > 5000:
                ext = ".webp" if "webp" in r.headers.get("content-type", "") else ".jpg"
                f = SAVE_DIR / f"note_img_{i+1:02d}{ext}"
                f.write_bytes(r.content)
                saved.append({"file": f.name, "size": len(r.content), "url": url[:90]})
                print(f"[OK] {f.name} ({len(r.content)//1024}KB)")
        except Exception as e:
            print(f"[FAIL] img{i}: {str(e)[:40]}")
    (SAVE_DIR / "images_manifest.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    print("保存清单:", SAVE_DIR / "images_manifest.json")
