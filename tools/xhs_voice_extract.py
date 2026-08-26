"""小红书语音评论转写提取：从页面 DOM 的 audio-comment-container 提取语音转文字。

原理：小红书网页自带"语音转文字"（服务端转写），DOM 类 audio-comment-container
的 span 文本即转写内容——无需本地 FunASR。

用法: python tools/xhs_voice_extract.py <note_id> [url]
输出: workbuddy/xhs_voice_{note_id}.json（voice 评论+转写+关联）
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CDP = "http://127.0.0.1:9222"


def main() -> int:
    note_id = sys.argv[1] if len(sys.argv) > 1 else "6a694aff000000000503a3b8"
    url_arg = sys.argv[2] if len(sys.argv) > 2 else ""
    voices = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=15000)
        ctx = browser.contexts[0]
        page = None
        # 找已打开的该笔记页，否则新开
        for pg in ctx.pages:
            if note_id in pg.url and "explore" in pg.url:
                page = pg
                break
        if page is None:
            page = ctx.new_page()
            page.goto(url_arg or f"https://www.xiaohongshu.com/explore/{note_id}", wait_until="domcontentloaded", timeout=60000)
            time.sleep(8)
        # 滚动评论区 + 展开回复，触发全部评论加载
        for _ in range(15):
            try:
                # 点击展开回复
                page.evaluate(
                    """() => {
                        const els = document.querySelectorAll('.show-more, .expand-comment, [class*=expand-comment], [class*=show-more], [class*=audio-comment] button, [class*=voice] button');
                        if (els.length) els[0].click();
                    }"""
                )
            except Exception:
                pass
            try:
                page.evaluate(
                    """() => {
                        const c = document.querySelector('.comments-container');
                        if (c) c.scrollTop = c.scrollHeight;
                        window.scrollBy(0, 800);
                    }"""
                )
            except Exception:
                pass
            time.sleep(2.5)
        # 提取语音转文字 + 关联评论上下文
        voices = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.audio-comment-container').forEach(el => {
                    const text = (el.textContent || '').trim();
                    if (!text) return;
                    // 向上找评论容器，提取用户/时间/点赞
                    let cmt = el.closest('.comment-item, [class*=comment-item]');
                    const nick = cmt ? (cmt.querySelector('[class*=nickname], [class*=name]')?.textContent || '').trim() : '';
                    const likes = cmt ? (cmt.querySelector('[class*=like]')?.textContent || '').trim() : '';
                    const timeEl = cmt ? (cmt.querySelector('time, [class*=time], [class*=date]')?.textContent || '').trim() : '';
                    out.push({ text, nick, likes, time: timeEl });
                });
                return out;
            }"""
        )
        browser.close()

    # 去重（同一语音可能在多个渲染节点）
    seen, uniq = set(), []
    for v in voices:
        key = v["text"][:30]
        if key not in seen:
            seen.add(key)
            uniq.append(v)

    out = ROOT / "workbuddy" / f"xhs_voice_{note_id}.json"
    out.write_text(json.dumps({"note_id": note_id, "voice_comments": uniq}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"语音转文字提取: {len(uniq)} 条 → {out}")
    for v in uniq:
        print(f"  [{v.get('nick') or '?'}] {v['text'][:40]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
