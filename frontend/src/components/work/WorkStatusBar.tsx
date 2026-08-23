/** 三件套进度条：下载 → 转写 → AI 笔记 三段式（基于作品状态推导）。 */
import { Check, Loader2, X } from 'lucide-react';
import { stageProgress } from '../../utils/stage';
import type { StageKey, StageProgressItem } from '../../utils/stage';
import type { TaskStage, WorkStatus } from '../../types/api.d';

const STAGE_ICON_STYLE: Record<StageKey, string> = {
  download: 'bg-info-light text-info',
  transcribe: 'bg-info-light text-info',
  note: 'bg-primary-light text-primary',
};

function SegmentIcon({ item }: { item: StageProgressItem }) {
  if (item.state === 'done') return <Check className="h-3.5 w-3.5" />;
  if (item.state === 'failed') return <X className="h-3.5 w-3.5" />;
  if (item.state === 'active') return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
  return null;
}

/** 每段：图标 + 标签 + 状态点。 */
export default function WorkStatusBar({ status, stages }: { status: WorkStatus; stages?: TaskStage[] }) {
  const items = stageProgress(status, stages);

  return (
    <div className="flex items-center gap-2" aria-label="三件套进度">
      {items.map((item, i) => (
        <div key={item.key} className="flex items-center gap-2">
          {i > 0 ? <span className="h-px w-4 bg-line" /> : null}
          <div
            className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              item.state === 'done'
                ? 'bg-success-light text-success'
                : item.state === 'failed'
                  ? 'bg-danger-light text-danger'
                  : item.state === 'active'
                    ? STAGE_ICON_STYLE[item.key]
                    : 'bg-sidebar text-ink-muted'
            }`}
            title={item.error ?? undefined}
          >
            <SegmentIcon item={item} />
            {item.label}
          </div>
        </div>
      ))}
    </div>
  );
}
