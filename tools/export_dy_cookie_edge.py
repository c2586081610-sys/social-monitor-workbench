"""从 Edge 真实 profile（Playwright msedge channel）提取抖音 cookie，写入 MediaCrawler COOKIES。

前提：Edge 已关闭；Edge 里已登录抖音。
用法: python export_dy_cookie_edge.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE_UD = Path(r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data")
CONFIG = ROOT / "tools" / "mediacrawler" / "config" / "base_config.py"
DOUYIN_URLS = ["https://www.douyin.com", "https://douyin.com"]


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not EDGE_UD.exists():
        print(f"[ERROR] Edge User Data 不存在: {EDGE_UD}")
        return 1

    cookies = []
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(EDGE_UD),
                channel="msedge",
                headless=False,
                args=["--no-proxy-server", "--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            print(f"[ERROR] 打开 Edge profile 失败: {e}")
            print("提示: 请确认 Edge 已完全关闭（任务管理器无 msedge 进程）")
            return 2
        page = ctx.new_page()
        page.goto("https://www.douyin.com/", timeout=60000)
        page.wait_for_timeout(6000)  # 等登录态生效
        for u in DOUYIN_URLS:
            try:
                cookies.extend(ctx.cookies([u]))
            except Exception:
                pass
        ctx.close()

    if not cookies:
        print("[WARN] 未获取到 cookie（确认 Edge 已登录抖音）")
        return 3

    # 去重
    seen, unique = set(), []
    for c in cookies:
        if c["name"] not in seen:
            seen.add(c["name"])
            unique.append(c)
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in unique)
    keys = [c["name"] for c in unique]
    print(f"[OK] 导出 {len(unique)} 个 cookie")
    print("关键字段:", [k for k in keys if k in ("sessionid", "sid_tt", "odin_tt", "ttwid", "passport_csrf_token", "LOGIN_STATUS")])

    text = CONFIG.read_text(encoding="utf-8")
    new_text = re.sub(r'^COOKIES\s*=.*$', f'COOKIES = "{cookie_str}"', text, count=1, flags=re.M)
    if new_text == text:
        print("[WARN] 未匹配 COOKIES 行")
        return 4
    CONFIG.write_text(new_text, encoding="utf-8")
    print(f"[OK] 已写入 MediaCrawler COOKIES（{len(cookie_str)} 字符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
