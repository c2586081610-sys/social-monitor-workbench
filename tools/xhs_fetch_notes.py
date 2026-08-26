"""小红书博主笔记列表提取：Playwright 拦截 user_posted API，保存完整笔记数据（含 xsecToken）。

用法: python tools/xhs_fetch_notes.py <user_profile_url> [输出json路径]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "tools" / "xhs_profile"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python xhs_fetch_notes.py <user_profile_url> [out.json]")
        return 1
    url = sys.argv[1]
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "workbuddy" / "xhs_notes.json"

    from playwright.sync_api import sync_playwright

    notes = []
    seen = set()

    def on_response(resp):
        if "user_posted" not in resp.url:
            return
        try:
            d = resp.json()
        except Exception:
            return
        for n in (d.get("data") or {}).get("notes") or []:
            nid = n.get("noteId") or n.get("note_id") or ""
            if not nid or nid in seen:
                continue
            seen.add(nid)
            notes.append(
                {
                    "note_id": nid,
                    "title": n.get("display_title") or n.get("title") or "",
                    "type": n.get("type") or "normal",
                    "xsec_token": n.get("xsec_token") or "",
                    "liked_count": (n.get("interact_info") or {}).get("liked_count", "0"),
                    "comment_count": (n.get("interact_info") or {}).get("comment_count", "0"),
                    "has_video": bool(n.get("video")),
                    "cover": (n.get("cover") or {}).get("url_default", ""),
                }
            )

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, viewport={"width": 1280, "height": 900},
            channel="msedge", args=["--no-proxy-server"],  # 系统 Edge 指纹 + 绕过梯子直连小红书
        )
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # 滚动加载 3 页（约 30-40 条）
        for _ in range(8):
            page.mouse.wheel(0, 2500)
            time.sleep(2.5)
        ctx.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    videos = [n for n in notes if n["has_video"]]
    print(f"提取笔记 {len(notes)} 条（含视频 {len(videos)} 条），已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
