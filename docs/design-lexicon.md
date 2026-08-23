# 设计文档：词库系统机制细化（T5）

> 项目：四平台博主监控 + 三件套 AI 笔记
> 作者：首席架构师 高见远
> 日期：2026-08-23
> 状态：机制设计完成，与 frames.py 现有实现对齐并修正差异
> 关联：SPEC lexicon 表（§7.5）/ §8.2 / F10 / B4 / PRD AC-10 / openapi-aggregator.yaml `/lexicon`

---

## 1. 现状与目标

**现状**（SPEC §7.5 已定 lexicon 表 + `monitor/pipeline/frames.py` 已实现 `match_windows`/`_frame_count_for_window`）：
- 词库 CRUD 端点已定义（GET/POST/PATCH/DELETE `/lexicon`）；
- frames.py 已有"子串命中 → 窗口 → 权重净额 → 抽帧"基础实现；
- 但机制细节（B4）未落定：多词条冲突、阈值、窗口边界、上限、平台过滤、命中精度。

**目标**：在现有实现基础上补全机制规则，作为后端实现与前端词库管理页的共同依据。配合 T5 句级时间戳方案（`docs/design-timestamps.md`），词库命中窗口从"整段退化"升级为"精确句级"。

---

## 2. 词条字段（lexicon 表）

### 2.1 既有字段（SPEC §7.5，保持兼容）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| term | TEXT | UNIQUE NOT NULL | 触发词（如"A股""走势""表格"） |
| action | TEXT | NOT NULL DEFAULT 'increase' | increase=增加关键帧 / decrease=减少关键帧 |
| weight | REAL | NOT NULL DEFAULT 1.0 | 权重（命中后对帧数的量化增量） |
| enabled | INTEGER | NOT NULL DEFAULT 1 | 启停（0=停用不参与命中） |
| platform_scope | TEXT | NULL | NULL=全平台生效；逗号分隔平台列表（douyin/bilibili/xhs/twitter） |
| created_at / updated_at | TEXT | NOT NULL | |

### 2.2 新增字段建议（B4 落定，后端实现时加入）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| match_mode | TEXT | 'substring' | substring=子串包含（MVP 默认）；regex=正则匹配（B4 增强，需转义校验） |
| window_padding | REAL | 0.5 | 命中窗口前后各扩展秒数（秒，容忍"话说完画面才出现"的滞后） |
| max_frames | INTEGER | 5 | 单窗口抽帧上限（防权重溢出） |
| note | TEXT | NULL | 词条用途备注（前端展示，非逻辑字段） |

> 兼容性：新增字段全部有默认值，不影响既有行；openapi `/lexicon` schema 同步补充即可。

---

## 3. 命中与窗口构造

### 3.1 输入

```
segments: [{start, end, text}, ...]   # 句级时间戳转写稿（方案 A 输出，秒 float）
entries:  [{term, action, weight, enabled, platform_scope, match_mode, window_padding, max_frames}, ...]
platform: str                          # 当前作品平台（用于 platform_scope 过滤）
```

### 3.2 匹配流程（frames.py `match_windows` 增强）

```
1. 平台过滤：entries 中 platform_scope 非空且不含当前 platform → 跳过
2. 逐段文本匹配：
   - substring：term in text（大小写不敏感，中文不受影响）
   - regex：re.search(term, text)，编译失败词条记 error 并跳过（不阻断整批）
3. 命中词条收集为该窗口的 hits：{term, action, weight, match_mode}
4. 窗口边界：start - window_padding, end + window_padding（clamp ≥ 0）
5. 输出 windows: [{start, end, hits, max_frames}, ...]
```

### 3.3 命中精度说明（与 T5 联动）

- 方案 A 落地前：segments 退化为单段 → 命中窗口=整段（现状问题）；
- 方案 A 落地后：segments 为 37 句精确句级 → 命中窗口精确到句子（典型 2-10s）；
- B4 后续增强：利用句内字符级 `char_timestamps` 定位**命中词起点**，窗口可缩至 `[词起点-0.5s, 词终点+0.5s]`，抽帧命中率更高（非阻塞，见 §7）。

---

## 4. 量化增删规则

### 4.1 公式

```
base_frames = 1                                    # SPEC §8.2：每命中窗口默认 1 帧
net_delta   = Σ(h.increase.weight) - Σ(h.decrease.weight)   # 同窗口多词条权重净额
target      = base_frames + net_delta
count       = clamp(round(target), 0, window.max_frames)    # 上限防溢出，下限 0

count == 0 → 该窗口不抽帧（窗口标记 skipped，落 manifest 供审计）
count >= 1 → 窗口内均匀取 count 帧：t_k = start + span*(k+0.5)/count, k=0..count-1
```

### 4.2 规则语义

| 命中情况 | net_delta | count | 说明 |
|----------|-----------|-------|------|
| 无命中 | — | 不产生窗口 | 该段不抽帧 |
| increase 词条（weight=1） | +1 | 2 | 默认 1 帧 → 2 帧 |
| increase 词条（weight=2） | +2 | 3 | 高权重强调 |
| decrease 词条（weight=1） | -1 | 0 | **该窗口不抽帧**（内容被标记为不重要） |
| increase(1) + decrease(1) 同窗口 | 0 | 1 | 净额归零 → 回到默认 1 帧 |
| increase(2) + decrease(3) 同窗口 | -1 | 0 | 净额为负 → 不抽帧，冲突写日志 |
| 任意命中 + 权重极大 | — | clamp 到 max_frames | 上限保护 |

### 4.3 与现有实现的差异（必须修正）

现有 `frames.py`：

```python
count = max(1, round(net))   # net = Σincrease - Σdecrease
```

