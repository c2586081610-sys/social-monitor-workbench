/** P3 博主作品列表：作品列表 + 三件套进度 + 状态筛选 Tab（全部/新作品/排队/下载中/转写中/笔记中/已完成/失败）+ 重试 + 打开笔记。 */
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import WorkListItem from '../components/work/WorkListItem';
import PlatformBadge from '../components/common/PlatformBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { getCreator, listCreatorWorks } from '../services/creators';
import { useAsyncData, usePolling } from '../hooks/useApi';
import { STATUS_TABS, RUNNING_STATUSES } from '../utils/constants';
import type { Work } from '../types/api.d';

export default function CreatorWorksPage() {
  const { id } = useParams<{ id: string }>();
  const creatorId = Number(id);
  const [tabKey, setTabKey] = useState('all');

  const creatorQuery = useAsyncData(() => getCreator(creatorId), [creatorId]);
  const worksQuery = useAsyncData(() => listCreatorWorks(creatorId, { page: 1, limit: 100 }), [creatorId]);

  const works = worksQuery.data?.items ?? [];
  const hasRunning = useMemo(() => works.some((w) => RUNNING_STATUSES.has(w.status)), [works]);

  // 存在 running 状态时 5s 轮询，完成后停轮
  usePolling(worksQuery.refetch, hasRunning && !worksQuery.loading, 5000);

  const tabCounts = useMemo(() => {
    const counts = new Map<string, number>();
    STATUS_TABS.forEach((t) => counts.set(t.key, 0));
    counts.set('all', works.length);
    works.forEach((w) => {
      STATUS_TABS.forEach((t) => {
        if (t.statuses?.includes(w.status)) counts.set(t.key, (counts.get(t.key) ?? 0) + 1);
      });
    });
    return counts;
  }, [works]);

  const filtered = useMemo(() => {
    const tab = STATUS_TABS.find((t) => t.key === tabKey) ?? STATUS_TABS[0];
    if (!tab.statuses) return works;
    return works.filter((w) => tab.statuses!.includes(w.status));
  }, [works, tabKey]);

  const creator = creatorQuery.data;

  return (
    <div className="space-y-4">
      <Link to="/" className="inline-flex items-center gap-1 text-xs text-ink-muted transition-colors hover:text-primary">
        <ArrowLeft className="h-3.5 w-3.5" />
        返回博主列表
      </Link>

      {creatorQuery.loading ? (
        <LoadingState label="加载博主信息…" />
      ) : creatorQuery.error ? (
        <ErrorState message={creatorQuery.error.message} onRetry={creatorQuery.refetch} />
      ) : creator ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface p-4 shadow-card">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-sidebar text-sm font-semibold text-ink-secondary">
            {creator.name.slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold text-ink">{creator.name}</h1>
              <PlatformBadge platform={creator.platform} />
            </div>
            <p className="truncate text-xs text-ink-muted">
              {creator.profile_url} · 共 {worksQuery.data?.total ?? 0} 个作品
            </p>
          </div>
        </div>
      ) : null}

      {/* 状态筛选 Tab */}
      <div className="flex flex-wrap gap-1.5">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setTabKey(tab.key)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              tabKey === tab.key
                ? 'bg-primary text-white'
                : 'border border-line bg-surface text-ink-secondary hover:bg-sidebar'
            }`}
          >
            {tab.label}（{tabCounts.get(tab.key) ?? 0}）
          </button>
        ))}
      </div>

      {worksQuery.loading ? (
        <LoadingState label="加载作品…" />
      ) : worksQuery.error ? (
        <ErrorState message={worksQuery.error.message} onRetry={worksQuery.refetch} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={tabKey === 'all' ? '还没有作品' : '该状态下暂无作品'}
          hint={tabKey === 'all' ? '新作品检测到后将自动进入流水线，进度会实时更新。' : '可切换到「全部」查看其他状态的作品。'}
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((w: Work) => (
            <WorkListItem key={w.id} work={w} onChanged={worksQuery.refetch} />
          ))}
        </div>
      )}
    </div>
  );
}
