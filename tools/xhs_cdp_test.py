"""CDP 连接测试：连日常 Edge（9222 端口），检查小红书登录态。

用法: python tools/xhs_cdp_test.py
前提: 已运行 tools/edge_cdp.cmd 启动日常 Edge（调试端口 9222）
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9222"


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL, timeout=15000)
        except Exception as e:
            print(f"[ERROR] 无法连接 {CDP_URL}：{str(e)[:80]}")
            print("请先运行 tools/edge_cdp.cmd 启动日常 Edge（调试端口 9222）")
            return 1

        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)

        # 登录态检查
        state = page.evaluate(
            """() => {
                try {
                    const u = (window.__INITIAL_STATE__ || {}).user || {};
                    return { loggedIn: !!u.loggedIn, nick: ((u.userInfo||{})||{}).nickname || '', userId: ((u.userInfo||{})||{}).userId || '' };
                } catch(e) { return { err: String(e).slice(0,40) }; }
            }"""
        )
        url_now = page.url[:60]
        print(f"当前 URL: {url_now}")
        print(f"登录态: {json.dumps(state, ensure_ascii=False)}")

        if state and state.get("loggedIn"):
            print("[OK] 日常 Edge 已登录小红书:", state.get("nick", "?"))
        else:
            print("[提示] 未检测到登录态——请在日常 Edge 窗口里登录小红书后重试")

        # 导出 cookie（写回 config，供 MediaCrawler 使用）
        cookies = ctx.cookies(["https://www.xiaohongshu.com", "https://edith.xiaohongshu.com"])
        ck = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "platform_cookies.json"
        import json as _json
        from pathlib import Path as _P
        cfg = _json.loads(_P(cfg_path).read_text(encoding="utf-8"))
        cfg["xhs"]["cookie"] = ck
        _P(cfg_path).write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] 已从日常 Edge 导出 cookie 到 config（{len(ck)} 字符）")

        page.close()
        browser.close()
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
