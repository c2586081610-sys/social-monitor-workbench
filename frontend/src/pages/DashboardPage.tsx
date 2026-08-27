/** P1 博主列表（首页）：全局聚合开关 + 立即爬取全部 + 自动刷新 + 平台监控 + 引擎分组 + 博主卡片。 */
import { useEffect, useMemo, useState } from 'react';
import { Plus, RefreshCw, UserPlus } from 'lucide-react';
import CreatorCard from '../components/creator/CreatorCard';
import AddCreatorModal from '../components/creator/AddCreatorModal';
import Toggle from '../components/common/Toggle';
import EngineHealthPanel from '../components/dashboard/EngineHealthPanel';
import PlatformPollPanel from '../components/dashboard/PlatformPollPanel';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { listCreators, getCreator } from '../services/creators';
import { listGroups } from '../services/groups';
import { pollNow } from '../services/monitor';
import { useAsyncData } from '../hooks/useApi';
import { readAggSettings, setGlobalEnabled } from '../utils/aggSettings';
import type { WorkSummary } from '../types/api.d';

export default function DashboardPage() {
  const [groupFilter, setGroupFilter] = useState<'all' | number>('all');
  const [addOpen, setAddOpen] = useState(false);
  const [pollMsg, setPollMsg] = useState<string | null>(null);
  const [pollingAll, setPollingAll] = useState(false);
  const [agg, setAgg] = useState(() => readAggSettings());

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

  const handleToggleGlobal = (value: boolean) => {
    setGlobalEnabled(value);
    setAgg((a) => ({ ...a, globalEnabled: value }));
  };

  const handlePollAll = async () => {
    if (pollingAll) return;
    setPollMsg(null);
    setPollingAll(true);
    try {
      await pollNow();
      setPollMsg('爬取已触发，正在拉取最新作品…');
      creatorsQuery.refetch();
    } catch (e) {
      setPollMsg(e instanceof Error ? `爬取失败：${e.message}` : '爬取失败');
    } finally {
      setPollingAll(false);
    }
  };

  // 自动刷新：总启用 + 设置开启时，每 N 分钟触发一次全平台爬取（仅在 Web 打开期间生效）
  useEffect(() => {
    if (!agg.globalEnabled || !agg.autoRefresh) return;
    const minutes = Math.max(1, agg.autoRefreshMinutes);
    const id = window.setInterval(() => {
      const cur = readAggSettings();
      if (!cur.globalEnabled || !cur.autoRefresh) return;
      pollNow().catch(() => {
        /* 静默，下个周期重试 */
      });
    }, minutes * 60 * 1000);
    return () => window.clearInterval(id);
  }, [agg.globalEnabled, agg.autoRefresh, agg.autoRefreshMinutes]);

  const creators = creatorsQuery.data?.items ?? [];

  return (
    <div className="space-y-4">
      {/* 头部操作 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">博主列表</h1>
          <p className="text-xs text-ink-muted">四平台统一监控 · 共 {creatorsQuery.data?.total ?? 0} 位</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-2 text-sm text-ink-secondary">
            <Toggle size="sm" checked={agg.globalEnabled} onChange={handleToggleGlobal} label="聚合监控总开关" />
            聚合监控
          </label>
          <button
            type="button"
            onClick={handlePollAll}
            disabled={!agg.globalEnabled || pollingAll}
            className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-surface px-3 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary-light disabled:cursor-not-allowed disabled:opacity-50"
            title={agg.globalEnabled ? '立即爬取全部平台' : '已关闭总开关'}
          >
            <RefreshCw className={`h-4 w-4 ${pollingAll ? 'animate-spin' : ''}`} />
            立即爬取全部
          </button>
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

      {/* 引擎在线状态（按流水线角色分组） */}
      <EngineHealthPanel />

      {/* 平台监控（启用开关 + 立即爬取 + 上次爬取时间） */}
      <PlatformPollPanel />

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
