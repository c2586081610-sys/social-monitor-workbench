/** P4 作品详情：三张状态卡（下载/转写/AI笔记）+ 打开 AI 笔记 + 失败原因 + 重试 + 关键帧 + 标签。 */
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Archive, ArrowLeft, AudioLines, ExternalLink, FileText, MonitorPlay, RotateCcw, Sparkles } from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import PlatformBadge from '../components/common/PlatformBadge';
import OpenNoteButton from '../components/work/OpenNoteButton';
import { ErrorState, LoadingState } from '../components/common/StateViews';
import { getWork, listWorkFrames, retryWork, analyzeWork } from '../services/works';
import { listAllArchiveEntriesByWork } from '../services/archive';
import { useAsyncData, useMutation, usePolling } from '../hooks/useApi';
import { stageProgress } from '../utils/stage';
import type { StageKey } from '../utils/stage';
import { formatArchiveDateTime, formatDateTime, formatSeconds } from '../utils/format';
import { RUNNING_STATUSES } from '../utils/constants';
import type { ArchiveCheckStatus, Frame } from '../types/api.d';
import { safeHttpUrl } from '../utils/urls';

const ARCHIVE_CHECK_LABEL: Record<ArchiveCheckStatus, string> = {
  verified: '已核实',
  needs_review: '待核实',
  conflict: '存在冲突',
  failed: '失败',
};

const STAGE_ICON: Record<StageKey, typeof FileText> = {
  download: FileText,
  transcribe: AudioLines,
  note: Sparkles,
};

