# 设计文档：句级时间戳方案（T5）

> 项目：四平台博主监控 + 三件套 AI 笔记
> 作者：首席架构师 高见远
> 日期：2026-08-23
> 状态：方案 A 已实测通过（本机 funasr 1.4.3，CPU）
> 关联：SPEC §8.2 语义对齐抽帧契约 / F9 / F10 / B4 / PRD AC-9 AC-10

---

## 1. 背景与问题根因

**核心特色**：语义对齐抽帧——根据转写文字稿判断重点，抽对应时间点画面。链路为：
`转写（带句级时间戳）→ 词库/规则命中 → 标记重点时间窗口 → 按窗口抽帧 → frame_manifest.json`。

**当前问题**：转写引擎（`monitor/pipeline/transcribe.py`）使用 `iic/SenseVoiceSmall`，且 `generate()` 未传任何时间戳参数，导致输出退化单段（无起止时间），词库命中只能定位"整段"，语义对齐抽帧无法成立。

### 根因定位（实测确认，2026-08-23）

| 引擎/参数 | 输出 | 结论 |
|-----------|------|------|
| SenseVoiceSmall + 无参数 | `key/text` 单段 | **SenseVoice 不支持字符级时间戳**（funasr 源码 auto_model.py 注释明确：`No timestamps in ASR result (e.g. SenseVoice)`） |
| paraformer-zh + vad + punc，未传 `pred_timestamp` | `key/text` + `sentence_info`（4 段 VAD 级，timestamp 空） | **paraformer 默认不输出时间戳**，需显式 `pred_timestamp=True`（源码 model.py:558 `kwargs.get("pred_timestamp", False)`）；无时间戳时 sentence_info 降级为 VAD 段 |
| paraformer-zh + vad + punc + `pred_timestamp=True, sentence_timestamp=True` | `key/text` + `timestamp`（420 个字符级 [ms,ms]）+ `sentence_info`（**37 句精确句级时间戳**） | **方案 A 可行**，即"转写 + 句级时间戳"一次调用完成 |

**一句话根因**：当前实现选错了引擎（SenseVoice）且缺少两个关键参数（`pred_timestamp` / `sentence_timestamp`）。

---

## 2. 调研结论（funasr 1.4.3 源码 + 官方文档）

### 2.1 sentence_info 的触发条件（源码依据，`funasr/auto/auto_model.py`）

`sentence_info` 仅在 **VAD 分段推理路径**（`inference_with_vad`）中构造，触发方式两种：

1. **spk_model 自动触发**（auto_model.py:871-873）：配置 `spk_model="cam++"` 时自动置 `output_timestamp=True`、`return_time_stamps=True`，用于说话人分离场景，MVP 不需要。
2. **`sentence_timestamp=True` 显式触发**（auto_model.py:1201-1233）：调用 `generate(..., sentence_timestamp=True)`。要求：
   - `vad_model` 已配置（否则走简单路径无 sentence_info）；
   - ASR 输出字符级 `timestamp`（paraformer 需 `pred_timestamp=True`）；
   - `punc_model` 用于句子切分；若标点与时间戳对齐失败，**静默降级为 VAD 段**（`punctuation timestamps could not be aligned, falling back to VAD segments`）。

### 2.2 关键参数速查

| 参数 | 作用 | 位置 |
|------|------|------|
| `pred_timestamp=True` | paraformer 输出字符级 `timestamp`（[start_ms, end_ms]） | `generate()` 传参（源码 paraformer/model.py:558） |
| `sentence_timestamp=True` | 构造句级 `sentence_info` | `generate()` 传参（源码 auto_model.py:1201） |
| `vad_model="fsmn-vad"` | 长音频分段（sentence_info 前置） | `AutoModel(...)` 构造 |
| `punc_model="ct-punc"` | 句子切分 + 标点（句级时间戳分句依据） | `AutoModel(...)` 构造 |
| `hub="hf"` | 从 HuggingFace 拉模型（`funasr/paraformer-zh` 等已发布） | `AutoModel(...)` 构造，默认 `ms`（ModelScope） |

### 2.3 模型仓库

