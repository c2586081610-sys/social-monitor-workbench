"""ORM 模型：一表一文件（SPEC §3.4 点名文件）。

统一在此导入，确保 Base.metadata 注册全部表（create_all 依赖）。
"""
from app.models.cookie import CookieHealth
from app.models.creator import Creator
from app.models.group import Group
from app.models.lexicon import LexiconEntry
from app.models.poll_log import PollLog
from app.models.tag import Tag
from app.models.task import Task
from app.models.work import Work
from app.models.work_tag import WorkTag

__all__ = [
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
