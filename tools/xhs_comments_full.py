"""小红书单笔记全量评论抓取：分批续抓 + 随机间隔 + 风控(461)检测。

策略：
  1. 每轮调用 mc_xhs_comments.py（MediaCrawler detail，浏览器有头，间隔已调 6s）
  2. 轮间随机等待（10-40s 正常 / 120-300s 遇风控）
  3. 评论数不增长 = 触发风控(461)/token 过期 → 长等待后重试
  4. 达到目标数或连续 N 轮无进展 → 结束

用法: python tools/xhs_comments_full.py <note_url> [目标评论数] [最大轮数]
"""
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC = ROOT / "tools" / "mc_xhs_comments.py"
NOTE_ID = "6a699ba30000000001000a87"


def count_comments(note_id: str) -> int:
    """从 MediaCrawler jsonl 统计该笔记去重评论数。"""
    seen = set()
    for f in (ROOT / "tools" / "mediacrawler" / "data" / "xhs" / "jsonl").glob("detail_comments_*.jsonl"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("note_id") == note_id:
                    seen.add(d.get("comment_id"))
        except Exception:
            pass
    return len(seen)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python xhs_comments_full.py <note_url> [目标数=544] [最大轮数=20]")
        return 1
    url = sys.argv[1]
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 544
    max_rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    prev = count_comments(NOTE_ID)
    print(f"[全量抓取] 起始评论数: {prev} | 目标: {target}")
    no_progress = 0
    for r in range(1, max_rounds + 1):
        print(f"\n=== 第 {r}/{max_rounds} 轮 ===")
        result = subprocess.run([sys.executable, str(MC), url], capture_output=True, text=True, timeout=480)
        now = count_comments(NOTE_ID)
        gained = now - prev
        if gained > 0:
            print(f"[进展] {prev} → {now} (+{gained})")
            prev = now
            no_progress = 0
            if now >= target:
                print(f"✅ 达到目标 {target} 条，结束")
                break
            wait = random.randint(10, 40)
        else:
            no_progress += 1
            print(f"[风控/无进展] 仍是 {now}（连续 {no_progress} 轮）")
            if no_progress >= 4:
                print("连续 4 轮无进展，可能 token 过期或风控封锁，停止。请刷新页面获取新链接后重跑。")
                break
            wait = random.randint(120, 300)
        print(f"随机等待 {wait}s（风控防护）...")
        time.sleep(wait)
    print(f"\n完成，最终评论数: {count_comments(NOTE_ID)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
