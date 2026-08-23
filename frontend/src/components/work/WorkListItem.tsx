/** 作品列表项：封面占位 + 标题/时间 + 三件套进度 + 状态徽标 + 操作（重试 / 打开笔记 / 详情）。 */
import { Link } from 'react-router-dom';
import { ExternalLink, ImageIcon, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { retryWork } from '../../services/works';
import { useMutation } from '../../hooks/useApi';
import { StatusBadge } from '../common/StatusBadge';
import PlatformBadge from '../common/PlatformBadge';
import WorkStatusBar from './WorkStatusBar';
import OpenNoteButton from './OpenNoteButton';
import { formatDateTime } from '../../utils/format';
import { PLATFORM_LABEL } from '../../utils/constants';
import type { Work } from '../../types/api.d';

interface WorkListItemProps {
  work: Work;
  /** 数据变更后回调（重试成功 / 归类后刷新列表） */
  onChanged?: () => void;
}

export default function WorkListItem({ work, onChanged }: WorkListItemProps) {
  const [retryError, setRetryError] = useState<string | null>(null);
  const retryMutation = useMutation((id: number) => retryWork(id));

  const handleRetry = async () => {
    setRetryError(null);
    try {
      await retryMutation.run(work.id);
      onChanged?.();
    } catch (e) {
      setRetryError(e instanceof Error ? e.message : '重试失败');
    }
  };

  return (
    <div className="flex gap-3 rounded-lg border border-line bg-surface p-3 shadow-card transition-colors hover:border-primary/40">
      {/* 封面占位（媒体为本地文件，前端无静态服务，用平台图标占位） */}
      <Link to={`/works/${work.id}`} className="shrink-0" aria-label="查看作品详情">
        <span className="flex h-16 w-24 items-center justify-center rounded-md bg-sidebar text-ink-muted">
          <ImageIcon className="h-6 w-6" />
        </span>
      </Link>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/works/${work.id}`} className="truncate-1 max-w-full text-sm font-medium text-ink hover:text-primary">
            {work.title}
          </Link>
          <PlatformBadge platform={work.platform} />
          <StatusBadge status={work.status} />
        </div>

        <p className="mt-1 text-xs text-ink-muted">
          发布于 {formatDateTime(work.published_at)} · 平台 {PLATFORM_LABEL[work.platform] ?? work.platform}
          {work.frame_count > 0 ? ` · 关键帧 ${work.frame_count}` : ''}
        </p>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <WorkStatusBar status={work.status} />
          <span className="flex-1" />
          {work.status === 'FAILED' ? (
            <button
              type="button"
              onClick={handleRetry}
              disabled={retryMutation.loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-ink-secondary transition-colors hover:bg-sidebar disabled:opacity-60"
            >
              <RotateCcw className={`h-3.5 w-3.5 ${retryMutation.loading ? 'animate-spin' : ''}`} />
              重试
            </button>
          ) : null}
          {work.note_path ? (
            <OpenNoteButton notePath={work.note_path} />
          ) : (
            <a
              href={work.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-ink-secondary transition-colors hover:bg-sidebar"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              原作品
            </a>
          )}
        </div>

        {retryError ? <p className="mt-1 text-xs text-danger">{retryError}</p> : null}
      </div>
    </div>
  );
}
