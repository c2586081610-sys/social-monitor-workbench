/** 博主卡片：头像占位 / 名称 / 分组 / 平台 / 监控状态 / 最近作品缩略+状态徽标 / 启停 / 删除。 */
import { Link } from 'react-router-dom';
import { Pause, Play, Trash2, User } from 'lucide-react';
import { useState } from 'react';
import { deleteCreator, updateCreator } from '../../services/creators';
import { useMutation } from '../../hooks/useApi';
import PlatformBadge from '../common/PlatformBadge';
import ConfirmDialog from '../common/ConfirmDialog';
import { formatDateTime, relativeTime } from '../../utils/format';
import { STATUS_LABEL } from '../../utils/constants';
import type { Creator, WorkSummary } from '../../types/api.d';

interface CreatorCardProps {
  creator: Creator;
  groupName?: string;
  recentWorks?: WorkSummary[];
  onChanged: () => void;
}

export default function CreatorCard({ creator, groupName, recentWorks = [], onChanged }: CreatorCardProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const toggleMutation = useMutation((enabled: boolean) =>
    updateCreator(creator.id, { enabled }),
  );
  const deleteMutation = useMutation((id: number) => deleteCreator(id));

  const handleToggle = async () => {
    try {
      await toggleMutation.run(!creator.enabled);
      onChanged();
    } catch {
      /* 错误由卡片顶部统一提示，此处静默 */
    }
  };

  const handleDelete = async () => {
    try {
      await deleteMutation.run(creator.id);
      setConfirmOpen(false);
      onChanged();
    } catch {
      setConfirmOpen(false);
    }
  };

  return (
    <div className="flex flex-col rounded-lg border border-line bg-surface p-4 shadow-card transition-colors hover:border-primary/40">
      <div className="flex items-start gap-3">
        {/* 头像占位：平台首字 */}
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-sidebar text-sm font-semibold text-ink-secondary">
          {creator.name.slice(0, 1) || <User className="h-5 w-5" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link to={`/creators/${creator.id}`} className="truncate-1 text-sm font-semibold text-ink hover:text-primary">
              {creator.name}
            </Link>
            <PlatformBadge platform={creator.platform} />
          </div>
          <p className="mt-0.5 truncate text-xs text-ink-muted">{groupName ?? '未分组'}</p>
        </div>
        <button
          type="button"
          onClick={handleToggle}
          disabled={toggleMutation.loading}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium transition-colors disabled:opacity-60 ${
            creator.enabled
              ? 'bg-success-light text-success hover:bg-success hover:text-white'
              : 'bg-sidebar text-ink-muted hover:bg-danger hover:text-white'
          }`}
          title={creator.enabled ? '点击停用监控' : '点击启用监控'}
        >
          {creator.enabled ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          {creator.enabled ? '监控中' : '已停用'}
        </button>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-ink-secondary">
        <div>
          <dt className="text-ink-muted">最近轮询</dt>
          <dd className="truncate-1">{relativeTime(creator.last_poll_at)}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">最近作品</dt>
          <dd className="truncate-1">{creator.last_work_at ? formatDateTime(creator.last_work_at) : '—'}</dd>
        </div>
      </dl>

      {/* 最近作品缩略 + 状态徽标 */}
      <div className="mt-3 space-y-1.5">
        {recentWorks.length === 0 ? (
          <p className="text-xs text-ink-muted">暂无作品记录</p>
        ) : (
          recentWorks.slice(0, 3).map((w) => (
            <Link key={w.id} to={`/works/${w.id}`} className="flex items-center gap-2 rounded-md px-1 py-0.5 transition-colors hover:bg-sidebar">
              <span className="h-8 w-12 shrink-0 rounded bg-sidebar" aria-hidden="true" />
              <span className="truncate-1 min-w-0 flex-1 text-xs text-ink-secondary">{w.title}</span>
              <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                w.status === 'DONE'
                  ? 'bg-success-light text-success'
                  : w.status === 'FAILED'
                    ? 'bg-danger-light text-danger'
                    : 'bg-info-light text-info'
              }`}>
                {STATUS_LABEL[w.status] ?? w.status}
              </span>
            </Link>
          ))
        )}
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
        <Link
          to={`/creators/${creator.id}`}
          className="rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-hover"
        >
          查看作品
        </Link>
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1.5 text-xs text-ink-muted transition-colors hover:border-danger/40 hover:text-danger"
        >
          <Trash2 className="h-3.5 w-3.5" />
          删除
        </button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="删除博主"
        message={`确定删除博主「${creator.name}」？其作品记录将保留（creator 解除关联），监控任务一并移除。`}
        loading={deleteMutation.loading}
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
