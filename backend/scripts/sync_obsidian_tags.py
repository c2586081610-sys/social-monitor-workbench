"""Obsidian 笔记标签回填工具（幂等，可重复执行）。

扫描 settings.obsidian_root/**/*.md，解析 frontmatter 的 tags 写入数据库：
1. tags 表：标签去 # 落库（name 唯一，重复跳过），kind=small。
2. work_tags 表：按 works.note_path 匹配作品后建立关联（已存在则跳过）。

用法：
    python backend/scripts/sync_obsidian_tags.py

frontmatter tags 兼容两种形态：
    tags: ["#健身", "#碳水循环"]          # 内联数组
    tags:                                 # 块状列表
      - "#健身"
      - "#碳水循环"
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import yaml  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402
from app.models import Tag, Work, WorkTag  # noqa: E402
from app.repositories import tag_repo  # noqa: E402


def extract_tags(frontmatter: dict | None) -> list[str]:
    """提取 frontmatter.tags 为去 # 的标签名列表（兼容 list/str/None）。"""
    if not frontmatter:
        return []
    raw = frontmatter.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    names: list[str] = []
    for item in raw:
        if not item:
            continue
        name = str(item).strip().lstrip("#").strip()
        if name:
            names.append(name)
    return names


def read_frontmatter(path: Path) -> dict | None:
    """读取 Markdown 开头 --- 围栏的 frontmatter；无围栏或解析失败返回 None。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return None
    try:
        payload = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return None
    return payload if isinstance(payload, dict) else None


def _strip_obsidian_prefix(p: str) -> str:
    """把 'Obsidian/健身/xxx.md' 规范化为相对 Obsidian 根路径 '健身/xxx.md'。"""
    p = p.replace("\\", "/")
    p = p.lstrip("./")
    if p.startswith("Obsidian/"):
        p = p[len("Obsidian/"):]
    return p


def main() -> int:
    init_db()
    stats = {
        "files": 0,
        "tagged_files": 0,
        "tags_new": 0,
        "linked": 0,
        "skipped": 0,
    }
    root = settings.obsidian_root
    with SessionLocal() as db:
        # 索引 works.note_path（兼容含 Obsidian/ 前缀与相对路径两种写法）
        works = db.execute(select(Work).where(Work.note_path.isnot(None))).scalars().all()
        by_note: dict[str, Work] = {}
        for w in works:
            raw = w.note_path.replace("\\", "/")
            by_note.setdefault(raw, w)
            by_note.setdefault(_strip_obsidian_prefix(raw), w)

        for path in sorted(root.rglob("*.md")):
            stats["files"] += 1
            names = extract_tags(read_frontmatter(path))
            if not names:
                continue
            stats["tagged_files"] += 1

            tag_ids: list[int] = []
            for name in names:
                tag = tag_repo.get_by_name(db, name)
                if tag is None:
                    tag = tag_repo.create(db, name, kind="small")
                    stats["tags_new"] += 1
                tag_ids.append(tag.id)

            rel = path.relative_to(root).as_posix()
            work = by_note.get(rel) or by_note.get(str(path.resolve().as_posix()))
            if work is None:
                continue
            for tag_id in tag_ids:
                exists = db.execute(
                    select(WorkTag).where(WorkTag.work_id == work.id, WorkTag.tag_id == tag_id)
                ).first()
                if exists is not None:
                    stats["skipped"] += 1
                    continue
                tag_repo.link_work(db, work.id, tag_id)
                stats["linked"] += 1
        db.commit()

        tag_total = db.execute(select(func.count()).select_from(Tag)).scalar_one()
        work_tag_total = db.execute(select(func.count()).select_from(WorkTag)).scalar_one()

    print(
        f"扫描 {stats['files']} 个笔记，{stats['tagged_files']} 个含标签；"
        f"新建标签 {stats['tags_new']}，新建关联 {stats['linked']}，跳过 {stats['skipped']}；"
        f"tags 表共 {tag_total} 行，work_tags 表共 {work_tag_total} 行。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
