import { CheckCircle2, Loader2, AlertTriangle, XCircle } from 'lucide-react';
import type { ArchiveJob, ArchivePolicy } from '../../types/api.d';
import { formatDateTime } from '../../utils/format';

const STATUS_LABEL: Record<ArchiveJob['status'], string> = {
  queued: '排队中',
  running: '进行中',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
};

const STAT_LABEL: Record<string, string> = {
  directories_total: '目录总数',
  directories_scanned: '已扫描目录',
  scanned: '已扫描',
  processed: '已处理',
  entries: '归档条目',
  indexed: '已索引',
  verified: '已核实',
  needs_review: '待核实',
  conflicts: '冲突',
  failed: '失败',
  errors: '错误',
};

interface ArchiveJobProgressProps {
  job: ArchiveJob;
  policy?: ArchivePolicy | null;
  onDismiss?: () => void;
}

function progressPercent(job: ArchiveJob): number | null {
  const values = { ...job.cursor, ...job.statistics };
  const currentKey = Object.keys(values).find((key) => /directories_scanned|processed|scanned|completed/i.test(key));
  const totalKey = Object.keys(values).find((key) => /directories_total|total/i.test(key));
  if (!currentKey || !totalKey) return null;
  const current = values[currentKey];
  const total = values[totalKey];
  if (typeof current !== 'number' || typeof total !== 'number' || total <= 0) return null;
  return Math.min(100, Math.max(0, Math.round((current / total) * 100)));
}

export default function ArchiveJobProgress({ job, policy, onDismiss }: ArchiveJobProgressProps) {
  const running = job.status === 'queued' || job.status === 'running';
  const rootLabel = job.root_key
    ? policy?.roots.find((root) => root.root_key === job.root_key)?.label ?? job.root_key
    : null;
  const Icon = running ? Loader2 : job.status === 'completed' ? CheckCircle2 : job.status === 'partial' ? AlertTriangle : XCircle;
  const tone = running
    ? 'border-info/40 bg-info-light text-info'
    : job.status === 'completed'
      ? 'border-success/40 bg-success-light text-success'
      : job.status === 'partial'
        ? 'border-warning/40 bg-warning-light text-warning'
        : 'border-danger/40 bg-danger-light text-danger';
  const percentage = progressPercent(job);
  const counters = Object.entries(job.statistics).filter(([, value]) => typeof value === 'number');

  return (
    <section className={`rounded-lg border p-4 ${tone}`} aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={`h-4 w-4 ${running ? 'animate-spin' : ''}`} />
        <h2 className="text-sm font-semibold">
          {job.job_type === 'scan' ? '归档扫描' : job.job_type === 'refresh' ? '平台信息刷新' : '信息文件同步'} · {STATUS_LABEL[job.status]}
        </h2>
        <span className="ml-auto font-mono text-[11px] opacity-75">{job.id}</span>
        {onDismiss && !running ? (
          <button type="button" onClick={onDismiss} className="rounded border border-current/30 px-2 py-0.5 text-xs hover:bg-surface/60">
            收起
          </button>
        ) : null}
      </div>

      {rootLabel ? (
        <p className="mt-2 text-xs">范围：{rootLabel}{job.relative_directory ? ` / ${job.relative_directory}` : ''}</p>
      ) : null}

      {percentage !== null ? (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs"><span>任务进度</span><span>{percentage}%</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-surface/70">
            <div className="h-full rounded-full bg-current transition-[width]" style={{ width: `${percentage}%` }} />
          </div>
        </div>
      ) : null}

      {counters.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {counters.map(([key, value]) => (
            <span key={key}>{STAT_LABEL[key] ?? key}：{String(value)}</span>
          ))}
        </div>
      ) : null}

      {job.error ? <p className="mt-3 rounded bg-surface/70 px-3 py-2 text-xs">{job.error}</p> : null}
      <p className="mt-2 text-[11px] opacity-75">
        更新于 {formatDateTime(job.updated_at)}{job.completed_at ? ` · 结束于 ${formatDateTime(job.completed_at)}` : ''}
      </p>
    </section>
  );
}
