"""ORM 模型：一表一文件（SPEC §3.4 点名文件）。

统一在此导入，确保 Base.metadata 注册全部表（create_all 依赖）。
"""
from app.models.cookie import CookieHealth
from app.models.creator import Creator
from app.models.archive_entry import ArchiveEntry
from app.models.archive_job import ArchiveJob
from app.models.archive_revision import ArchiveRevision
from app.models.group import Group
from app.models.lexicon import LexiconEntry
from app.models.poll_log import PollLog
from app.models.tag import Tag
from app.models.task import Task
from app.models.work import Work
from app.models.work_tag import WorkTag

__all__ = [
    "ArchiveEntry",
    "ArchiveJob",
    "ArchiveRevision",
    "CookieHealth",
    "Creator",
    "Group",
    "LexiconEntry",
    "PollLog",
    "Tag",
    "Task",
    "Work",
    "WorkTag",
]
