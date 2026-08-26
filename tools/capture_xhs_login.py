"""用 Playwright 交互登录捕获小红书网页版 cookie（与抖音 dy_profile 同一方法）。

流程：弹出浏览器窗口 → 打开小红书 → 用户扫码/账号登录 → 检测到 web_session 后自动保存
输出: config/platform_cookies.json -> xhs.cookie（XHS-Downloader --cookie 格式）
用法: python capture_xhs_login.py [--timeout 秒]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "tools" / "xhs_profile"
OUT_CFG = ROOT / "config" / "platform_cookies.json"
LOGIN_URL = "https://www.xiaohongshu.com/explore"
KEY_COOKIE = "web_session"


def export_cookies(ctx) -> str:
    cookies = ctx.cookies(["https://www.xiaohongshu.com", "https://.xiaohongshu.com"])
    pairs = []
    seen = set()
    for c in cookies:
        if c["name"] in seen or c["name"].endswith("_1P_JAR"):
            continue
        seen.add(c["name"])
        pairs.append(f"{c['name']}={c['value']}")
    return "; ".join(pairs)


def verify_login(cookie_str: str) -> bool:
    """校验是否真实登录：id_token 是登录后才下发的 cookie（访客没有）。"""
    return "id_token=" in cookie_str and "web_session=" in cookie_str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=300, help="等待登录超时(秒)")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] 请先安装 playwright: pip install playwright && python -m playwright install chromium")
        return 1

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # 优先系统 Edge（channel），失败回退 chromium（需已 install）
        context = None
        browser_error = None
        for launcher in (
            lambda: p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, channel="msedge", viewport={"width": 1280, "height": 900},
                args=["--no-proxy-server"],  # 绕过梯子直连小红书（梯子全局代理会挡 xhs）
            ),
            lambda: p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, viewport={"width": 1280, "height": 900},
                args=["--no-proxy-server"],
            ),
        ):
            try:
                context = launcher()
                break
            except Exception as exc:  # noqa: BLE001
                browser_error = exc
        if context is None:
            print(f"[ERROR] 浏览器启动失败: {browser_error}")
            print("        请执行: python -m playwright install chromium")
            return 1

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        print(f"[提示] 浏览器已打开小红书，请【在窗口内完成登录】（扫码或账号密码）。")
        print(f"[提示] 未验证到真实登录态前不会保存；最多等待 {args.timeout} 秒。")

        deadline = time.time() + args.timeout
        while time.time() < deadline:
            try:
                cookie_str = export_cookies(context)
                if cookie_str and verify_login(cookie_str):
                    print("[OK] API 验证通过：真实登录态确认！")
                    # 保存
                    cfg = {}
                    if OUT_CFG.exists():
                        try:
                            cfg = json.loads(OUT_CFG.read_text(encoding="utf-8"))
                        except Exception:
                            cfg = {}
                    cfg.setdefault("xhs", {})["cookie"] = cookie_str
                    OUT_CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"[OK] 已写入: {OUT_CFG} -> xhs.cookie（{len(cookie_str)} 字符）")
                    print("[提示] 登录态已保存在 tools/xhs_profile/；cookie 失效时重跑本脚本")
                    time.sleep(3)
                    context.close()
                    return 0
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)

        print("[WARN] 超时未检测到真实登录态（可能未登录或 cookie 验证失败）。profile 已保留，可重跑。")
        context.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
