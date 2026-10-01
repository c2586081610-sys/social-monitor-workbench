"""配置加载：全部来自环境变量，禁止硬编码路径。

默认工作区根 = backend 的父目录（承载 media/ Obsidian/ aggregator.db workbuddy/）。

.env 加载：模块导入时读取 {backend}/.env（仅补缺失键，系统环境变量优先）。
"""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

# config.py 位于 {工作区根}/backend/app/core/config.py → parents[2] 即 backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(_BACKEND_DIR / ".env", override=False)


def _workspace_root() -> Path:
    # config.py 位于 {工作区根}/backend/app/core/config.py → 上溯 3 层为工作区根
    return Path(__file__).resolve().parents[3]


def _env_path(name: str, default: Path) -> Path:
    val = os.getenv(name)
    return Path(val).resolve() if val else default


_ARCHIVE_ROOT_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
ARCHIVE_PLATFORM_LABELS: dict[str, str] = {
    "douyin": "抖音",
    "bilibili": "哔哩哔哩",
    "xhs": "小红书",
    "twitter": "Twitter/X",
    "wechat": "微信公众号",
}
ARCHIVE_DIRECTORY_TEMPLATE = "{published_at}_{platform}_{title}_{external_id}"
ARCHIVE_INFORMATION_FILES = ("作品信息.csv", "作品信息.json", "作品信息.md")
ARCHIVE_COLLECTION_FILE = "合集清单.csv"
ARCHIVE_CATALOG_FILE = "归档总清单.csv"


def _archive_root_paths(media_root: Path, workspace_root: Path) -> dict[str, Path]:
    """Load server-only root mappings; paths never enter public policy responses."""
    roots = {"media": media_root, "fitness": workspace_root / "健身"}
    raw = os.getenv("ARCHIVE_ROOTS", "").strip()
    if not raw:
        return roots
    try:
        configured = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("ARCHIVE_ROOTS must map root keys to paths as a JSON object") from exc
    if not isinstance(configured, dict):
        raise ValueError("ARCHIVE_ROOTS must map root keys to paths as a JSON object")
    for key, value in configured.items():
        if not isinstance(key, str) or not _ARCHIVE_ROOT_KEY.fullmatch(key):
            raise ValueError(f"Invalid archive root key: {key!r}")
        if key == "media":
            # MEDIA_ROOT is the only source of the project-generated media root.
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Archive root {key!r} must map to a non-empty path")
        roots[key] = Path(value).expanduser().resolve()
    return roots


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
        # These machine-local mappings are never returned as absolute paths by the API.
        self.archive_root_paths: dict[str, Path] = _archive_root_paths(self.media_root, ws)
        self.obsidian_root: Path = _env_path("OBSIDIAN_ROOT", ws / "Obsidian")
        self.workbuddy_dir: Path = _env_path("WORKBUDDY_DIR", ws / "workbuddy")
        self.pending_dir: Path = self.workbuddy_dir / "pending"
        # 后端对外可访问的 base URL（前端跨源时 cover_url 需要绝对地址）。
        # 默认 http://127.0.0.1:8000 本机即用；NAS/局域网部署时改 MEDIA_BASE_URL 环境变量
        self.media_base_url: str = os.getenv("MEDIA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        self.trigger_dir: Path = self.workbuddy_dir / "triggers"
        self.monitor_heartbeat_file: Path = self.workbuddy_dir / "monitor_heartbeat.json"
        self.monitor_heartbeat_timeout: int = int(os.getenv("MONITOR_HEARTBEAT_TIMEOUT", "60"))
        # 外部服务（监控层健康探测；留空视为未配置）
        self.rsshub_base_url: str = os.getenv("RSSHUB_BASE_URL", "").rstrip("/")
        self.changedetection_url: str = os.getenv("CHANGEDETECTION_URL", "").rstrip("/")
        # 抖音监测：MediaCrawler 目录（复用其 cookie 登录态 + DouYinClient）
        self.mediacrawler_dir: Path = _env_path("MEDIACRAWLER_DIR", ws / "tools" / "mediacrawler")
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
        self.douyin_downloader_dir: str = os.getenv("DOUYIN_DOWNLOADER_DIR", "")
        self.transcriber_engine: str = os.getenv("TRANSCRIBER_ENGINE", "")
        self.fernet_key: str = os.getenv("FERNET_KEY", "")


settings = Settings()


def archive_root_policy() -> dict[str, object]:
    """Return the public, path-free archive rules and root availability."""
    roots = []
    for key, path in sorted(settings.archive_root_paths.items()):
        try:
            configured = path.is_dir()
        except OSError:
            configured = False
        roots.append({
            "root_key": key,
            "label": "项目媒体" if key == "media" else "健身素材" if key == "fitness" else key,
            "configured": configured,
        })
    return {
        "timezone": "Asia/Shanghai",
        "directory_template": ARCHIVE_DIRECTORY_TEMPLATE,
        "information_files": list(ARCHIVE_INFORMATION_FILES),
        "collection_file_name": ARCHIVE_COLLECTION_FILE,
        "catalog_file_name": ARCHIVE_CATALOG_FILE,
        "platforms": [
            {"value": value, "label": label}
            for value, label in ARCHIVE_PLATFORM_LABELS.items()
        ],
        "roots": roots,
    }
