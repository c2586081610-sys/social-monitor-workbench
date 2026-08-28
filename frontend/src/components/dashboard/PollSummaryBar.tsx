/** 爬取摘要条：按平台展示最近一次爬取结果徽标（成功=新作品数 / 失败=detail 中文映射 / 未爬取）。 */
import { CheckCircle2, Clock, RefreshCw, XCircle } from 'lucide-react';
import type { ApiError } from '../../services/http';
import { PLATFORM_LABEL } from '../../utils/constants';
import type { PollStatusItem } from '../../types/api.d';

/** 失败 detail 到中文映射（no_rsshub_route 优先于 route 匹配，避免误判）。 */
export function mapPollDetail(detail: string | null): string {
  if (!detail) return '未知原因';
  if (detail.includes('no_rsshub_route')) return '无路由（抖音需 CDP）';
  if (detail.includes('route')) return '路由失效';
  if (detail.includes('CDP')) return 'CDP 未启用';
  return detail;
}

interface PollSummaryBarProps {
  items: PollStatusItem[];
  error?: ApiError | null;
  onRetry?: () => void;
}

export default function PollSummaryBar({ items, error, onRetry }: PollSummaryBarProps) {
  return (
    <section className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-muted">爬取摘要</h2>
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1 text-xs text-ink-muted transition-colors hover:text-primary"
          title="刷新爬取摘要"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </button>
      </div>
      {error ? (
        <p className="text-xs text-danger">爬取摘要获取失败：{error.message}</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-ink-muted">暂无爬取记录，点击「立即爬取全部」后此处会显示各平台结果。</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map((it) => {
            const ok = it.status === 'ok';
            const failed = it.status === 'fail' || it.status === 'failed';
            const Icon = ok ? CheckCircle2 : failed ? XCircle : Clock;
            const tone = ok
              ? 'bg-success-light text-success'
              : failed
                ? 'bg-warning-light text-warning'
                : 'bg-sidebar text-ink-muted';
            return (
              <span
                key={it.platform}
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}
              >
                <Icon className="h-3.5 w-3.5" />
                {PLATFORM_LABEL[it.platform] ?? it.platform}
                {ok
                  ? `上次 ${it.new_works ?? 0} 条新作品`
                  : failed
                    ? `失败：${mapPollDetail(it.detail)}`
                    : '未爬取'}
              </span>
            );
          })}
        </div>
      )}
    </section>
  );
}
