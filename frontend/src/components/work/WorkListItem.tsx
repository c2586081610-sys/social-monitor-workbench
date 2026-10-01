/** 作品列表项：原封面 + 标题/时间 + 三件套进度 + 状态徽标 + 操作（重试 / 打开笔记 / 详情）。 */
import { Link } from 'react-router-dom';
import { Archive, ExternalLink, ImageIcon, RotateCcw } from 'lucide-react';
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
import { safeHttpUrl } from '../../utils/urls';

const ARCHIVE_CHECK_LABEL: Record<string, string> = {
  verified: '已核实',
  needs_review: '待核实',
  conflict: '存在冲突',
  failed: '核对失败',
};

interface WorkListItemProps {
  work: Work;
  /** 数据变更后回调（重试成功 / 归类后刷新列表） */
  onChanged?: () => void;
}

export default function WorkListItem({ work, onChanged }: WorkListItemProps) {
  const [retryError, setRetryError] = useState<string | null>(null);
  const [coverError, setCoverError] = useState(false);
  const retryMutation = useMutation((id: number) => retryWork(id));
  const safeUrl = safeHttpUrl(work.url);
  const archiveCheckStatus = (work as Work & { archive_check_status?: string | null }).archive_check_status;
  const downloadedLabel = work.download_time_source === 'not_required'
    ? '无需媒体下载'
    : work.downloaded_at
      ? `${formatDateTime(work.downloaded_at)}（来源 ${work.download_time_source ?? '未知'}）`
      : '下载时间未知';

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
      {/* 原封面（cover_url 为平台外链；无封面或加载失败用占位） */}
      <Link to={`/works/${work.id}`} className="shrink-0" aria-label="查看作品详情">
        {work.cover_url && !coverError ? (
          <img
            src={work.cover_url}
            alt=""
            loading="lazy"
            onError={() => setCoverError(true)}
            className="h-16 w-24 rounded-md border border-line object-cover"
          />
        ) : (
          <span className="flex h-16 w-24 items-center justify-center rounded-md bg-sidebar text-ink-muted">
            <ImageIcon className="h-6 w-6" />
          </span>
        )}
      </Link>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/works/${work.id}`} className="truncate-1 max-w-full text-sm font-medium text-ink hover:text-primary">
            {work.title}
          </Link>
          <PlatformBadge platform={work.platform} />
          <StatusBadge status={work.status} notePath={work.note_path} />
        </div>

        <p className="mt-1 text-xs text-ink-muted">
          发布时间（北京时间）{formatDateTime(work.published_at)} · 下载完成时间（北京时间）{downloadedLabel} · 平台 {PLATFORM_LABEL[work.platform] ?? work.platform}
          {work.frame_count > 0 ? ` · 关键帧 ${work.frame_count}` : ''}
          {archiveCheckStatus ? ` · 归档核对 ${ARCHIVE_CHECK_LABEL[archiveCheckStatus] ?? archiveCheckStatus}` : ''}
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
          <Link
            to={`/archive?work_id=${work.id}`}
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-ink-secondary transition-colors hover:bg-sidebar"
          >
            <Archive className="h-3.5 w-3.5" />归档记录
          </Link>
          {safeUrl ? (
            <a
              href={safeUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-ink-secondary transition-colors hover:bg-sidebar"
            >
              <ExternalLink className="h-3.5 w-3.5" />原作品
            </a>
          ) : null}
          {work.note_path ? (
            <OpenNoteButton notePath={work.note_path} />
          ) : null}
        </div>

        {retryError ? <p className="mt-1 text-xs text-danger">{retryError}</p> : null}
      </div>
    </div>
  );
}
