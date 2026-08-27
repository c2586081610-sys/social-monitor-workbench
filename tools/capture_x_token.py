"""capture_x_token.py - 交互式捕获 x.com 登录态（auth_token + ct0），写入 config/platform_cookies.json。

流程：弹出 Chrome（复用 Profile 2）→ 打开 x.com/login → 等待用户在窗口内登录
→ 检测到 auth_token 后自动导出。用法: python tools/capture_x_token.py
"""
import json, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path("C:/Users/Administrator/AppData/Local/Google/Chrome/User Data")
PROFILE = "Profile 2"
PROXY = "http://127.0.0.1:7892"
COOKIE_CFG = ROOT / "config" / "platform_cookies.json"
WAIT_MAX = 300  # 最多等 5 分钟


def main() -> int:
    udd = CHROME / PROFILE
    print(f"弹出 Chrome（{PROFILE}），请在浏览器窗口中登录 x.com ...")
    print(f"登录完成后将自动捕获 auth_token，最长等待 {WAIT_MAX // 60} 分钟")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(udd),
            channel="chrome",
            headless=False,
            proxy={"server": PROXY},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.new_page()
        page.goto("https://x.com/login", timeout=60000, wait_until="domcontentloaded")
        auth_token = None
        ct0 = None
        deadline = time.time() + WAIT_MAX
        while time.time() < deadline:
            cookies = ctx.cookies()
            x_cookies = [c for c in cookies if "x.com" in c["domain"]]
            auth = [c for c in x_cookies if c["name"] == "auth_token"]
            if auth:
                auth_token = auth[0]["value"]
                c = [c for c in x_cookies if c["name"] == "ct0"]
                ct0 = c[0]["value"] if c else None
                break
            time.sleep(3)
        ctx.close()
    if not auth_token:
        print("超时未捕获到 auth_token（可能未完成登录）")
        return 1

    print(f"捕获成功: auth_token={auth_token[:12]}...(len={len(auth_token)})")
    if ct0:
        print(f"         ct0={ct0[:12]}...(len={len(ct0)})")

    # 写入 config/platform_cookies.json
    cfg = json.loads(COOKIE_CFG.read_text(encoding="utf-8")) if COOKIE_CFG.exists() else {}
    cfg.setdefault("twitter", {})
    cfg["twitter"]["_auth_token"] = auth_token
    if ct0:
        cfg["twitter"]["_ct0"] = ct0
    cfg["twitter"]["_note"] = "capture_x_token.py 于登录后自动捕获，仅用于 RSSHub 监控"
    COOKIE_CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {COOKIE_CFG}")
    print("把 auth_token 填入 RSSHub 环境变量: $env:TWITTER_AUTH_TOKEN=\"%s\"" % auth_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
