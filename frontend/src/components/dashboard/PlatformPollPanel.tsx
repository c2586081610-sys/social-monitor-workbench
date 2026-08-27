/** 平台监控行：每平台 = 启用开关（localStorage）+ 立即爬取（poll-now {platform}）+ 上次爬取时间（poll-status）。 */
import { useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import Toggle from '../common/Toggle';
import PlatformBadge from '../common/PlatformBadge';
import { pollNow, pollStatus } from '../../services/monitor';
import { useAsyncData, usePolling } from '../../hooks/useApi';
import { formatRelativeTime } from '../../utils/format';
import { readPlatformEnabled, setPlatformEnabled } from '../../utils/aggSettings';
import { PLATFORMS } from '../../utils/constants';
import type { Platform, PollStatusItem } from '../../types/api.d';

export default function PlatformPollPanel() {
  const statusQuery = useAsyncData(() => pollStatus(), []);
  // 每 30s 刷新各平台上次爬取时间
  usePolling(statusQuery.refetch, true, 30000);

  const statusByPlatform = useMemo(() => {
    const map: Record<string, PollStatusItem> = {};
    (statusQuery.data?.items ?? []).forEach((it) => {
      map[it.platform] = it;
    });
    return map;
  }, [statusQuery.data]);

  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>(() => {
    const map: Record<string, boolean> = {};
    PLATFORMS.forEach((p) => {
      map[p.value] = readPlatformEnabled(p.value);
    });
    return map;
  });

  const [pendingMap, setPendingMap] = useState<Record<string, boolean>>({});
  const [triggeredMap, setTriggeredMap] = useState<Record<string, boolean>>({});

  const handleToggle = (platform: string, value: boolean) => {
    setPlatformEnabled(platform, value);
    setEnabledMap((m) => ({ ...m, [platform]: value }));
  };

  const handleTrigger = async (platform: Platform) => {
    if (pendingMap[platform]) return;
    setPendingMap((m) => ({ ...m, [platform]: true }));
    try {
      await pollNow({ platform });
      setTriggeredMap((m) => ({ ...m, [platform]: true }));
      window.setTimeout(() => setTriggeredMap((m) => ({ ...m, [platform]: false })), 2000);
      statusQuery.refetch();
    } catch {
      /* 失败静默，下次可重试 */
    } finally {
      setPendingMap((m) => ({ ...m, [platform]: false }));
    }
  };

  return (
    <section className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-muted">平台监控</h2>
        <span className="text-xs text-ink-muted">关闭开关可停用该平台的单次爬取</span>
      </div>
      <div className="divide-y divide-line">
        {PLATFORMS.map((p) => {
          const enabled = enabledMap[p.value] ?? true;
          const item = statusByPlatform[p.value];
          const pending = Boolean(pendingMap[p.value]);
          const triggered = Boolean(triggeredMap[p.value]);
          return (
            <div key={p.value} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
              <div className="flex items-center gap-2.5">
                <PlatformBadge platform={p.value} />
                <Toggle
                  size="sm"
                  checked={enabled}
                  onChange={(v) => handleToggle(p.value, v)}
                  label={`${enabled ? '停用' : '启用'}${p.label}监控`}
                />
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-ink-muted">
                  上次爬取 <span className="font-mono text-ink-secondary">{formatRelativeTime(item?.last_poll_at)}</span>
                </span>
                <button
                  type="button"
                  onClick={() => handleTrigger(p.value as Platform)}
                  disabled={!enabled || pending}
                  className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-secondary transition-colors hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  title={enabled ? `立即爬取${p.label}` : '已停用，请先开启'}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${pending ? 'animate-spin' : ''}`} />
                  {triggered ? '已触发' : '立即爬取'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {statusQuery.error ? <p className="mt-2 text-xs text-danger">上次爬取时间获取失败：{statusQuery.error.message}</p> : null}
    </section>
  );
}
