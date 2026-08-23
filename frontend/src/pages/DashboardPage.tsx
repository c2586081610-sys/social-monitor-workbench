/** P1 博主列表（首页）：博主卡片 + 添加博主 + 手动轮询 + 引擎在线状态 + 分组过滤。 */
import { useEffect, useMemo, useState } from 'react';
import { Plus, RefreshCw, UserPlus } from 'lucide-react';
import CreatorCard from '../components/creator/CreatorCard';
import AddCreatorModal from '../components/creator/AddCreatorModal';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { ToneBadge } from '../components/common/StatusBadge';
import { listCreators, getCreator } from '../services/creators';
import { listGroups } from '../services/groups';
import { getSystemHealth } from '../services/health';
import { triggerPoll } from '../services/monitor';
import { useAsyncData, useMutation, usePolling } from '../hooks/useApi';
import { PLATFORMS, SYSTEM_COMPONENT_LABEL, SYSTEM_COMPONENT_STATUS } from '../utils/constants';
import type { Platform, SystemHealth, WorkSummary } from '../types/api.d';

const COMPONENT_TONE: Record<SystemHealth['status'], 'success' | 'danger' | 'warning' | 'neutral'> = {
  online: 'success',
  offline: 'danger',
  degraded: 'warning',
  unknown: 'neutral',
};

export default function DashboardPage() {
  const [groupFilter, setGroupFilter] = useState<'all' | number>('all');
  const [addOpen, setAddOpen] = useState(false);
  const [pollMsg, setPollMsg] = useState<string | null>(null);
  const [pollPlatform, setPollPlatform] = useState<string>('');

  const groupsQuery = useAsyncData(() => listGroups(), []);
  const creatorsQuery = useAsyncData(
    () =>
      listCreators({
        page: 1,
        limit: 50,
        ...(typeof groupFilter === 'number' ? { group_id: groupFilter } : {}),
      }),
    [groupFilter],
  );
  const systemQuery = useAsyncData(() => getSystemHealth(), []);

  const pollMutation = useMutation((platform: string) => triggerPoll(platform ? (platform as Platform) : undefined));

  // 每 30s 刷新一次引擎健康度
  usePolling(systemQuery.refetch, true, 30000);

  // 最近作品摘要（详情接口返回 ≤5 条），仅对当前页博主拉取
  const [recentMap, setRecentMap] = useState<Record<number, WorkSummary[]>>({});
  useEffect(() => {
    const items = creatorsQuery.data?.items ?? [];
    if (items.length === 0) {
      setRecentMap({});
      return;
    }
    let cancelled = false;
    Promise.all(items.map((c) => getCreator(c.id).catch(() => null))).then((details) => {
      if (cancelled) return;
      const map: Record<number, WorkSummary[]> = {};
      items.forEach((c, i) => {
        if (details[i]) map[c.id] = details[i]!.recent_works;
      });
      setRecentMap(map);
    });
    return () => {
      cancelled = true;
    };
  }, [creatorsQuery.data]);

  const groupName = useMemo(() => {
    const groups = groupsQuery.data?.items ?? [];
    const find = (id: number | null) => groups.find((g) => g.id === id)?.name;
    return (id: number | null) => (id == null ? undefined : find(id));
  }, [groupsQuery.data]);

  const handlePoll = async () => {
    setPollMsg(null);
    try {
      await pollMutation.run(pollPlatform);
      setPollMsg('轮询已触发，正在检测新作品…');
      creatorsQuery.refetch();
      systemQuery.refetch();
    } catch (e) {
      setPollMsg(e instanceof Error ? `轮询失败：${e.message}` : '轮询失败');
    }
  };

  const systemItems = systemQuery.data?.items ?? [];
  const creators = creatorsQuery.data?.items ?? [];

  return (
    <div className="space-y-4">
      {/* 头部操作 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">博主列表</h1>
          <p className="text-xs text-ink-muted">四平台统一监控 · 共 {creatorsQuery.data?.total ?? 0} 位</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1.5">
            <select
              value={pollPlatform}
              onChange={(e) => setPollPlatform(e.target.value)}
              className="bg-transparent text-sm text-ink-secondary focus:outline-none"
              aria-label="轮询平台"
            >
              <option value="">全部平台</option>
              {PLATFORMS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={handlePoll}
              disabled={pollMutation.loading}
              className="inline-flex items-center gap-1 rounded-md bg-surface px-2 py-0.5 text-sm text-primary transition-colors hover:bg-primary-light disabled:opacity-60"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${pollMutation.loading ? 'animate-spin' : ''}`} />
              立即轮询
            </button>
          </div>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover"
          >
            <UserPlus className="h-4 w-4" />
            添加博主
          </button>
        </div>
      </div>

      {pollMsg ? (
        <p className="rounded-md bg-info-light px-3 py-2 text-sm text-info">{pollMsg}</p>
      ) : null}

      {/* 引擎在线状态 */}
      <section className="rounded-lg border border-line bg-surface p-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-ink-muted">引擎在线状态</h2>
        {systemQuery.loading ? (
          <p className="text-xs text-ink-muted">检测中…</p>
        ) : systemItems.length === 0 ? (
          <p className="text-xs text-ink-muted">暂无引擎信息</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {systemItems.map((s) => (
              <span key={s.component} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-sidebar px-2.5 py-1 text-xs text-ink-secondary">
                <EngineStatusBadge status={s.status} />
                {SYSTEM_COMPONENT_LABEL[s.component] ?? s.component}
                <span className="text-ink-muted">· {SYSTEM_COMPONENT_STATUS[s.status] ?? s.status}</span>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* 分组过滤 */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setGroupFilter('all')}
          className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            groupFilter === 'all' ? 'bg-primary text-white' : 'border border-line bg-surface text-ink-secondary hover:bg-sidebar'
          }`}
        >
          全部
        </button>
        {(groupsQuery.data?.items ?? []).map((g) => (
          <button
            key={g.id}
            type="button"
            onClick={() => setGroupFilter(g.id)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              groupFilter === g.id ? 'bg-primary text-white' : 'border border-line bg-surface text-ink-secondary hover:bg-sidebar'
            }`}
          >
            {g.name}（{g.creator_count}）
          </button>
        ))}
      </div>

      {/* 博主卡片 */}
      {creatorsQuery.loading ? (
        <LoadingState label="加载博主中…" />
      ) : creatorsQuery.error ? (
        <ErrorState message={creatorsQuery.error.message} onRetry={creatorsQuery.refetch} />
      ) : creators.length === 0 ? (
        <EmptyState
          title="还没有博主"
          hint="添加第一位博主后，系统将按分组定时检测新作品，并自动进入 下载 → 转写 → 关键帧 → AI 笔记 流水线。"
          action={
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover"
            >
              <Plus className="h-4 w-4" />
              添加第一位博主
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {creators.map((c) => (
            <CreatorCard
              key={c.id}
              creator={c}
              groupName={groupName(c.group_id)}
              recentWorks={recentMap[c.id]}
              onChanged={creatorsQuery.refetch}
            />
          ))}
        </div>
      )}

      <AddCreatorModal
        open={addOpen}
        groups={groupsQuery.data?.items ?? []}
        onClose={() => setAddOpen(false)}
        onCreated={() => {
          setAddOpen(false);
          creatorsQuery.refetch();
          groupsQuery.refetch();
        }}
      />
    </div>
  );
}

function EngineStatusBadge({ status }: { status: SystemHealth['status'] }) {
  return <ToneBadge tone={COMPONENT_TONE[status]} label={SYSTEM_COMPONENT_STATUS[status] ?? status} />;
}