问题：
1. **decrease 词条单独命中失效**：`net = -1` → `max(1, -1) = 1`，decrease 命中与未命中一样（都是 1 帧），违背"减少帧"语义；
2. **基准缺失**：`net=0`（increase+decrease 抵消）仍得 1 帧，语义上正确但公式未体现"默认 1 帧基数"；
3. **无上限**：weight=100 会抽 100 帧，浪费磁盘与推理（ffmpeg 每帧一次调用）。

修正为 §4.1 公式：`base + net_delta → clamp(0, max_frames)`。

### 4.4 置信度（manifest confidence）

```
confidence = min(0.99, 0.5 + 0.1 * |net_delta|)    # 简单单调映射
# net_delta=0 → 0.5（默认帧，低置信）
# net_delta=+1 → 0.6；net_delta=+4 → 0.9
```

替代现固定 `0.9`。MVP 阶段不引入复杂模型，映射规则写死即可。

---

## 5. 冲突处理（K20）

| 场景 | 规则 |
|------|------|
| 同窗口多词条 | 合并 hits，按 §4.1 权重净额计算 count，**不按"最高权重者"覆盖**（与 PRD §8 边界"取权重高者"一致性说明：取净额是"高者优先"的量化形式，避免仅取单个词条丢失信息） |
| 同窗口 increase 与 decrease 并存 | 净额相加；结果 ≤0 → 不抽帧并写日志 `lexicon conflict resolved by net weight: {hits}`（现有 K20 日志保留） |
| 同 term 重复（大小写/全半角差异） | term UNIQUE 约束；匹配时大小写不敏感，全半角不归一（中文场景影响小，B4 可加归一化） |
| regex 编译失败 | 跳过该词条，写 error 日志，不阻断其他词条 |
| 窗口重叠（相邻句均命中） | 不合并（保持句粒度），抽帧各自独立；若未来发现重复帧过多，由感知哈希去重（SPEC §8.2 已有）兜底 |

---

## 6. 与 frames.py 对接

### 6.1 接口签名（增强，保持向后兼容）

```python
def match_windows(
    segments: list[dict],          # [{start, end, text}] 秒 float
    entries: list[dict],           # 词条，含新字段（缺省用默认值）
    platform: str | None = None,   # 新增：平台过滤
) -> list[dict]:                   # [{start, end, hits, max_frames}]

def _frame_count_for_window(window: dict) -> int:
    # base + net_delta → clamp(0, max_frames)；返回 0 表示跳过

def extract_frames(video_path, windows, out_dir) -> list[dict]:
    # count==0 的窗口跳过；confidence 按 §4.4 计算
```

### 6.2 调用方（pipeline 编排层）

```python
entries = lexicon_repo.list_enabled()          # SELECT * FROM lexicon WHERE enabled=1
windows = match_windows(segments, entries, platform=work.platform)
frames  = extract_frames(video_path, windows, frames_dir)
manifest = write_manifest(work_id, frames, frames_dir,
                          semantic_aligned=not degraded,
                          fallback=degraded)
```

### 6.3 输出 manifest（SPEC §8.2 示例扩展）

```json
{
  "work_id": 12,
  "semantic_aligned": true,
  "fallback": false,
  "frames": [
    {
      "file": "frames/frame_0001.jpg",
      "time_seconds": 42.5,
      "window_start": 40.0,
      "window_end": 45.5,
      "hits": [{"term": "A股", "action": "increase", "weight": 1.0}],
      "confidence": 0.6
    }
  ],
  "skipped_windows": [{"start": 12.0, "end": 15.0, "hits": [{"term": "广告", "action": "decrease", "weight": 1.0}]}],
  "lexicon_version": 2
}
```

---

## 7. 边界与降级

| 场景 | 行为 |
|------|------|
| 词库为空/全部停用 | 无语义窗口 → 走兜底均匀抽帧（`fallback: true`，SPEC §8.2）或按配置抽 0 帧（前端提示"未配置词库"） |
| 转写无时间戳（降级） | 上层标记 `semantic_aligned: false`；词库命中不可用 → 兜底抽帧 |
| 命中窗口 count=0 全部 | manifest 无 frames + `skipped_windows` 记录，前端展示"命中但被 decrease 排除" |
| 平台过滤后无词条 | 等同词库为空，兜底 |
| 长视频多命中 | 总帧数上限建议：`min(20, Σcount)`（配置项 `FRAME_TOTAL_MAX`），防单作品帧数爆炸 |
| 命中词是噪音（"嗯""啊"等语气词） | 不建词条即不命中；可在前端词库管理页提示"建议使用有内容含义的实词" |

---

## 8. 遗留与后续（B4 范围外/非阻塞）

1. **字符级起点定位**：利用 `char_timestamps`（T5 方案 A 增强字段）将窗口缩至命中词 ± padding，提升图表/口播帧命中率——优先级高，建议 P1 后期纳入。
2. **正则与模糊匹配**：`match_mode="regex"`、编辑距离容错（错别字"A古走势"）——B4。
3. **词条批量导入/导出**：CSV 导入词库——B4。
4. **命中统计埋点**：PRD §10 `lexicon_hit`（带词条/动作）——MVP 必埋，由 lexicon 命中处上报。
5. **负面词条示例库**：默认内置常见"减少帧"模板（如"我们下期再见""点赞关注"）——B4，避免空库冷启动。

---

## 9. 对 openapi-aggregator.yaml 的增量（提示后端）

- `/lexicon` schema 增补：`match_mode` / `window_padding` / `max_frames` / `note`（均可选，默认值见 §2.2）。
- `frame_manifest.json` 增补：`skipped_windows` / `lexicon_version`（可选字段，向后兼容）。
