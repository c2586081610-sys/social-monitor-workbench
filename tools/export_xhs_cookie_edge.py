"""从 Edge 真实 profile（Playwright msedge channel）提取小红书 cookie，写入 config/platform_cookies.json。

前提：Edge 已关闭；Edge 里已登录小红书。
用法: python export_xhs_cookie_edge.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE_UD = Path(r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data")
COOKIE_FILE = ROOT / "config" / "platform_cookies.json"
XHS_URLS = ["https://www.xiaohongshu.com", "https://xiaohongshu.com"]


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not EDGE_UD.exists():
        print(f"[ERROR] Edge User Data 不存在: {EDGE_UD}")
        return 1

    cookies = []
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(EDGE_UD), channel="msedge", headless=False,
                args=["--no-proxy-server", "--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            print(f"[ERROR] 打开 Edge profile 失败: {e}")
            print("提示: 请确认 Edge 已完全关闭（任务管理器无 msedge 进程）")
            return 2
        page = ctx.new_page()
        page.goto("https://www.xiaohongshu.com/explore", timeout=60000)
        page.wait_for_timeout(6000)
        for u in XHS_URLS:
            try:
                cookies.extend(ctx.cookies([u]))
            except Exception:
                pass
        ctx.close()

    if not cookies:
        print("[WARN] 未获取到 cookie（确认 Edge 已登录小红书）")
        return 3

    seen, unique = set(), []
    for c in cookies:
        if c["name"] not in seen:
            seen.add(c["name"])
            unique.append(c)
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in unique)
    keys = [c["name"] for c in unique]
    print(f"[OK] 导出 {len(unique)} 个 cookie")
    print("关键字段:", [k for k in keys if k in ("web_session", "webId", "a1", "gid", "xsecappid")])

    data = {}
    if COOKIE_FILE.exists():
        try:
            data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data.setdefault("xhs", {})["cookie"] = cookie_str
    data["xhs"]["_updated_at"] = "2026-08-28"
    COOKIE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 已写入 {COOKIE_FILE}（xhs.cookie {len(cookie_str)} 字符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
