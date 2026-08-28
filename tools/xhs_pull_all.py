"""小红书博主作品批量扒取：自动遍历博主所有笔记，逐个调 MediaCrawler detail 模式拉内容+全量评论。

流程：
  1. 用 tools/xhs_fetch_notes.py 拉博主笔记列表（note_id + xsec_token + time）
  2. 按发布时间倒序（最新在前）排列
  3. 逐篇构造带 xsec_token 的 URL → subprocess 调 mc_xhs_comments.py（MediaCrawler detail）
  4. 风控保护：每篇间隔 + 失败跳过 + 断点续传（已拉过的 note_id 自动跳过）

用法:
  python tools/xhs_pull_all.py <博主主页URL> [--limit N] [--interval S]
  示例:
  python tools/xhs_pull_all.py "https://www.xiaohongshu.com/user/profile/61ab7f700000000010004c16" --limit 5
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC_COMMENTS = ROOT / "tools" / "mc_xhs_comments.py"
PYTHON = sys.executable
NOTES_FILE = ROOT / "workbuddy" / "xhs_notes_latest.json"
COMMENTS_DIR = ROOT / "tools" / "mediacrawler" / "data" / "xhs" / "jsonl"


def _to_sec(v) -> int:
    try:
        i = int(v)
        return i // 1000 if i > 10**12 else i
    except (TypeError, ValueError):
        return 0


def _load_existing_note_ids() -> set[str]:
    """断点续传：从已有 jsonl 里收集已拉过的 note_id。"""
    ids: set[str] = set()
    if not COMMENTS_DIR.exists():
        return ids
    for f in COMMENTS_DIR.glob("detail_comments_*.jsonl"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                nid = d.get("note_id") or ""
                if nid:
                    ids.add(nid)
        except (OSError, json.JSONDecodeError):
            continue
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description="小红书博主作品批量扒取（内容+全量评论）")
    ap.add_argument("profile_url", help="博主主页 URL")
    ap.add_argument("--limit", type=int, default=0, help="最多扒取 N 篇（0=全部）")
    ap.add_argument("--interval", type=int, default=12, help="每篇间隔秒数（风控保护，默认 12s）")
    ap.add_argument("--force", action="store_true", help="忽略断点续传，重新拉取")
    args = ap.parse_args()

    # 1. 拉笔记列表
    print("[1] 拉取博主笔记列表...")
    subprocess.run([PYTHON, str(ROOT / "tools" / "xhs_fetch_notes.py"), args.profile_url, str(NOTES_FILE)],
                   timeout=180)
    notes = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    notes.sort(key=lambda n: _to_sec(n.get("time")), reverse=True)  # 最新在前
    print(f"[1] 共 {len(notes)} 篇（按发布时间倒序）")

    # 2. 过滤已拉过的（断点续传）
    existing = set() if args.force else _load_existing_note_ids()
    todo = [n for n in notes if n.get("note_id") not in existing]
    if args.limit > 0:
        todo = todo[: args.limit]
    print(f"[2] 待扒取 {len(todo)} 篇（已跳过 {len(notes) - len(todo)} 篇）")

    # 3. 逐篇扒取
    ok, fail = 0, 0
    for idx, n in enumerate(todo, 1):
        nid = n.get("note_id") or ""
        xsec = n.get("xsec_token") or ""
        url = f"https://www.xiaohongshu.com/explore/{nid}"
        if xsec:
            url += f"?xsec_token={xsec}&xsec_source=pc_feed"
        title = (n.get("title") or "")[:24]
        print(f"[3] [{idx}/{len(todo)}] {nid} | {title}")
        try:
            r = subprocess.run(
                [PYTHON, str(MC_COMMENTS), url],
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                ok += 1
                print(f"     ✅ 完成")
            else:
                fail += 1
                print(f"     ⚠️ 失败 rc={r.returncode} {r.stderr[-200:]}")
        except subprocess.TimeoutExpired:
            fail += 1
            print("     ⚠️ 超时")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"     ⚠️ 异常: {e!r}")
        if idx < len(todo):
            time.sleep(args.interval)  # 风控间隔

    print(f"\n完成：成功 {ok} 篇，失败 {fail} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