| 模型 | ModelScope ID | HuggingFace ID | 参数量 | 本机缓存 |
|------|---------------|----------------|--------|----------|
| ASR（paraformer-zh） | `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | `funasr/paraformer-zh` | 220M | 已缓存 |
| VAD | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`（别名 `fsmn-vad`） | `funasr/fsmn-vad` | 0.4M | 已缓存 |
| 标点 | `iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch`（别名 `ct-punc`） | `funasr/ct-punc` | 290M | 已缓存 |
| 独立时间戳预测（方案 B） | `iic/speech_timestamp_prediction-v1-16k-offline`（别名 `fa-zh`） | 见 ModelScope | 38M | 未缓存 |

---

## 3. 方案对比

| 维度 | 方案 A：paraformer 组合 | 方案 B：独立时间戳模型后处理 | 方案 C：VAD 段级降级 |
|------|------------------------|------------------------------|----------------------|
| 链路 | 一次 `generate()` 出转写+句级时间戳 | SenseVoice 转写 → `fa-zh` 对 text+audio 对齐 | VAD 分段，每段无精确时间戳 |
| 可行性 | **已实测通过** | 待实测（模型未缓存，38M 小） | **已实测**（A1/A3 降级路径） |
| 精度 | 句级毫秒；字符级 420 个/73s；官方 CIF 对齐 AAS 65-71ms | 字级 AAS 69.3ms（官方工业数据）；对文本-语音不匹配敏感 | 段级（VAD 切分粒度，说话连贯时单段可达 20-60s） |
| CPU 成本 | 加载 ~6s + 推理 RTF≈0.047（73s 音频 3.4s） | fa-zh 38M 推理快，但需额外一次推理 + 文本对齐预处理 | 最低（vad 0.4M） |
| 实现工作量 | 低（改 transcribe.py 模型+参数+输出适配，约半天） | 中（文本清洗 + 对齐后处理 + 失败回退） | 低（但精度不足，仅作兜底） |
| 依赖 | 本机已缓存 3 个模型，零新增下载 | 需下载 fa-zh（38M） | 零新增 |
| 风险 | 需监控 punc 对齐失败静默降级 | 文本与语音不匹配时预测不稳；保留 SenseVoice 情感/事件标记需额外清洗 | 不满足"语义对齐"卖点 |
| **评分（1-5）** | **5** | 3 | 2 |

> 评分依据：MVP 技术选型矩阵——学习成本、生态成熟度、部署成本、团队熟悉度优先；扩展性权重低。

**结论：推荐方案 A**。本机模型已齐、一次调用、精度满足"语义对齐"卖点；方案 B 作为 SenseVoice 转写质量增强的后备（如未来需要情感/事件标记保留）；方案 C 作为硬降级（引擎异常时保证抽帧不中断，明确标注"非语义对齐"）。

---

## 4. 方案 A 详细设计

### 4.1 调用配置

```python
from funasr import AutoModel

ASR_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"   # 或别名 "fsmn-vad"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"  # 或别名 "ct-punc"

engine = AutoModel(
    model=ASR_MODEL,
    vad_model=VAD_MODEL,
    punc_model=PUNC_MODEL,
    device="cpu",
    disable_update=True,
)

res = engine.generate(input=wav_path, pred_timestamp=True, sentence_timestamp=True)
item = res[0]
# item["text"]          全文（带标点）
# item["timestamp"]     [[start_ms, end_ms], ...] 字符级时间戳（与 text 字符一一对应，空格分隔）
# item["sentence_info"] [{start(ms), end(ms), text, timestamp}, ...] 句级时间戳
```

### 4.2 输出适配（transcript JSON）

现有 `transcript/*.json` 契约（SPEC §8.2 输入）为 `segments: [{start, end, text}]`（秒，float）。适配规则：

```python
segments = []
for s in item["sentence_info"]:
    text = (s.get("text") or "").strip()
    if not text:
        continue
    segments.append({
        "start": round(s["start"] / 1000, 3),   # ms → s
        "end": round(s["end"] / 1000, 3),
        "text": text,
    })
```

