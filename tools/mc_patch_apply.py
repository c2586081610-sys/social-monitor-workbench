"""MediaCrawler DIY 补丁应用脚本（幂等）：给 store 落盘字段补 ip_location（IP属地统计用）。

用法: python tools/mc_patch_apply.py
效果: tools/mediacrawler/store/xhs/__init__.py 的 update_xhs_note_comment 增加 ip_location 字段
      （clone MediaCrawler 后运行一次即可；重跑安全，已打则跳过）
"""
from pathlib import Path

MC_STORE = Path(__file__).resolve().parent.parent / "tools" / "mediacrawler" / "store" / "xhs" / "__init__.py"

ANCHOR = '        "like_count": comment_item.get("like_count", 0),\n'
PATCH = '        "like_count": comment_item.get("like_count", 0),\n        "ip_location": comment_item.get("ip_location", ""),  # 本地DIY增强：IP属地（统计用，非身份信息）\n'


def main() -> int:
    if not MC_STORE.exists():
        print(f"[ERROR] 未找到 MediaCrawler store: {MC_STORE}")
        return 1
    src = MC_STORE.read_text(encoding="utf-8")
    if "ip_location" in src:
        print("[OK] 补丁已存在（幂等跳过）")
        return 0
    if ANCHOR not in src:
        print("[ERROR] 未找到锚点（MediaCrawler 版本可能已变更），请手动核对 store/xhs/__init__.py")
        return 1
    src = src.replace(ANCHOR, PATCH, 1)
    MC_STORE.write_text(src, encoding="utf-8")
    print(f"[OK] 已应用补丁: {MC_STORE}")
    print("     新增字段: ip_location（评论IP属地，供 mc_comment_report.py 统计）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
