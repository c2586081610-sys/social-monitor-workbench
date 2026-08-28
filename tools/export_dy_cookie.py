"""从 Playwright 持久化 profile（tools/dy_profile/）导出抖音 cookie，写入 MediaCrawler COOKIES。

用法: python export_dy_cookie.py
输出: 打印 cookie 数量；写入 tools/mediacrawler/config/base_config.py 的 COOKIES
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "tools" / "dy_profile"
CONFIG = ROOT / "tools" / "mediacrawler" / "config" / "base_config.py"


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not PROFILE.exists():
        print(f"[ERROR] profile 不存在: {PROFILE}")
        return 1

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True)
        except Exception:
            # 兜底：部分 profile 用 msedge channel 创建
            ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True, channel="msedge")
        cookies = ctx.cookies(["https://www.douyin.com", "https://douyin.com/"])
        ctx.close()

    if not cookies:
        print("[WARN] 未获取到任何 douyin cookie（profile 登录态可能已失效，需重新登录）")
        return 2

    pairs = [f"{c['name']}={c['value']}" for c in cookies]
    cookie_str = "; ".join(pairs)
    print(f"[OK] 导出 {len(cookies)} 个 cookie，长度 {len(cookie_str)}")
    print("关键字段:", [c["name"] for c in cookies if c["name"] in ("sessionid", "sid_tt", "odin_tt", "ttwid", "passport_csrf_token")])

    # 写入 MediaCrawler base_config.py COOKIES
    if not CONFIG.exists():
        print(f"[ERROR] MediaCrawler 配置不存在: {CONFIG}")
        return 3
    text = CONFIG.read_text(encoding="utf-8")
    new_text = re.sub(r'^COOKIES\s*=.*$', f'COOKIES = "{cookie_str}"', text, count=1, flags=re.M)
    if new_text == text:
        print("[WARN] 未匹配到 COOKIES 行，手动检查配置格式")
        return 4
    CONFIG.write_text(new_text, encoding="utf-8")
    print("[OK] 已写入 MediaCrawler COOKIES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