**建议（增强，非阻塞）**：transcript JSON 增加 `char_timestamps` 顶层字段（原文照存 `item["timestamp"]` + `item["sentence_info"]` 原始毫秒结构），供未来词库命中做**字符级起点定位**（B4 Backlog：命中词精确起点 → 更窄的抽帧窗口）。MVP 阶段 `segments` 已够用。

### 4.3 对现有代码的改动

| 文件 | 改动 | 工作量 |
|------|------|--------|
| `monitor/pipeline/transcribe.py` | 引擎由 SenseVoiceSmall → paraformer 组合；`generate(pred_timestamp=True, sentence_timestamp=True)`；`segments` 从 `sentence_info` 构造（ms→s）；去除 SenseVoice 元标记清洗逻辑（paraformer 无 `<|zh|>` 标记，改用 punc 标点）；`engine` 字段更新为 `paraformer-zh` | 约半天 |
| `monitor/pipeline/frames.py` | `match_windows` 已兼容 `[{start, end, text}]`，**无需改动**；建议补充"检测 sentence_info 是否降级"的告警日志 | 0.5h |
| `monitor/pipeline/transcribe.py` 降级 | 捕获异常/空结果 → 回退 VAD 段（方案 C）并打 `fallback` 标记（复用现有 `_vad_segment_sentences` 行为） | 已含在半天内 |

### 4.4 必须处理的坑（实测踩到）

1. **`pred_timestamp=True` 不能省**：省略则 paraformer 不输出字符级 timestamp，`sentence_info` 静默降级为 VAD 段（粒度 20-60s），表现为"能出时间戳但精度退化"。
2. **监控 punc 对齐降级**：当出现日志 `punctuation timestamps could not be aligned, falling back to VAD segments`，说明句级精度失效。防御性检查：`sentence_info` 非空但 `s[0]["timestamp"]` 为空 → 判定降级，记录 `semantic_aligned: false`。
3. **单位统一**：`sentence_info` 的 `start/end` 是毫秒 int，`timestamp` 是毫秒对；transcript JSON 契约用秒 float——必须显式 `/1000`，避免抽帧时间偏差 1000 倍。
4. **引擎标识**：`engine` 字段改为 `paraformer-zh`（现有值 `SenseVoiceSmall` 已失真），前端/清单消费方注意兼容旧数据。
5. **punc 模型非必需但强烈建议**：无 punc 时 `sentence_timestamp=True` 直接跳过句切分（auto_model.py:1204-1210），句级时间戳退化为 VAD 段；配 punc 才能拿到标点分句的精确句级。

### 4.5 性能预期（实测：test480.wav 73s，CPU）

- 模型加载：首次 ~6s（3 模型，之后进程内常驻）
- 推理：~3.4s（RTF≈0.047，即 1s 音频约 47ms）
- 对比验收口径（PRD AC-12：单作品 ≤3min 端到端 <10min）：转写阶段远低于预算，方案 A 不构成瓶颈。

---

## 5. 方案 B 设计（备用：独立时间戳模型后处理）

适用场景：需要保留 SenseVoice 转写质量（情感/事件标记）或对既有转写文本补时间戳。

```python
from funasr import AutoModel

ts_model = AutoModel(model="iic/speech_timestamp_prediction-v1-16k-offline", disable_update=True)
# 对 text + audio 对齐，输出字符级时间戳
result = ts_model.generate(input=(wav_path, text), data_type=("sound", "text"))
# result[0]["timestamp"]  [[start_ms, end_ms], ...]
```

约束（官方模型卡）：
- 支持 Linux/macOS/Windows；离线场景；CPU 可跑（38M）。
- 输入文本必须与语音内容一致，不匹配时预测不稳定（需按句子逐条对齐，每段建议 ≤ 数十字）。
- 句级时间戳需自行按标点切分后逐句对齐，或对全文字符时间戳按标点聚合。
- 状态：**待实测**（模型未缓存）；作为方案 A 失败时的增强后备，不建议 MVP 主路径使用。

---

## 6. 方案 C 设计（降级链路）

