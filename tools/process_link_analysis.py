"""运行一条手动链接分析作品，不扫描或处理全局队列。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor import jobs  # noqa: E402
from monitor.store.shared_db import init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="处理一条手动视频链接分析")
    parser.add_argument("--work-id", type=int, required=True)
    args = parser.parse_args()
    if args.work_id < 1:
        parser.error("--work-id 必须为正整数")
    init_db()
    try:
        result = jobs.process_link_analysis(args.work_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
