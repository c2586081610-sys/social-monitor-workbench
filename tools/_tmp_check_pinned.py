"""临时验证：小红书评论置顶标识。"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

notes = json.load(open(ROOT / "workbuddy" / "xhs_notes.json", encoding="utf-8"))
n = next(x for x in notes if x["note_id"] == "6a7421670000000025007f23")
url = f"https://www.xiaohongshu.com/explore/{n['note_id']}?xsec_token={n['xsec_token']}&xsec_source=pc_user"
profile = ROOT / "tools" / "xhs_profile"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(profile), headless=True, viewport={"width": 1280, "height": 900},
        channel="msedge", args=["--no-proxy-server"],
    )
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    time.sleep(8)

    # 1. 页面是否有"置顶"文本及其上下文
    pinned = page.eval_on_selector_all(
        "text=置顶",
        """els => els.map(e => {
            const c = e.closest('[class*=comment]');
            return (e.textContent || '').slice(0, 8) + ' | 父class: ' + (c ? String(c.className).slice(0, 60) : '无');
        })""",
    )
    print("置顶标识:", pinned if pinned else "未找到'置顶'文本")

    # 2. 评论区第一条评论文本
    first = page.evaluate(
        """() => {
            const els = document.querySelectorAll('[class*=comment-item], [class*=commentItem]');
            for (const el of els) {
                if (el.textContent.length > 20) return el.textContent.slice(0, 80);
            }
            return '未找到';
        }"""
    )
    print("评论区首条:", first)
    ctx.close()
