"""小红书评论完整分析：层级重组 + 置顶识别 + 点赞排序 + 图片评论 + 语音评论标记。

输入: workbuddy/xhs_comments_{note_id}_full.json（doc: {note_id, comments}）
输出: workbuddy/xhs_comment_report_{note_id}_full.md + _full.json（结构化）
用法: python tools/xhs_comment_analyze.py <note_id> [标题]
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))


def ts_str(ts) -> str:
    try:
        ts = int(ts)
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, CST).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def is_voice(c) -> bool:
    """语音评论标记：内容为空 且 非图片评论（小红书语音评论 content 空）。"""
    return not (c.get("content") or "").strip() and not c.get("pictures")


def analyze(note_id: str, title: str) -> dict:
    # 匹配数据文件（支持完整/短 id，兼容 *_full.json 两种命名）
    short = note_id[:7]
    candidates = list((ROOT / "workbuddy").glob(f"xhs_comments_*{short}*_full.json"))
    if not candidates:
        raise FileNotFoundError(f"未找到 {short} 的评论数据，先跑 mc_xhs_comments.py")
    src = candidates[0]
    doc = json.loads(src.read_text(encoding="utf-8"))
    comments = doc["comments"]
    # 去重
    seen, uniq = set(), []
    for c in comments:
        if c.get("comment_id") not in seen:
            seen.add(c["comment_id"])
            uniq.append(c)
    comments = uniq

    parents = [c for c in comments if not c.get("parent_comment_id")]
    subs = [c for c in comments if c.get("parent_comment_id")]
    # 层级重组：父评论 + 其下子回复
    tree = []
    for p in parents:
        replies = [s for s in subs if s.get("parent_comment_id") == p.get("comment_id")]
        tree.append({"parent": p, "replies": sorted(replies, key=lambda s: -int(s.get("like_count") or 0))})
    # 置顶识别（第一性原理）：列表第一条 + 点赞非最高 → 置顶
    max_like = max((int(c.get("like_count") or 0) for c in parents), default=0)
    pinned = None
    if comments and int(comments[0].get("like_count") or 0) < max_like:
        pinned = comments[0]
    # 点赞排序（父评论）
    top = sorted(parents, key=lambda c: -int(c.get("like_count") or 0))
    # 图片评论 / 语音评论
    pic_cmts = [c for c in comments if c.get("pictures")]
    voice_cmts = [c for c in comments if is_voice(c)]

    times = [c.get("create_time") for c in comments if c.get("create_time")]
    return {
        "note_id": note_id,
        "title": title,
        "stats": {
            "评论总数": len(comments),
            "父评论": len(parents),
            "子回复": len(subs),
            "唯一用户": len({c.get("creator_hash") for c in comments}),
            "图片评论": len(pic_cmts),
            "语音评论(标记)": len(voice_cmts),
            "最高点赞": max_like,
            "时间范围": f"{ts_str(min(times))} ~ {ts_str(max(times))}" if times else "",
        },
        "pinned_comment": pinned,
        "top_comments": top[:10],
        "voice_comments": voice_cmts,
        "pic_comments": pic_cmts,
        "tree": tree,
    }


def to_markdown(r: dict) -> str:
    s = r["stats"]
    L = [
        f"# 小红书评论完整分析（{r['title']}）", "",
        f"- **评论总数**：{s['评论总数']}（父 {s['父评论']} / 子回复 {s['子回复']}）",
        f"- **唯一用户**：{s['唯一用户']}｜**最高点赞**：{s['最高点赞']}",
        f"- **图片评论**：{s['图片评论']} 条｜**语音评论**：{s['语音评论(标记)']} 条（⏳ 未配置转写，仅标记）",
        f"- **时间范围**：{s['时间范围']}",
    ]
    # 置顶
    if r.get("pinned_comment"):
        p = r["pinned_comment"]
        L += ["", "## 📌 置顶评论", "", f"> **{p.get('nickname','')}**：" + (p.get("content") or "[语音/图片内容]") + f"（{p.get('like_count',0)}赞）"]
    # 语音评论（标记）
    if r.get("voice_comments"):
        L += ["", "## 🎙️ 语音评论（已标记，未处理）", ""]
        for v in r["voice_comments"]:
            L.append(f"- [{v.get('like_count',0)}赞] {v.get('nickname','')}：{ts_str(v.get('create_time'))}（语音内容，转写待配置）")
    # 点赞榜
    L += ["", "## 点赞 TOP（父评论）", "", "| 点赞 | 昵称 | 内容 | 回复数 | 图片 | 语音 |", "|------|------|------|--------|------|------|"]
    for c in r["top_comments"]:
        L.append(f"| {c.get('like_count',0)} | {c.get('nickname','')} | {(c.get('content') or '')[:40] or '[空]'} | {c.get('sub_comment_count',0)} | {'📷' if c.get('pictures') else ''} | {'🎙️' if is_voice(c) else ''} |")
    # 层级（Top10 父 + 回复）
    L += ["", "## 评论层级（点赞榜 Top10 父评论 + 回复）", ""]
    for node in r["tree"][:10]:
        p = node["parent"]
        L.append(f"- **{p.get('nickname','')}**（{p.get('like_count',0)}赞）：{(p.get('content') or '')[:50] or '[语音/图片]'}")
        for rep in node["replies"][:3]:
            L.append(f"  - ┗ {rep.get('nickname','')}（{rep.get('like_count',0)}赞）：{(rep.get('content') or '')[:40]}")
    # 图片评论
    if r.get("pic_comments"):
        L += ["", "## 图片评论", ""]
        for c in r["pic_comments"][:5]:
            L.append(f"- [{c.get('like_count',0)}赞] {c.get('nickname','')}：{(c.get('content') or '')[:30]}（图：{c.get('pictures','')[:50]}）")
    return "\n".join(L)


def main() -> int:
    note_id = sys.argv[1] if len(sys.argv) > 1 else "6a694aff000000000503a3b8"
    title = sys.argv[2] if len(sys.argv) > 2 else "债基混债红利选哪个"
    r = analyze(note_id, title)
    md = to_markdown(r)
    out_md = ROOT / "workbuddy" / f"xhs_comment_report_{note_id}_full.md"
    out_json = ROOT / "workbuddy" / f"xhs_comment_report_{note_id}_full.json"
    out_md.write_text(md, encoding="utf-8")
    out_json.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    s = r["stats"]
    print(f"完整报告: {out_md}")
    print(f"  评论 {s['评论总数']}（父{s['父评论']}/子{s['子回复']}）| 置顶: {'✅' if r['pinned_comment'] else '❌'} | 图片评论 {s['图片评论']} | 语音评论 {s['语音评论(标记)']}（标记）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
