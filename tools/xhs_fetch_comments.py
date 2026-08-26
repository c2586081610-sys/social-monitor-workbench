"""小红书单条笔记评论抓取：Playwright 拦截 comment/page API，多策略滚动分页加载全量评论（含回复）。

用法: python tools/xhs_fetch_comments.py <note_url> [输出json路径]
前置: tools/xhs_profile/ 已登录（capture_xhs_login.py）
输出: workbuddy/xhs_comments_{note_id}.json
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "tools" / "xhs_profile"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python xhs_fetch_comments.py <note_url> [out.json]")
        return 1
    url = sys.argv[1]
    note_id = url.split("/explore/")[-1].split("?")[0]

    from playwright.sync_api import sync_playwright

    comments = []  # 去重：同 id 只留第一次（含首次附带回复）
    seen = set()

    def on_response(resp):
        if not resp.url.split("?")[0].endswith("/comment/page"):
            return
        try:
            d = resp.json()
        except Exception:
            return
        for c in (d.get("data") or {}).get("comments") or []:
            cid = c.get("id") or ""
            if not cid or cid in seen:
                continue
            seen.add(cid)
            sub = []
            for s in (c.get("sub_comments") or [])[:20]:
                sub.append(
                    {
                        "user": (s.get("user_info") or {}).get("nickname", ""),
                        "text": s.get("content") or "",
                        "likes": s.get("like_count") or 0,
                        "time": s.get("create_time") or "",
                    }
                )
            comments.append(
                {
                    "id": cid,
                    "user": (c.get("user_info") or {}).get("nickname", ""),
                    "text": c.get("content") or "",
                    "likes": c.get("like_count") or 0,
                    "time": c.get("create_time") or "",
                    "sub_comment_count": c.get("sub_comment_count") or 0,
                    "replies": sub,
                }
            )

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, viewport={"width": 1280, "height": 900},  # 有头：小红书无头渲染不稳
            channel="msedge", args=["--no-proxy-server"],  # 系统 Edge 指纹 + 绕过梯子直连小红书
        )
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        # 点击"查看更多评论"（可能多次出现/嵌套）
        for _ in range(5):
            try:
                page.get_by_text("查看更多评论", exact=False).first.click(timeout=2000)
                time.sleep(2)
            except Exception:
                break

        # 多策略滚动分页：直到评论数稳定
        last = -1
        stale = 0
        for round_i in range(60):
            time.sleep(2)
            if len(comments) != last:
                last = len(comments)
                stale = 0
            else:
                stale += 1
                if stale >= 4:
                    break
            # 策略1：滚动评论区容器（小红书评论在内部滚动容器 comments-container）
            try:
                page.evaluate(
                    """() => {
                        const c = document.querySelector('.comments-container') || document.querySelector('.comments-el');
                        if (c) c.scrollTop = c.scrollHeight;
                        window.scrollBy(0, 400);
                    }"""
                )
            except Exception:
                pass
            time.sleep(1.5)
            # 策略2：滚动所有可滚动容器到底
            try:
                page.evaluate(
                    """() => {
                        document.querySelectorAll('.comments-container *, [class*=comment-list] *').forEach(el => {
                            if (el.scrollHeight > el.clientHeight + 200) el.scrollTop = el.scrollHeight;
                        });
                    }"""
                )
            except Exception:
                pass
            time.sleep(1.5)
            # 策略3：点击加载更多（如有）
            try:
                page.get_by_text("查看更多", exact=False).first.click(timeout=1500)
                time.sleep(1)
            except Exception:
                pass

        ctx.close()

    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "workbuddy" / f"xhs_comments_{note_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 置顶评论识别（第一性原理）：评论列表第一条被固定在首位；
    # 若其点赞不是全局最高 → 它不是自然热度排序 → 判定为置顶评论。
    # 若第一条恰为最高赞 → 无法区分（标记 may_pinned，笔记里按"第一条评论"单独列出）。
    max_like = max((int(c["likes"]) for c in comments), default=0)
    pinned = None
    if comments:
        first = comments[0]
        if int(first["likes"]) < max_like:
            first["pinned"] = True
            pinned = first
        else:
            first["pinned"] = False
            first["may_pinned"] = max_like > 0
    doc = {"note_id": note_id, "pinned_comment": pinned, "comments": comments}
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    pin_note = f"｜置顶评论: {pinned['user']}『{pinned['text'][:20]}』" if pinned else ""
    print(f"评论 {len(comments)} 条（含回复 {sum(len(c['replies']) for c in comments)} 条）{pin_note}，已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
