/** 页面三态：Loading / Empty / Error（禁 AI 模板味文案）。 */
import { AlertCircle, Inbox, Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

export function LoadingState({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-ink-muted">
      <Loader2 className="h-6 w-6 animate-spin text-primary" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, hint, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-sidebar text-ink-muted">
        {icon ?? <Inbox className="h-5 w-5" />}
      </span>
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint ? <p className="max-w-sm text-xs leading-5 text-ink-muted">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-danger/30 bg-danger-light px-6 py-10 text-center">
      <AlertCircle className="h-6 w-6 text-danger" />
      <p className="text-sm text-danger">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-danger/40 bg-surface px-3 py-1.5 text-sm text-danger transition-colors hover:bg-danger hover:text-white"
        >
          重试
        </button>
      ) : null}
    </div>
  );
}
