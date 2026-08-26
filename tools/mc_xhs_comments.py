"""MediaCrawler 小红书评论采集封装：读项目 cookie，调用 MediaCrawler detail 模式抓全量评论（含回复）。

用法: python tools/mc_xhs_comments.py <note_url|note_id> [更多note...]
输出: tools/mediacrawler/data/xhs/jsonl/detail_comments_*.jsonl（评论） + detail_contents_*.jsonl（笔记内容）
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC_DIR = ROOT / "tools" / "mediacrawler"
MC_PY = MC_DIR / ".venv" / "Scripts" / "python.exe"
COOKIE_CFG = ROOT / "config" / "platform_cookies.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python mc_xhs_comments.py <note_url|note_id> [more...]")
        return 1
    ids = sys.argv[1:]
    # 读取项目 cookie
    cfg = json.loads(COOKIE_CFG.read_text(encoding="utf-8"))
    ck = cfg.get("xhs", {}).get("cookie", "")
    if not ck:
        print("[ERROR] config/platform_cookies.json 缺少 xhs.cookie（先跑 capture_xhs_login.py 登录）")
        return 1

    cmd = [
        str(MC_PY), "main.py",
        "--platform", "xhs",
        "--lt", "cookie",
        "--type", "detail",
        "--specified_id", ",".join(ids),
        "--get_comment", "yes",
        "--get_sub_comment", "yes",
        "--cookies", ck,
        "--save_data_option", "jsonl",
        "--headless", "yes",
    ]
    print("[MediaCrawler] 采集:", ids)
    # 清理旧的当日 jsonl（避免覆盖已存在文件被文件保护拦截）
    import datetime
    today = datetime.date.today().isoformat()
    out_dir = MC_DIR / "data" / "xhs" / "jsonl"
    if out_dir.exists():
        for f in out_dir.glob(f"*{today}*.jsonl"):
            try:
                f.unlink()
            except OSError:
                pass
    result = subprocess.run(cmd, cwd=str(MC_DIR))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