export default function WorkDetailPage() {
  const { id } = useParams<{ id: string }>();
  const workId = Number(id);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const workQuery = useAsyncData(() => getWork(workId), [workId]);
  const framesQuery = useAsyncData(() => listWorkFrames(workId), [workId]);
  const archiveQuery = useAsyncData(() => listAllArchiveEntriesByWork(workId), [workId], Number.isInteger(workId) && workId > 0);
  const retryMutation = useMutation((wid: number) => retryWork(wid));
  const analyzeMutation = useMutation((wid: number) => analyzeWork(wid));

  const work = workQuery.data;
  const hasRunning = useMemo(() => (work ? RUNNING_STATUSES.has(work.status) : false), [work]);
  usePolling(() => {
    workQuery.refetch();
    framesQuery.refetch();
    archiveQuery.refetch();
  }, hasRunning && !workQuery.loading, 5000);

  if (workQuery.loading) return <LoadingState label="加载作品详情…" />;
  if (workQuery.error || !work) return <ErrorState message={workQuery.error?.message ?? '作品不存在'} onRetry={workQuery.refetch} />;

  const stages = stageProgress(work.status, work.stages);
  const failedError =
    work.status === 'FAILED'
      ? stages.find((s) => s.error)?.error ?? work.last_error
      : null;

  const handleRetry = async () => {
    setActionMsg(null);
    try {
      await retryMutation.run(work.id);
      setActionMsg('已重新入队，等待流水线执行…');
      workQuery.refetch();
    } catch (e) {
      setActionMsg(e instanceof Error ? `重试失败：${e.message}` : '重试失败');
    }
  };

  const handleAnalyze = async () => {
    setActionMsg(null);
    try {
      const res = await analyzeMutation.run(work.id);
      setActionMsg(res.note_pending ? '已生成素材就绪清单，等待 WorkBuddy 生成 AI 笔记（待 AI 生成）。' : '已触发分析。');
      workQuery.refetch();
    } catch (e) {
      setActionMsg(e instanceof Error ? `触发失败：${e.message}` : '触发失败');
    }
  };

  const frames = framesQuery.data?.items ?? [];
  const archiveEntries = archiveQuery.data ?? [];
  const archiveCounts = archiveEntries.reduce<Record<ArchiveCheckStatus, number>>((counts, entry) => {
    counts[entry.check_status] += 1;
    return counts;
  }, { verified: 0, needs_review: 0, conflict: 0, failed: 0 });
  const safeWorkUrl = safeHttpUrl(work.url);
  const downloadedLabel = work.download_time_source === 'not_required'
    ? '无需媒体下载'
    : work.downloaded_at
      ? `${formatDateTime(work.downloaded_at)}（来源 ${work.download_time_source ?? '未知'}）`
      : '下载时间未知';

  return (
    <div className="space-y-4">
      <Link to={work.creator_id ? `/creators/${work.creator_id}` : '/'} className="inline-flex items-center gap-1 text-xs text-ink-muted transition-colors hover:text-primary">
        <ArrowLeft className="h-3.5 w-3.5" />
        返回
      </Link>

      <div className="rounded-lg border border-line bg-surface p-4 shadow-card">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-base font-semibold text-ink">{work.title}</h1>
              <PlatformBadge platform={work.platform} />
              <StatusBadge status={work.status} notePath={work.note_path} />
            </div>
            <p className="mt-1 text-xs text-ink-muted">
              发布时间（北京时间）{formatDateTime(work.published_at)} · 下载完成时间（北京时间）{downloadedLabel} · 重试 {work.retry_count} 次
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {work.status === 'FAILED' ? (
              <button
                type="button"
                onClick={handleRetry}
                disabled={retryMutation.loading}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-60"
              >
                <RotateCcw className={`h-4 w-4 ${retryMutation.loading ? 'animate-spin' : ''}`} />
                重试
              </button>
            ) : null}
            <button
              type="button"
              onClick={handleAnalyze}
              disabled={analyzeMutation.loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar disabled:opacity-60"
            >
              <Sparkles className="h-4 w-4" />
              手动生成 AI 笔记
            </button>
            {safeWorkUrl ? (
              <a
                href={safeWorkUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar"
              >
                <ExternalLink className="h-4 w-4" />
                平台原作品
              </a>
            ) : null}
            <Link
              to={`/works/${workId}/local`}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar"
            >
              <MonitorPlay className="h-4 w-4" />
              本地视图
            </Link>
          </div>
        </div>

        {actionMsg ? <p className="mt-3 rounded-md bg-info-light px-3 py-2 text-sm text-info">{actionMsg}</p> : null}
        {failedError ? (
          <div className="mt-3 rounded-md bg-danger-light px-3 py-2 text-sm text-danger">
            失败原因：{failedError}
          </div>
        ) : null}
      </div>

      <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
        <div className="flex flex-wrap items-start gap-2">
          <Archive className="mt-0.5 h-4 w-4 text-primary" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-ink">本地归档核对</h2>
            <p className="mt-1 text-xs text-ink-muted">
              {archiveQuery.loading ? '正在读取与此作品关联的全部物理目录…' : archiveQuery.error ? '归档摘要暂不可用。' : archiveEntries.length === 0 ? '暂无关联归档目录。' : `关联 ${archiveEntries.length} 个物理目录：已核实 ${archiveCounts.verified} · 待核实 ${archiveCounts.needs_review} · 冲突 ${archiveCounts.conflict} · 失败 ${archiveCounts.failed}`}
            </p>
          </div>
          <Link to={`/archive?work_id=${work.id}`} className="rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-secondary hover:bg-sidebar">在本地归档中查看</Link>
        </div>
        {archiveQuery.error ? <p role="alert" className="mt-2 text-xs text-danger">{archiveQuery.error.message}</p> : null}
        {archiveEntries.length > 0 ? (
          <ul className="mt-3 divide-y divide-line rounded-md border border-line">
            {archiveEntries.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-start gap-2 px-3 py-2 text-xs">
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-ink">{entry.root_key} / {entry.relative_directory}</span>
                  <span className="mt-0.5 block text-ink-muted">
                    发布时间（北京时间）{formatArchiveDateTime(entry.published_at, entry.published_time_precision, '待核实')}
                    {' · '}下载完成时间（北京时间）{formatArchiveDateTime(entry.downloaded_at, entry.download_time_precision, entry.download_time_source === 'not_required' ? '无需媒体下载' : '未知')}
                    {' · '}{entry.files.length} 个登记媒体文件
                  </span>
                </span>
                <span className={`rounded-full px-2 py-0.5 ${entry.check_status === 'verified' ? 'bg-success-light text-success' : entry.check_status === 'failed' ? 'bg-danger-light text-danger' : 'bg-warning-light text-warning'}`}>
                  {ARCHIVE_CHECK_LABEL[entry.check_status]}
                </span>
                <span className="rounded-full bg-sidebar px-2 py-0.5 text-ink-secondary">{entry.sync_status === 'ready' ? '文件已同步' : entry.sync_status === 'failed' ? '同步失败' : '待同步'}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {/* 三张状态卡 */}
      <section className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {stages.map((s) => {
          const Icon = STAGE_ICON[s.key];
          const tone =
            s.state === 'done'
              ? 'border-success/40 bg-success-light text-success'
              : s.state === 'failed'
                ? 'border-danger/40 bg-danger-light text-danger'
                : s.state === 'active'
                  ? 'border-info/40 bg-info-light text-info'
                  : 'border-line bg-surface text-ink-muted';
          const label =
            s.state === 'done' ? '已完成' : s.state === 'failed' ? '失败' : s.state === 'active' ? '进行中' : '等待中';
          return (
            <div key={s.key} className={`rounded-lg border p-4 ${tone}`}>
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4" />
                <span className="text-sm font-semibold">{s.label}</span>
                <span className="ml-auto rounded-full bg-surface/70 px-2 py-0.5 text-xs">{label}</span>
              </div>
              {s.error ? <p className="mt-2 text-xs leading-5 opacity-90">{s.error}</p> : null}
            </div>
          );
        })}
      </section>

      {/* 标签 */}
      {work.tags.length > 0 ? (
        <section className="rounded-lg border border-line bg-surface p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-ink-muted">标签</h2>
          <div className="flex flex-wrap gap-2">
            {work.tags.map((t) => (
              <Link
                key={t.id}
                to={`/tags?tag=${encodeURIComponent(t.name)}`}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  t.kind === 'big' ? 'bg-primary-light text-primary' : 'bg-sidebar text-ink-secondary'
                }`}
              >
                #{t.name}
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {/* AI 笔记 */}
      <section className="rounded-lg border border-line bg-surface p-4">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-ink-muted">AI 笔记（Obsidian）</h2>
        {work.note_path ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="truncate-1 max-w-full font-mono text-xs text-ink-secondary">{work.note_path}</p>
            <OpenNoteButton notePath={work.note_path} />
          </div>
        ) : (
          <p className="text-xs text-ink-muted">
            {work.status === 'NOTE_GENERATING'
              ? 'AI 笔记未完成：素材就绪清单已生成，等待 WorkBuddy 处理（可点击「手动生成 AI 笔记」触发）。'
              : '尚未生成：完成下载/转写后可通过「手动生成 AI 笔记」触发。'}
          </p>
        )}
      </section>

      {/* 关键帧 */}
      <section className="rounded-lg border border-line bg-surface p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-muted">
            关键帧（{frames.length}）
          </h2>
          {framesQuery.data && framesQuery.data.fallback ? (
            <span className="rounded-full bg-warning-light px-2 py-0.5 text-xs text-warning">非语义对齐（兜底抽帧）</span>
          ) : null}
        </div>
        {framesQuery.loading ? (
          <LoadingState label="加载关键帧…" />
        ) : frames.length === 0 ? (
          <p className="text-xs text-ink-muted">暂无关键帧。转写稿命中词库后将按语义时间窗口抽取画面。</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {frames.map((f: Frame, i) => (
              <div key={`${f.file}-${i}`} className="rounded-md border border-line bg-surface p-2">
                <div className="flex h-20 items-center justify-center rounded bg-sidebar text-xs text-ink-muted">帧 {i + 1}</div>
                <p className="mt-1.5 font-mono text-[11px] text-ink-secondary">@{formatSeconds(f.time_seconds)}</p>
                {f.hits.length > 0 ? (
                  <p className="truncate-1 text-[11px] text-primary">命中：{f.hits.map((h) => h.term).join('、')}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
