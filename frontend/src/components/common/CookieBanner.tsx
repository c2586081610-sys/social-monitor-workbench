/** 凭据失效横幅（B1）：NEEDS_RELOGIN 红 / WARN 黄，任意页面可见，点击引导重新登录（P10）。 */
import { AlertTriangle, XCircle } from 'lucide-react';
import { useEffect } from 'react';
import { getCookieHealth } from '../../services/health';
import { useAsyncData, usePolling } from '../../hooks/useApi';
import { onReloginRequired } from '../../utils/events';
import { PLATFORM_LABEL } from '../../utils/constants';
import { useRelogin } from '../../state/relogin';
import type { CookieHealth } from '../../types/api.d';

function formatPlatforms(items: CookieHealth[]): string {
  return items.map((c) => PLATFORM_LABEL[c.platform] ?? c.platform).join('、');
}

export default function CookieBanner() {
  const { data, refetch } = useAsyncData(() => getCookieHealth(), []);
  const { open } = useRelogin();

  // 后台 30s 刷新一次健康度；后端报 2001 时立即刷新。
  usePolling(refetch, true, 30000);
  useEffect(() => onReloginRequired(() => refetch()), [refetch]);

  const items = data?.items ?? [];
  const relogin = items.filter((c) => c.status === 'NEEDS_RELOGIN');
  const warns = items.filter((c) => c.status === 'WARN');

  if (relogin.length === 0 && warns.length === 0) return null;

  return (
    <div className="space-y-2 px-4 pt-3">
      {relogin.length > 0 ? (
        <div
          className="flex items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger-light px-4 py-2.5 text-sm text-danger"
          role="alert"
        >
          <div className="flex items-center gap-2">
            <XCircle className="h-4 w-4 shrink-0" />
            <span>
              需要重新登录：<strong>{formatPlatforms(relogin)}</strong> 的凭据已失效，监控与任务已暂停，任务数据不会丢失。
            </span>
          </div>
          <button
            type="button"
            onClick={() => open(relogin[0].platform)}
            className="shrink-0 rounded-md border border-danger/40 bg-surface px-2.5 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger hover:text-white"
          >
            重新登录
          </button>
        </div>
      ) : null}
      {warns.length > 0 ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-light px-4 py-2.5 text-sm text-warning"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            凭据告警：{formatPlatforms(warns)} 状态异常（WARN），可能即将失效，请留意。
          </span>
        </div>
      ) : null}
    </div>
  );
}
