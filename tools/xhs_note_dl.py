"""小红书单笔记媒体下载：从 SSR state 提取源笔记正文图片/视频，精确下载（不抓页面杂图）。

2026-08-28 修复：旧版拦截所有 CDN 响应会混入头像/推荐位缩略图（43 文件里 32 个杂图）；
现改为读 window.__INITIAL_STATE__.note.noteDetailMap 的 imageList/video → 只下载源笔记内容。

用法: python tools/xhs_note_dl.py <note_url> [输出目录]
输出: {out}/media_*.webp|jpg|mp4 + note_info.json（标题/描述/正文图清单）
"""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "tools" / "xhs_profile"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
REFERER = "https://www.xiaohongshu.com/"


def _ext(ct: str, url: str) -> str:
    if "mp4" in ct or ".mp4" in url:
        return ".mp4"
    if "webp" in ct or ".webp" in url:
        return ".webp"
    if "png" in ct or ".png" in url:
        return ".png"
    return ".jpg"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python xhs_note_dl.py <note_url> [输出目录]")
        return 1
    url = sys.argv[1]
    note_id = url.split("/explore/")[-1].split("?")[0]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "media" / "_test_xhs" / f"note_{note_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False, viewport={"width": 1280, "height": 900},
            channel="msedge", args=["--no-proxy-server"],
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        data = page.evaluate(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.note) return null;
                try {
                    const m = s.note.noteDetailMap;
                    const n = Object.values(m)[0].note;
                    const images = (n.imageList || []).map(img => {
                        let u = img.urlDefault || img.urlPre || '';
                        const il = img.infoList || [];
                        if (il.length) u = il.reduce((a, b) => ((a.url || '').length > (b.url || '').length ? a : b)).url || u;
                        return u;
                    }).filter(x => x);
                    let video = '';
                    if (n.video) video = (n.video.media || {}).stream?.h264?.[0]?.masterUrl || n.video.url || '';
                    return {
                        note_id: n.noteId || '', title: n.title || '',
                        desc: n.desc || '', type: n.type || '',
                        liked: (n.interactInfo || {}).likedCount || '',
                        commented: (n.interactInfo || {}).commentCount || '',
                        imgCount: images.length,
                        images: images, video: video
                    };
                } catch(e) { return {err: String(e).slice(0, 60)}; }
            }"""
        )
        ctx.close()

    if not data or data.get("err"):
        print(f"[ERROR] 提取 SSR 数据失败: {data}")
        return 1

    downloaded = []
    # 正文图（精确：源笔记 imageList）
    for i, img_url in enumerate(data.get("images") or [], 1):
        try:
            r = httpx.get(img_url, timeout=20, headers={"User-Agent": UA, "Referer": REFERER})
            if r.status_code == 200 and len(r.content) > 1000:
                fname = f"media_{i:03d}{_ext(r.headers.get('content-type', ''), img_url)}"
                (out_dir / fname).write_bytes(r.content)
                downloaded.append({"file": fname, "size": len(r.content), "url": img_url})
        except Exception:
            continue
    # 视频（源笔记 video）
    if data.get("video"):
        try:
            r = httpx.get(data["video"], timeout=60, headers={"User-Agent": UA, "Referer": REFERER}, follow_redirects=True)
            if r.status_code == 200:
                fname = f"media_video{_ext(r.headers.get('content-type', ''), data['video'])}"
                (out_dir / fname).write_bytes(r.content)
                downloaded.append({"file": fname, "size": len(r.content), "url": data["video"]})
        except Exception:
            pass

    (out_dir / "note_info.json").write_text(
        json.dumps({"info": {k: data[k] for k in ("note_id", "title", "desc", "type", "liked", "commented", "imgCount")},
                    "media": downloaded}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"下载 {len(downloaded)} 个媒体（源笔记正文）→ {out_dir}")
    print(f"  标题: {data.get('title', '')[:40]}")
    print(f"  类型: {data.get('type')} | 点赞: {data.get('liked')} | 评论: {data.get('commented')} | 正文图片: {data.get('imgCount')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
