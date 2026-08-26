"""配置加载：全部来自环境变量，禁止硬编码路径。

默认工作区根 = backend 的父目录（承载 media/ Obsidian/ aggregator.db workbuddy/）。
"""
import os
from pathlib import Path


def _workspace_root() -> Path:
    # config.py 位于 {工作区根}/backend/app/core/config.py → 上溯 3 层为工作区根
    return Path(__file__).resolve().parents[3]


def _env_path(name: str, default: Path) -> Path:
    val = os.getenv(name)
    return Path(val).resolve() if val else default


class Settings:
    """应用配置单例。实例化时机 = 模块导入时（测试须先设 env 再导入）。"""

    def __init__(self) -> None:
        ws = _workspace_root()
        self.workspace_root: Path = ws
        # tools/bin 注入 PATH 前部：ffmpeg / yutto / yt-dlp / xhs 下载器子进程依赖（Windows CreateProcess 不解析 .cmd，
        # 但 shutil.which/ffmpeg 子进程需能直接找到 exe；.cmd 由 download.py 改用 python -m 调用规避）
        _tools_bin = ws / "tools" / "bin"
        if _tools_bin.exists():
            os.environ["PATH"] = str(_tools_bin) + os.pathsep + os.environ.get("PATH", "")
        # 认证
        self.admin_token: str = os.getenv("ADMIN_TOKEN", "dev-admin-token-change-me")
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if o.strip()
        ]
        # 存储
        self.database_path: Path = _env_path("DATABASE_PATH", ws / "aggregator.db")
        self.media_root: Path = _env_path("MEDIA_ROOT", ws / "media")
        self.obsidian_root: Path = _env_path("OBSIDIAN_ROOT", ws / "Obsidian")
        self.workbuddy_dir: Path = _env_path("WORKBUDDY_DIR", ws / "workbuddy")
        self.pending_dir: Path = self.workbuddy_dir / "pending"
        self.trigger_dir: Path = self.workbuddy_dir / "triggers"
        self.monitor_heartbeat_file: Path = self.workbuddy_dir / "monitor_heartbeat.json"
        self.monitor_heartbeat_timeout: int = int(os.getenv("MONITOR_HEARTBEAT_TIMEOUT", "60"))
        # 外部服务（监控层健康探测；留空视为未配置）
        self.rsshub_base_url: str = os.getenv("RSSHUB_BASE_URL", "").rstrip("/")
        self.changedetection_url: str = os.getenv("CHANGEDETECTION_URL", "").rstrip("/")
        # 监控层调度
        self.poll_rsshub_interval: int = int(os.getenv("POLL_RSSHUB_INTERVAL", "300"))
        self.poll_douyin_interval: int = int(os.getenv("POLL_DOUYIN_INTERVAL", "600"))
        self.poll_trigger_interval: int = int(os.getenv("POLL_TRIGGER_INTERVAL", "10"))
        self.heartbeat_interval: int = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
        self.monitor_run_pipeline: bool = os.getenv("MONITOR_RUN_PIPELINE", "false").lower() == "true"
        self.douyin_cdp_enabled: bool = os.getenv("ENABLE_DOUYIN_CDP", "false").lower() == "true"
        self.douyin_cdp_profile_dir: str = os.getenv("DOUYIN_CDP_PROFILE_DIR", "")
        # 流水线
        self.downloader_bin: str = os.getenv("DOWNLOADER_BIN", "")
        self.transcriber_engine: str = os.getenv("TRANSCRIBER_ENGINE", "")
        self.fernet_key: str = os.getenv("FERNET_KEY", "")


settings = Settings()
