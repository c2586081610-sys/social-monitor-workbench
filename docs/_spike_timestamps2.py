# -*- coding: utf-8 -*-
"""T5 spike round2: paraformer + vad + punc + pred_timestamp + sentence_timestamp。"""
import json
import sys
import time
from pathlib import Path

WAV = sys.argv[1] if len(sys.argv) > 1 else "media/_e2e/test480.wav"

PARAFORMER = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

out = {"wav": WAV, "cases": []}
from funasr import AutoModel

t0 = time.time()
print("loading...", flush=True)
model = AutoModel(
    model=PARAFORMER,
    vad_model=VAD,
    punc_model=PUNC,
    device="cpu",
    disable_update=True,
)
print(f"loaded in {time.time()-t0:.1f}s", flush=True)

for name, gen_kwargs in [
    ("B1_pred_ts_only", {"pred_timestamp": True}),
    ("B2_pred_ts_sentence_ts", {"pred_timestamp": True, "sentence_timestamp": True}),
]:
    print(f"[{name}] generating...", flush=True)
    t1 = time.time()
    res = model.generate(input=WAV, **gen_kwargs)
    dt = time.time() - t1
    item = res[0]
    case = {
        "name": name,
        "gen_s": round(dt, 1),
        "keys": list(item.keys()),
        "text_len": len(item.get("text") or ""),
    }
    ts = item.get("timestamp")
    if isinstance(ts, list):
        case["timestamp_count"] = len(ts)
        case["timestamp_first5"] = ts[:5]
        if ts:
            case["timestamp_ms_range"] = [ts[0][0], ts[-1][1]]
    si = item.get("sentence_info")
    if isinstance(si, list):
        case["sentence_info_count"] = len(si)
        case["sentence_info_summary"] = [
            {"start": s.get("start"), "end": s.get("end"), "len": len(s.get("text") or ""), "ts_n": len(s.get("timestamp") or [])}
            for s in si[:6]
        ]
    out["cases"].append(case)
    print(json.dumps(case, ensure_ascii=False, indent=2), flush=True)

(Path(__file__).parent / "_spike_timestamps_result2.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("WROTE result2", flush=True)
