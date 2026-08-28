/** 平台监控（一行 chips）：每平台 = 平台名（短）+ 启用开关 + 上次爬取相对时间 + 立即爬取图标按钮。 */
import { useMemo, useState } from 'react';
import { CheckCircle2, RefreshCw } from 'lucide-react';
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
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 text-xs font-semibold uppercase tracking-widest text-ink-muted">平台监控</h2>
        {PLATFORMS.map((p) => {
          const enabled = enabledMap[p.value] ?? true;
          const item = statusByPlatform[p.value];
          const pending = Boolean(pendingMap[p.value]);
          const triggered = Boolean(triggeredMap[p.value]);
          return (
            <div
              key={p.value}
              className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-2 py-1"
              title={`${p.label} · 上次爬取 ${item?.last_poll_at ? formatRelativeTime(item.last_poll_at) : '尚未爬取'}`}
            >
              <PlatformBadge platform={p.value} />
              <Toggle
                size="sm"
                checked={enabled}
                onChange={(v) => handleToggle(p.value, v)}
                label={`${enabled ? '停用' : '启用'}${p.label}监控`}
              />
              <span className="min-w-0 text-[11px] leading-none text-ink-muted">
                {item?.last_poll_at ? formatRelativeTime(item.last_poll_at) : '未爬取'}
              </span>
              <button
                type="button"
                onClick={() => handleTrigger(p.value as Platform)}
                disabled={!enabled || pending}
                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-secondary transition-colors hover:bg-sidebar hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                title={enabled ? `立即爬取${p.label}` : '已停用，请先开启'}
              >
                {triggered ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                ) : (
                  <RefreshCw className={`h-3.5 w-3.5 ${pending ? 'animate-spin' : ''}`} />
                )}
              </button>
            </div>
          );
        })}
      </div>
      {statusQuery.error ? <p className="mt-2 text-xs text-danger">上次爬取时间获取失败：{statusQuery.error.message}</p> : null}
    </section>
  );
}
