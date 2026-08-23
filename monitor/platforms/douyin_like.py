"""TikTokDownloader 适配器占位（P2 完整实现：发布/喜欢/收藏增量，GPL 进程隔离）。

K8/K9：扫码登录已失效需手动粘贴 cookie；喜欢/收藏仅返回发布日期，需全量拉取再筛选。
P2 通过 Web API（port 5555）或 CLI 子进程调用，本类仅定义接口契约。
"""
from __future__ import annotations


class TikTokDownloaderAdapter:
    def __init__(self, base_url: str = "", cli_path: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.cli_path = cli_path

    def available(self) -> bool:
        """P2 由 spike#1 确认 Web API 契约后实现为 True。"""
        return False

    def poll_posts(self, max_pages: int = 1) -> list[dict]:
        raise NotImplementedError("TikTokDownloader 发布/喜欢/收藏适配器为 P2 范围")

    def poll_likes(self, max_pages: int = 1) -> list[dict]:
        raise NotImplementedError("TikTokDownloader 点赞适配器为 P2 范围")

    def poll_favorites(self, max_pages: int = 1) -> list[dict]:
        raise NotImplementedError("TikTokDownloader 收藏适配器为 P2 范围")
