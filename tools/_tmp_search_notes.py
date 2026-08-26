"""临时：通过搜索进入博主主页（无需旧token），拦截 user_posted 拿笔记列表。"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "tools" / "xhs_profile"
KEYWORD = "长宁辛吉德"
notes = []


def on_response(resp):
    try:
        if "user_posted" in resp.url:
            d = resp.json()
            for n in (d.get("data") or {}).get("notes") or []:
                nid = n.get("noteId") or n.get("note_id") or ""
                if nid:
                    notes.append(
                        {
                            "note_id": nid,
                            "title": n.get("display_title") or n.get("title") or "",
                            "type": n.get("type") or "normal",
                            "xsec_token": n.get("xsec_token") or "",
                            "liked_count": (n.get("interact_info") or {}).get("liked_count", "0"),
                        }
                    )
    except Exception:
        pass


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE), headless=True, viewport={"width": 1280, "height": 900},
        channel="msedge", args=["--no-proxy-server"],
    )
    page = ctx.new_page()
    page.on("response", on_response)
    # 搜索
    page.goto(f"https://www.xiaohongshu.com/search_result?keyword={KEYWORD}", wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    print("搜索页标题:", page.title()[:30])
    # 点用户 tab 或第一个用户卡片
    for sel in ['text=用户', '[class*=user-card]', '[class*=user-item]']:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible(timeout=3000):
                el.click(timeout=3000)
                print("点击:", sel)
                time.sleep(5)
                break
        except Exception:
            continue
    # 滚动加载
    for _ in range(6):
        page.mouse.wheel(0, 2500)
        time.sleep(2.5)
    print("抓到笔记:", len(notes))
    # 保存
    out = ROOT / "workbuddy" / "xhs_notes.json"
    out.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    for n in notes[:6]:
        print(" ", n["note_id"][:12], n["title"][:24], "| xsec:", bool(n["xsec_token"]))
    ctx.close()
