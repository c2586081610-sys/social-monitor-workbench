"""小红书单笔记媒体下载（浏览器拦截方案）：Playwright 有头打开笔记页 → 拦截 CDN 媒体响应 → 落盘。

为什么用这个方案：小红书 xsec_token 时效短、API 层 cookie 会过期；浏览器打开页面时自动签名，
拦截响应拿媒体直链最稳（不依赖 token/cookie 有效期）。

用法: python tools/xhs_note_dl.py <note_url> [输出目录]
输出: {out}/media_*.webp|jpg|mp4 + note_info.json（标题/描述/类型/点赞/图片数）
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "tools" / "xhs_profile"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python xhs_note_dl.py <note_url> [输出目录]")
        return 1
    url = sys.argv[1]
    note_id = url.split("/explore/")[-1].split("?")[0]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "media" / "_test_xhs" / f"note_{note_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    downloaded = []

    def on_response(resp):
        u = resp.url
        if ("sns-webpic" in u or "sns-video" in u or "xhscdn.com" in u) and resp.request.resource_type in (
            "image", "media", "video",
        ):
            try:
                body = resp.body()
                if len(body) > 4000:
                    ext = ".mp4" if ("video" in u or ".mp4" in u) else ".webp" if "webp" in resp.headers.get("content-type", "") else ".jpg"
                    fname = f"media_{len(downloaded) + 1:03d}{ext}"
                    (out_dir / fname).write_bytes(body)
                    downloaded.append({"file": fname, "size": len(body), "url": u})
            except Exception:
                pass

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False, viewport={"width": 1280, "height": 900},
            channel="msedge", args=["--no-proxy-server"],
        )
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)
        for _ in range(8):
            page.mouse.wheel(0, 2500)
            time.sleep(2)
        # 笔记信息
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
                            note_id: n.noteId || '', title: n.title || '',
                            desc: n.desc || '', type: n.type || '',
                            liked: (n.interactInfo || {}).likedCount || '',
                            commented: (n.interactInfo || {}).commentCount || '',
                            collected: (n.interactInfo || {}).collectedCount || '',
                            imgCount: n.imageList ? n.imageList.length : 0,
                            video: n.video ? true : false
                        };
                    } catch(e) { return {err: String(e).slice(0, 40)}; }
                }"""
            )
        except Exception:
            pass
        ctx.close()

    note_file = out_dir / "note_info.json"
    note_file.write_text(json.dumps({"info": info, "media": downloaded}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"下载 {len(downloaded)} 个媒体 → {out_dir}")
    if info:
        print(f"  标题: {info.get('title','')[:40]}")
        print(f"  类型: {info.get('type')} | 点赞: {info.get('liked')} | 评论: {info.get('commented')} | 图片数: {info.get('imgCount')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
