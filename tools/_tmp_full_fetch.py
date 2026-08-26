"""临时：综合抓取——拦截 feed(imageList原图)+comment(评论) + 下载正确图片。"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
NOTE = "6a699ba30000000001000a87"
TOKEN = "ABuP-R_FAfVR5G7DTdtVlwfb7DkdEXfI6f0NlNObnN5qY"
URL = f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token={TOKEN}&xsec_source=pc_user"
PROFILE = ROOT / "tools" / "xhs_profile"
IMG_DIR = ROOT / "media" / "_test_xhs" / "note_6a699ba3" / "real_images"
IMG_DIR.mkdir(parents=True, exist_ok=True)
feed_cards = []
comments = []
seen_cmt = set()


def on_response(resp):
    try:
        u = resp.url
        if "api/sns/web/v1/feed" in u:
            d = resp.json()
            for it in ((d.get("data") or {}).get("items") or []):
                card = it.get("note_card") or {}
                if card.get("display_title") or card.get("noteId") == NOTE:
                    feed_cards.append(card)
        elif "comment/page" in u:
            d = resp.json()
            for c in (d.get("data") or {}).get("comments") or []:
                cid = c.get("id")
                if cid and cid not in seen_cmt:
                    seen_cmt.add(cid)
                    comments.append(
                        {
                            "comment_id": cid,
                            "content": c.get("content") or "",
                            "nickname": (c.get("user_info") or {}).get("nickname", ""),
                            "like_count": c.get("like_count") or 0,
                            "create_time": c.get("create_time") or 0,
                            "sub_comment_count": c.get("sub_comment_count") or 0,
                            "pictures": ",".join(p.get("url_default", "") for p in (c.get("pictures") or [])),
                            "parent_comment_id": (c.get("target_comment") or {}).get("id", ""),
                        }
                    )
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
    # 滚动触发评论分页
    for _ in range(10):
        page.mouse.wheel(0, 3000)
        time.sleep(2.5)
        try:
            page.get_by_text("查看更多评论", exact=False).first.click(timeout=1500)
        except Exception:
            pass
    ctx.close()

# 1. feed imageList（正确原图）
imgs = []
for card in feed_cards:
    imgs = card.get("imageList") or card.get("image_list") or []
    if imgs:
        break
print("feed 捕获:", len(feed_cards), "| imageList:", len(imgs))
from curl_cffi import requests as creq
saved = []
for i, img in enumerate(imgs):
    url = img.get("urlDefault") or img.get("url") or ""
    if not url:
        continue
    try:
        r = creq.get(url, impersonate="chrome120", headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=30)
        if r.status_code == 200 and len(r.content) > 3000:
            ext = ".webp" if "webp" in r.headers.get("content-type", "") else ".jpg"
            f = IMG_DIR / f"note_img_{i+1:02d}{ext}"
            f.write_bytes(r.content)
            saved.append({"file": f.name, "size": len(r.content)})
            print(f"[图] {f.name} ({len(r.content)//1024}KB)")
    except Exception:
        pass
(IMG_DIR / "images_manifest.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

# 2. 评论保存
cmt_path = ROOT / "workbuddy" / f"xhs_comments_{NOTE}.json"
doc = {"note_id": NOTE, "comments": comments}
cmt_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"评论 {len(comments)} 条 → {cmt_path}")
