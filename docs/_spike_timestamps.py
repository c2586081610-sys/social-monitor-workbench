# -*- coding: utf-8 -*-
"""T5 spike: 验证 paraformer-zh + vad + punc 能否输出句级时间戳 sentence_info。

用法: python docs/_spike_timestamps.py <wav_path>
输出 JSON: docs/_spike_timestamps_result.json
"""
import json
import sys
import time
from pathlib import Path

WAV = sys.argv[1] if len(sys.argv) > 1 else "media/_e2e/test480.wav"

PARAFORMER = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

out = {"wav": WAV, "cases": []}


def run_case(name: str, model_kwargs: dict, gen_kwargs: dict):
    from funasr import AutoModel

    t0 = time.time()
    print(f"[{name}] loading model...", flush=True)
    model = AutoModel(disable_update=True, **model_kwargs)
    t_load = time.time() - t0
    print(f"[{name}] loaded in {t_load:.1f}s, generating...", flush=True)
    t1 = time.time()
    res = model.generate(input=WAV, **gen_kwargs)
    t_gen = time.time() - t1
    item = res[0]
    keys = list(item.keys())
    print(f"[{name}] keys={keys}", flush=True)
    case = {
        "name": name,
        "load_s": round(t_load, 1),
        "gen_s": round(t_gen, 1),
        "keys": keys,
        "text_len": len(item.get("text") or ""),
    }
    if isinstance(item.get("timestamp"), list):
        case["timestamp_count"] = len(item["timestamp"])
        case["timestamp_first5"] = item["timestamp"][:5]
    si = item.get("sentence_info")
    if isinstance(si, list):
        case["sentence_info_count"] = len(si)
        case["sentence_info_first"] = si[0] if si else None
    out["cases"].append(case)
    print(json.dumps(case, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    # A1: paraformer + vad + punc, generate(sentence_timestamp=True)
    run_case(
        "A1_paraformer_vad_punc_sentence_timestamp",
        {"model": PARAFORMER, "vad_model": VAD, "punc_model": PUNC, "device": "cpu"},
        {"sentence_timestamp": True},
    )
    # A2: 同上但不传 sentence_timestamp（验证默认是否也有）
    run_case(
        "A2_paraformer_vad_punc_default",
        {"model": PARAFORMER, "vad_model": VAD, "punc_model": PUNC, "device": "cpu"},
        {},
    )
    # A3: paraformer + vad，无 punc（字符级 timestamp 是否可用）
    run_case(
        "A3_paraformer_vad_no_punc",
        {"model": PARAFORMER, "vad_model": VAD, "device": "cpu"},
        {"sentence_timestamp": True},
    )

    result_path = Path(__file__).parent / "_spike_timestamps_result.json"
    result_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {result_path}", flush=True)
