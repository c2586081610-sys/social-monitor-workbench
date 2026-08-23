"""文件名清洗（SPEC §8.1 硬约束）：移除非法字符、超长截断、Windows 保留名、emoji 替换。"""
from __future__ import annotations

import re

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U0000FE0F"
    "\U0000200D"
    "\U00002300-\U000023FF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF]"
)
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """清洗为跨平台安全文件名（用于目录名 / 文件名，不含扩展名场景）。"""
    if not name:
        return "untitled"
    s = _ILLEGAL.sub("_", name)
    s = _EMOJI.sub("_", s)
    s = s.strip().strip(".")
    if not s:
        return "untitled"
    stem = s[:max_len].rstrip(" .")
    upper = stem.upper()
    if upper in _RESERVED or upper.startswith("CON.") or upper.startswith("PRN.") or upper.startswith("AUX."):
        stem = "_" + stem
    return stem or "untitled"
