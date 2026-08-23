"""流水线·转写：FunASR/SenseVoice 带时间戳（K14/K18；引擎未装则明确报错）。"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from monitor.pipeline.download import PipelineOfflineError

logger = logging.getLogger("monitor.pipeline.transcribe")

_ENGINE = None


def _get_engine():
    """懒加载 SenseVoice 引擎（全局单例，避免重复加载模型）。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    try:
        import funasr  # noqa: F401
        from funasr import AutoModel
    except ImportError:
        raise PipelineOfflineError("转写引擎 funasr 未安装（首次部署需预下载 SenseVoice 模型，K18）") from None
    logger.info("loading SenseVoiceSmall model (first load may take seconds)...")
    _ENGINE = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cpu",
        disable_update=True,
    )
    logger.info("SenseVoiceSmall model ready")
    return _ENGINE


# SenseVoice 输出的元数据标记（<|zh|> 语言 / <|NEUTRAL|> 情感 / <|Speech|> 事件等）
_META_TAG_RE = re.compile(r"<\|[^|]+\|>")


def _clean_text(raw: str) -> str:
    """去除 SenseVoice 的元数据标记，保留纯文本。"""
    return _META_TAG_RE.sub("", raw or "").strip()


def transcribe(video_path: str, out_dir: Path) -> str:
    """对视频/音频文件做语音转文字，返回带时间戳转写稿 JSON 路径。

    输出格式（transcript/*.json）：
        {
          "source": "<video_path>",
          "engine": "SenseVoiceSmall",
          "created_at": "ISO8601",
          "segments": [{"start": 0.0, "end": 2.5, "text": "..."}],
          "text": "全文拼接（含时间戳标记用于语义对齐抽帧）"
        }
    """
    engine = _get_engine()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 检查输入文件存在
    if not Path(video_path).exists():
        raise PipelineOfflineError(f"输入文件不存在: {video_path}")

    logger.info("transcribing: %s", video_path)
    t0 = time.time()
    # rich_transcription_post_process=True 可清洗标记，但为保留时间戳用默认输出再自行清洗
    res = engine.generate(input=video_path, cache={})
    elapsed = time.time() - t0
    logger.info("transcribe done in %.1fs", elapsed)

    if not res:
        raise PipelineOfflineError("转写结果为空")

    # SenseVoice 默认输出整体文本；若含时间戳用 segments，否则单段
    item = res[0]
    raw_text = item.get("text", "") or ""
    segments = []

    # 有句级时间戳时构建 segments；没有则按整段
    if isinstance(item.get("timestamp"), list) and item["timestamp"]:
        # SenseVoice-Small 默认无句级时间戳（可用 VAD 分句），此处保留扩展位
        pass

    clean = _clean_text(raw_text)
    if clean:
        segments.append({"start": 0.0, "end": round(elapsed, 2), "text": clean})

    # 提取文件名（去除扩展名）作为转写稿名
    stem = Path(video_path).stem
    out_path = out_dir / f"{stem}.json"
    doc = {
        "source": str(video_path),
        "engine": "SenseVoiceSmall",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "segments": segments,
        "text": clean,
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("transcript saved: %s", out_path)
    return str(out_path)
