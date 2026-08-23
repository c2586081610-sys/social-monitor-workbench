/** 分页控件：上一页/下一页 + 页码 + 总数。 */
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PaginationProps {
  page: number;
  limit: number;
  total: number;
  onChange: (page: number) => void;
}

export default function Pagination({ page, limit, total, onChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const start = (page - 1) * limit + 1;
  const end = Math.min(page * limit, total);

  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-ink-muted">
      <span>
        共 {total} 条 · 第 {start}–{end} 条
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-line text-ink-secondary transition-colors hover:bg-sidebar disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="上一页"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="px-2">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => onChange(page + 1)}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-line text-ink-secondary transition-colors hover:bg-sidebar disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="下一页"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