触发条件：paraformer 加载失败 / 推理异常 / 输出为空。
实现：回退为现有 SenseVoice 转写（无时间戳）或纯 VAD 分段，`frame_manifest.json` 置 `semantic_aligned: false, fallback: true`（SPEC §8.2 已有契约），前端明确标注"非语义对齐"。

> 语义对齐抽帧是产品核心卖点，方案 C 仅保证"抽帧不中断"，不作为常态路径。

---

## 7. 实测记录

### 环境
- funasr 1.4.3，Python 3.13.12，CPU（无 GPU），Windows
- 音频：`media/_e2e/test480.wav`（73.05s 语音，16kHz）

### 实测矩阵

| 用例 | 参数 | keys | timestamp | sentence_info | 判定 |
|------|------|------|-----------|---------------|------|
| 现状（SenseVoiceSmall） | 无 | key/text | 无 | 无（单段） | 不满足 |
| A1 | paraformer+vad+punc, `sentence_timestamp=True` | key/text/sentence_info | 无 | 4 段（VAD 级，timestamp 空） | **退化**（缺 pred_timestamp） |
| A2 | paraformer+vad+punc, 默认 | key/text | 无 | 无 | 不满足 |
| A3 | paraformer+vad, `sentence_timestamp=True` | key/text/sentence_info | 无 | 4 段（VAD 级） | 退化 |
| B1 | paraformer+vad+punc, `pred_timestamp=True` | key/text/timestamp | **420 个（150ms-73110ms）** | 无 | 字符级 OK |
| **B2** | paraformer+vad+punc, `pred_timestamp=True, sentence_timestamp=True` | key/text/timestamp/sentence_info | **420 个** | **37 句（精确句级，含每句字符级）** | **通过（方案 A）** |

### 关键数据（B2）
- 字符级时间戳 420 个，覆盖 0.15s-73.11s 全音频，首字符 150ms 起。
- 句级 37 句，示例：`{start:150, end:2489, len:19, ts_n:18}`、`{start:7109, end:8010, len:8, ts_n:7}`——句内字符时间戳与文本长度一致，对齐质量良好。
- 推理耗时 3.4s / 73s 音频（RTF≈0.047）。

### 结论
- 方案 A 在**不改代码、不新增模型下载**的前提下即可交付（3 模型均已缓存）。
- 两个关键参数 `pred_timestamp=True` + `sentence_timestamp=True` 缺一不可。
- 复现脚本保留：`docs/_spike_timestamps.py`（round1 对比）、`docs/_spike_timestamps2.py`（round2 验证），结果见 `docs/_spike_timestamps_result.json` / `docs/_spike_timestamps_result2.json`。

---

## 8. 技术约束清单

1. funasr >= 1.4.3（旧版本 `sentence_timestamp` 参数行为可能不同，升级后需回归）。
2. 转写引擎锁定 paraformer-zh 组合，**不再使用 SenseVoice 作主引擎**（其无时间戳能力）；SenseVoice 保留为方案 C 降级引擎。
3. 所有时间戳统一：API/清单契约用**秒 float**，内部毫秒结构（char_timestamps）仅作增强保留，避免混用。
4. `sentence_info[0]["timestamp"]` 为空视为句级降级，须落 `semantic_aligned: false`。
5. 模型源默认 ModelScope（`hub` 默认 `ms`）；海外/受限网络环境可切 `hub="hf"` 拉 `funasr/paraformer-zh`、`funasr/fsmn-vad`、`funasr/ct-punc`（同一 funasr 版本行为一致）。
6. 禁止引入 WhisperX 等额外对齐栈（SPEC 表格曾列"转写增强 WhisperX"——方案 A 已覆盖该需求，降低依赖面）。

---

## 9. 后续建议（非阻塞）

- B4 词库机制细化后，可将词库命中精度从"句级窗口"升级到"命中词字符级起点 ± N 秒窗口"（利用 `char_timestamps`），进一步提升抽帧命中率。
- 转写 JSON 增加 `version` 字段（如 `"transcript_version": 2`），兼容旧单段数据。
- 长视频（>10min）建议 `vad_kwargs={"max_single_segment_time": 30000}` 控制分段上限（SPEC 验收口径外，P2 优化）。
