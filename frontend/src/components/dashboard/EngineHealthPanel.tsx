/** 引擎健康状态：按流水线角色分 3 组展示（后端 health/system items 数组不变，前端按 component 分组）。 */
import { useMemo } from 'react';
import { ToneBadge } from '../common/StatusBadge';
import { ErrorState, LoadingState } from '../common/StateViews';
import { getSystemHealth } from '../../services/health';
import { useAsyncData, usePolling } from '../../hooks/useApi';
import { SYSTEM_COMPONENT_LABEL, SYSTEM_COMPONENT_STATUS } from '../../utils/constants';
import type { ComponentStatus, SystemHealth } from '../../types/api.d';

const COMPONENT_TONE: Record<ComponentStatus, 'success' | 'danger' | 'warning' | 'neutral'> = {
  online: 'success',
  offline: 'danger',
  degraded: 'warning',
  unknown: 'neutral',
};

interface EngineGroup {
  title: string;
  desc: string;
  components: string[];
}

/** 流水线角色分组（与后端 component 命名对齐）。 */
const ENGINE_GROUPS: EngineGroup[] = [
  { title: '监测源', desc: '外部内容抓取与变更发现', components: ['rsshub', 'changedetection'] },
  { title: '处理引擎', desc: '监测调度、下载与转写流水线', components: ['monitor', 'downloader', 'transcriber'] },
  { title: '中枢与出口', desc: '聚合 API 与 AI 笔记对接', components: ['aggregator', 'workbuddy_pending'] },
];

export default function EngineHealthPanel() {
  const systemQuery = useAsyncData(() => getSystemHealth(), []);
  // 每 30s 刷新一次引擎健康度
  usePolling(systemQuery.refetch, true, 30000);

  const items = systemQuery.data?.items ?? [];

  const byComponent = useMemo(() => {
    const map: Record<string, SystemHealth> = {};
    items.forEach((s) => {
      map[s.component] = s;
    });
    return map;
  }, [items]);

  // 未落入任何分组的组件兜底展示，避免静默丢失
  const leftovers = items.filter((s) => !ENGINE_GROUPS.some((g) => g.components.includes(s.component)));

  return (
    <section className="rounded-lg border border-line bg-surface p-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-ink-muted">引擎在线状态</h2>
      {systemQuery.loading ? (
        <LoadingState label="检测中…" />
      ) : systemQuery.error ? (
        <ErrorState message={systemQuery.error.message} onRetry={systemQuery.refetch} />
      ) : items.length === 0 ? (
        <p className="text-xs text-ink-muted">暂无引擎信息</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {ENGINE_GROUPS.map((group) => {
            const groupItems = group.components.map((c) => byComponent[c]).filter((s): s is SystemHealth => Boolean(s));
            return (
              <div key={group.title} className="rounded-md border border-line bg-sidebar/50 p-3">
                <h3 className="text-sm font-medium text-ink">{group.title}</h3>
                <p className="mt-0.5 text-xs text-ink-muted">{group.desc}</p>
                {groupItems.length === 0 ? (
                  <p className="mt-2 text-xs text-ink-muted">暂无数据</p>
                ) : (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {groupItems.map((s) => (
                      <span
                        key={s.component}
                        title={s.detail ?? ''}
                        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-secondary"
                      >
                        <ToneBadge tone={COMPONENT_TONE[s.status]} label={SYSTEM_COMPONENT_STATUS[s.status] ?? s.status} />
                        {SYSTEM_COMPONENT_LABEL[s.component] ?? s.component}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {leftovers.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {leftovers.map((s) => (
            <span key={s.component} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-sidebar px-2.5 py-1 text-xs text-ink-secondary">
              <ToneBadge tone={COMPONENT_TONE[s.status]} label={SYSTEM_COMPONENT_STATUS[s.status] ?? s.status} />
              {SYSTEM_COMPONENT_LABEL[s.component] ?? s.component}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
