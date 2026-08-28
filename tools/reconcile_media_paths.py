"""媒体路径回填工具：把本地已下载但未关联的作品目录，自动匹配并回填 works.media_path。

两种模式：
1. 正式目录匹配：media/{分组}/{博主}/{日期}-{标题}/ → 按 标题+日期 匹配 works（media_path 为空）
2. 测试目录迁移：media/_test_xhs/note_{note_id}/ → 按 external_id 精确匹配 → 移动到
   media/{分组}/{博主}/{日期}-{标题}/ 并回填（完成后原测试目录清空）

用法: python tools/reconcile_media_paths.py [--dry-run]
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"


def _norm(s: str) -> str:
    """标题归一化：去 #标签、标点、空白、全半角（用于目录名匹配）。"""
    s = re.sub(r"#\S+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s.lower()


def _title_key(dirname: str) -> str:
    """目录名 {日期}-{标题} → 标题 key（去日期前缀）。"""
    name = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", dirname)
    return _norm(name)


def _date_key(work_date: str | None) -> str | None:
    return work_date[:10] if work_date else None


def _collect_formal_dirs() -> dict[str, list[Path]]:
    """扫描 media/{分组}/{博主}/{日期}-{标题}/，按标题 key 建索引（排除特殊目录）。"""
    SKIP = {"cover", "_test_xhs", "_e2e", "_work", "美国50ETF平替"}
    index: dict[str, list[Path]] = {}
    if not MEDIA.exists():
        return index
    for p in MEDIA.iterdir():
        if not p.is_dir() or p.name in SKIP:
            continue
        for creator in p.iterdir():
            if not creator.is_dir():
                continue
            for work_dir in creator.iterdir():
                if not work_dir.is_dir():
                    continue
                key = _title_key(work_dir.name)
                if key:
                    index.setdefault(key, []).append(work_dir)
    return index


def main() -> int:
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(str(ROOT / "aggregator.db"))
    works = conn.execute(
        "SELECT id, title, published_at, platform FROM works WHERE media_path IS NULL OR media_path = ''"
    ).fetchall()
    print(f"待回填 works: {len(works)} 条")

    index = _collect_formal_dirs()
    updated = 0
    for wid, title, published_at, platform in works:
        key = _norm(title)
        if not key:
            continue
        cands = index.get(key) or []
        if not cands:
            continue
        # 优先日期匹配
        dkey = _date_key(published_at)
        picked = next((d for d in cands if dkey and dkey in d.name), cands[0])
        rel = picked.relative_to(MEDIA).as_posix()
        if not dry:
            conn.execute("UPDATE works SET media_path=? WHERE id=?", (rel, wid))
        print(f"  work#{wid} {title[:20]} → {rel}")
        updated += 1
    if not dry:
        conn.commit()

    # 模式 2：_test_xhs 迁移（note_{note_id} → external_id）
    test_dir = MEDIA / "_test_xhs"
    if test_dir.exists():
        print("--- 测试目录迁移 ---")
        for d in sorted(test_dir.iterdir()):
            if not d.is_dir():
                continue
            m = re.match(r"note_([0-9a-f]+)", d.name)
            if not m:
                continue
            row = conn.execute(
                "SELECT id, title, published_at, media_path FROM works WHERE platform='xhs' AND external_id LIKE ? ORDER BY LENGTH(external_id) DESC LIMIT 1",
                (m.group(1) + "%",),
            ).fetchone()
            if not row:
                print(f"  {d.name}: 无匹配作品，跳过")
                continue
            wid, title, published_at, exist_mp = row
            if exist_mp:
                print(f"  work#{wid} {d.name}: 已关联 {exist_mp}，跳过（残留目录待清理）")
                continue
            dkey = _date_key(published_at) or "unknown"
            dst = MEDIA / "财经" / "长宁辛吉德" / f"{dkey}-{title[:40]}"
            dst = dst.with_name(re.sub(r"[\\/:*?\"<>|]", "", dst.name))
            if dry:
                print(f"  work#{wid} {d.name} → 将迁移到 {dst.relative_to(MEDIA)}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            moved = 0
            for f in d.rglob("*"):  # 递归（兼容 note_xxx/real_images/ 嵌套结构）
                if not f.is_file():
                    continue
                try:
                    shutil.move(str(f), str(dst / f.name))
                    moved += 1
                except OSError as e:
                    print(f"    文件 {f.name} 移动失败: {str(e)[:60]}")
            if moved:
                conn.execute("UPDATE works SET media_path=? WHERE id=?", (dst.relative_to(MEDIA).as_posix(), wid))
            try:
                shutil.rmtree(d)
            except OSError:
                pass
            print(f"  work#{wid} {title[:20]} → {dst.relative_to(MEDIA)}（{moved} 文件）")
        if not dry:
            conn.commit()

    conn.close()
    print(f"{'[DRY-RUN] ' if dry else ''}回填完成，更新 {updated} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
