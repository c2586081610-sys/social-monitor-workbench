"""MediaCrawler 小红书评论 DIY 增强报告：对齐"易小红"的附带统计 + 层级导出。

读 MediaCrawler 导出的 detail_comments_*.jsonl，输出：
  1. 附带统计：评论总数/子评论数/唯一用户数/图片评论数/点赞Top/首末评论时间/关键词TOP
  2. 层级导出：父评论 + ┗ 回复 重组（按 parent_comment_id）
  3. 置顶识别：列表第一条 + 点赞非最高 → 置顶（第一性原理）
输出: workbuddy/xhs_comment_report_{note_id}.md + .json

用法: python tools/mc_comment_report.py [jsonl路径] [输出前缀]
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))


def load_comments(jsonl_path: Path) -> list[dict]:
    comments = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            comments.append(json.loads(line))
    return comments


def ts_to_str(ts) -> str:
    """毫秒时间戳 → CST 字符串"""
    try:
        ts = int(ts)
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts or "")


def keyword_top(comments: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """jieba 关键词 TOP（评论内容分词统计，去掉常见停用词）。"""
    try:
        import jieba
        jieba.setLogLevel(60)
    except ImportError:
        return []
    stop = set("的了在是我有和就都不这也那一个要吗吧啊嗯哦呢哈呀啦什么怎么你们他们我们大家老师请问一下可以吗".strip())
    texts = " ".join(c.get("content", "") for c in comments if c.get("content"))
    words = [w for w in jieba.cut(texts) if len(w) >= 2 and w not in stop and not w.isdigit()]
    return Counter(words).most_common(top_n)


def dedup_comments(comments: list[dict]) -> list[dict]:
    """按 comment_id 去重；同 id 保留字段更全的那条（MediaCrawler 子评论分页可能重复落库）。"""
    best: dict[str, dict] = {}
    for c in comments:
        cid = c.get("comment_id") or c.get("id") or ""
        if not cid:
            continue
        prev = best.get(cid)
        if prev is None:
            best[cid] = c
            continue
        if (1 if c.get("content") else 0) > (1 if prev.get("content") else 0):
            best[cid] = c
    return list(best.values())


def build_report(note: dict | None, comments: list[dict]) -> dict:
    comments = dedup_comments(comments)
    parents = [c for c in comments if not c.get("parent_comment_id")]
    subs = [c for c in comments if c.get("parent_comment_id")]
    users = {c.get("creator_hash") or c.get("nickname") for c in comments}
    with_pic = [c for c in comments if c.get("pictures")]
    # 首末时间
    times = [c.get("create_time") for c in comments if c.get("create_time")]
    # 点赞 Top（父评论内排序，置顶单独）
    max_like = max((int(c.get("like_count") or 0) for c in parents), default=0)
    top_parents = sorted(parents, key=lambda c: int(c.get("like_count") or 0), reverse=True)
    # 置顶识别（第一性原理）：抓取顺序第一条（置顶固定在最前），若点赞非全局最高 → 置顶
    pinned = None
    if comments and parents and int(comments[0].get("like_count") or 0) < max_like:
        pinned = comments[0]
    # 关键词
    kw = keyword_top(comments)

    return {
        "note": note,
        "stats": {
            "评论总数": len(comments),
            "父评论": len(parents),
            "子评论回复": len(subs),
            "唯一用户数": len(users),
            "图片评论数": len(with_pic),
            "最高点赞": max_like,
            "首条评论时间": ts_to_str(min(times)) if times else "",
            "末条评论时间": ts_to_str(max(times)) if times else "",
            "关键词TOP": kw,
        },
        "pinned_comment": pinned,
        "top_comments": top_parents[:10],
    }


def to_markdown(rpt: dict) -> str:
    stats = rpt["stats"]
    lines = [
        "# 小红书评论统计报告",
        "",
        f"- **评论总数**：{stats['评论总数']}（父评论 {stats['父评论']} / 子回复 {stats['子评论回复']}）",
        f"- **唯一用户数**：{stats['唯一用户数']}",
        f"- **图片评论**：{stats['图片评论数']} 条",
        f"- **最高点赞**：{stats['最高点赞']}",
        f"- **评论时间范围**：{stats['首条评论时间']} ~ {stats['末条评论时间']}",
        "",
        "## IP 属地分布",
        "",
        "| 属地 | 数量 |",
        "|------|------|",
    ]
    if stats["关键词TOP"]:
        lines += ["", "## 评论关键词 TOP", "", "| 关键词 | 次数 |", "|--------|------|"]
        for w, c in stats["关键词TOP"]:
            lines.append(f"| {w} | {c} |")
    # 置顶
    if rpt.get("pinned_comment"):
        p = rpt["pinned_comment"]
        lines += ["", "## 📌 置顶评论", "", f"> **{p.get('nickname','')}**：「{p.get('content','')}」"]
    # Top 评论
    if rpt.get("top_comments"):
        lines += ["", "## 点赞 TOP 评论", "", "| 点赞 | 昵称 | 内容 | 回复数 | 图片 |", "|------|------|------|--------|------|"]
        for c in rpt["top_comments"]:
            pics = "📷" if c.get("pictures") else ""
            lines.append(
                f"| {c.get('like_count',0)} | {c.get('nickname','')} | {(c.get('content') or '')[:40]} | {c.get('sub_comment_count',0)} | {pics} |"
            )
    # 层级评论（父+回复）
    lines += ["", "## 评论层级（父评论 + 回复）", ""]
    seen_subs = set()
    for c in rpt["top_comments"]:
        lines.append(f"- **{c.get('nickname','')}**：{c.get('content','')}（{c.get('like_count',0)}赞）")
        cid = c.get("comment_id")
        for s in [x for x in rpt_note_subs if x.get("parent_comment_id") == cid][:5]:
            seen_subs.add(s.get("comment_id"))
            lines.append(f"  - ┗ {s.get('nickname','')}：{s.get('content','')[:40]}")
    return "\n".join(lines)


# 供 to_markdown 使用（模块级避免参数传递复杂度）
rpt_note_subs: list[dict] = []


def main() -> int:
    if len(sys.argv) < 2:
        jsonl = list((ROOT / "tools" / "mediacrawler" / "data" / "xhs" / "jsonl").glob("detail_comments_*.jsonl"))
        if not jsonl:
            print("[ERROR] 未找到 detail_comments_*.jsonl，请先运行 mc_xhs_comments.py")
            return 1
        jsonl_path = max(jsonl, key=lambda p: p.stat().st_mtime)
    else:
        jsonl_path = Path(sys.argv[1])
    global rpt_note_subs
    comments = load_comments(jsonl_path)
    rpt_note_subs = [c for c in comments if c.get("parent_comment_id")]
    note_id = jsonl_path.stem.split("_")[-1].split(".")[0] if "detail_comments" in jsonl_path.name else "unknown"
    rpt = build_report(None, comments)
    out_prefix = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "workbuddy" / f"xhs_comment_report_{note_id}"
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    (out_prefix.with_suffix(".md")).write_text(to_markdown(rpt), encoding="utf-8")
    (out_prefix.with_suffix(".json")).write_text(json.dumps(rpt, ensure_ascii=False, indent=2), encoding="utf-8")
    s = rpt["stats"]
    print(f"报告已生成: {out_prefix.with_suffix('.md')}")
    print(f"  评论 {s['评论总数']}（父 {s['父评论']}/子 {s['子评论回复']}）｜唯一用户 {s['唯一用户数']}｜图片评论 {s['图片评论数']}｜最高赞 {s['最高点赞']}")
    print(f"  关键词TOP: {[w for w,_ in s['关键词TOP'][:5]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
