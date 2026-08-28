"""小红书博主笔记列表提取：SSR state 正则提取（主）+ 拦截 user_posted API（兜底），含 xsecToken/time。

2026-08-28 修复：小红书新版主页改为 SSR 内联数据（window.__INITIAL_STATE__），
user_posted API 在 cookie 降级时返回旧列表 → 改用 SSR 正则提取（note_id+title+xsec_token+time），
拦截保留为补充（去重合并）。

用法: python tools/xhs_fetch_notes.py <user_profile_url> [输出json路径]
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "tools" / "xhs_profile"

# SSR state 里每个笔记块：{"id":"<24hex>","noteCard":{...},"time":<ms>...}
_ID_PATTERN = re.compile(r'"id":"([0-9a-f]{24})","noteCard"')


def _parse_ssr_notes(html: str) -> list[dict]:
    """从 window.__INITIAL_STATE__ 提取笔记（主数据源，含最新作品）。"""
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        return []
    state = m.group(1)
    ids = list(dict.fromkeys(_ID_PATTERN.findall(state)))
    notes = []
    for idx, nid in enumerate(ids):
        i = state.find(f'"id":"{nid}","noteCard"')
        if i < 0:
            continue
        # 切片到下一个笔记块前（避免字段串到别的笔记）
        end = state.find('"id":"', i + 10)
        if end < 0:
            end = min(i + 6000, len(state))
        seg = state[i:end]

        def _grab(pattern: str) -> str | None:
            mm = re.search(pattern, seg)
            return mm.group(1) if mm else None

        title = _grab(r'"displayTitle":"([^"]*)"')
        token = _grab(r'"xsecToken":"([^"]*)"')
        t_raw = _grab(r'"time":(\d+)')
        liked = _grab(r'"likedCount":(\d+)')
        comment = _grab(r'"commentCount":(\d+)')
        if not nid or not title:
            continue
        notes.append(
            {
                "note_id": nid,
                "title": title.replace("\\u002F", "/").replace("\\u0026", "&"),
                "type": "normal",
                "xsec_token": token or "",
                "liked_count": liked or "0",
                "comment_count": comment or "0",
                "has_video": False,
                "cover": "",
                "time": int(t_raw) if t_raw else 0,  # 毫秒
            }
        )
    return notes


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python xhs_fetch_notes.py <user_profile_url> [out.json]")
        return 1
    url = sys.argv[1]
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "workbuddy" / "xhs_notes.json"

    from playwright.sync_api import sync_playwright

    notes: list[dict] = []
    seen: set[str] = set()

    def merge_item(item: dict) -> None:
        nid = item.get("note_id") or ""
        if not nid or nid in seen:
            return
        seen.add(nid)
        notes.append(item)

    def on_response(resp):
        if "user_posted" not in resp.url:
            return
        try:
            d = resp.json()
        except Exception:
            return
        for n in (d.get("data") or {}).get("notes") or []:
            nid = n.get("noteId") or n.get("note_id") or ""
            merge_item(
                {
                    "note_id": nid,
                    "title": n.get("display_title") or n.get("title") or "",
                    "type": n.get("type") or "normal",
                    "xsec_token": n.get("xsec_token") or "",
                    "liked_count": (n.get("interact_info") or {}).get("liked_count", "0"),
                    "comment_count": (n.get("interact_info") or {}).get("comment_count", "0"),
                    "has_video": bool(n.get("video")),
                    "cover": (n.get("cover") or {}).get("url_default", ""),
                    "time": n.get("time") or 0,
                }
            )

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, viewport={"width": 1280, "height": 900},
            channel="msedge", args=["--no-proxy-server"],
        )
        # 注入 config/platform_cookies.json 的最新 xhs cookie（优先级高于旧 profile）
        try:
            _cfg = json.loads((ROOT / "config" / "platform_cookies.json").read_text(encoding="utf-8"))
            _ck = (_cfg.get("xhs") or {}).get("cookie") or ""
            if _ck:
                for _pair in _ck.split(";"):
                    if "=" not in _pair:
                        continue
                    _name, _val = _pair.strip().split("=", 1)
                    if not _name:
                        continue
                    try:
                        ctx.add_cookies([{"name": _name, "value": _val, "domain": ".xiaohongshu.com", "path": "/"}])
                    except Exception:
                        pass
        except Exception:
            pass
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        html = page.content()
        # 滚动加载更多（拦截兜底补充）
        for _ in range(8):
            page.mouse.wheel(0, 2500)
            time.sleep(2.5)
        ctx.close()

    # SSR state（主）+ 拦截（兜底）合并
    for item in _parse_ssr_notes(html):
        merge_item(item)
    # 按时间倒序（毫秒兼容）
    notes.sort(key=lambda n: int(n.get("time") or 0), reverse=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    videos = [n for n in notes if n["has_video"]]
    print(f"提取笔记 {len(notes)} 条（含视频 {len(videos)} 条），已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
