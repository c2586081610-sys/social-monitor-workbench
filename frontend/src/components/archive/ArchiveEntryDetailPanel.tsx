import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, ExternalLink, FileText, Pencil, RefreshCw, Save, X } from 'lucide-react';
import { ErrorState, LoadingState } from '../common/StateViews';
import { useAsyncData, usePolling } from '../../hooks/useApi';
import {
  exportArchiveEntryCsv,
  getArchiveEntry,
  patchArchiveMetadata,
  readArchiveMedia,
  refreshArchiveEntry,
  retryArchiveSync,
} from '../../services/archive';
import type {
  ArchiveEntryDetail,
  ArchiveJob,
  ArchiveMetadataPatch,
  ArchivePlatformOption,
} from '../../types/api.d';
import { formatArchiveDateTime, formatBytes, formatDateTime, fromBeijingDateInput, toBeijingDateInput, toBeijingDateTimeInput } from '../../utils/format';
import { safeHttpUrl } from '../../utils/urls';

type Precision = 'day' | 'minute' | 'second';

interface ArchiveEntryDetailPanelProps {
  entryId: number;
  platformOptions: ArchivePlatformOption[];
  activeJob?: ArchiveJob | null;
  onClose: () => void;
  jobLaunchBlocked: boolean;
  beginJobLaunch: () => boolean;
  endJobLaunch: () => void;
  onJobStarted: (job: ArchiveJob) => void;
  onChanged: () => void;
}

interface MetadataDraft {
  platform: string;
  externalId: string;
  title: string;
  url: string;
  creatorId: string;
  creatorLabel: string;
  groupId: string;
  groupLabel: string;
  publishedInput: string;
  precision: Precision;
  publishedTouched: boolean;
  precisionNeedsInput: boolean;
}

const CHECK_LABEL: Record<string, string> = {
  verified: '已核实',
  needs_review: '待核实',
  conflict: '存在冲突',
  failed: '核对失败',
};

const SYNC_LABEL: Record<string, string> = { pending: '待同步', ready: '已同步', failed: '同步失败' };

function precisionChoice(value?: string | null): Precision {
  const normalized = value?.trim().toLowerCase();
  if (normalized === 'day' || normalized === 'date' || normalized === '日') return 'day';
  if (normalized === 'second' || normalized === 'seconds' || normalized === '秒') return 'second';
  return 'minute';
}

function toDraft(entry: ArchiveEntryDetail): MetadataDraft {
  const precision = precisionChoice(entry.published_time_precision);
  const publishedInput = !entry.published_at
    ? ''
    : precision === 'day'
      ? toBeijingDateInput(entry.published_at)
      : toBeijingDateTimeInput(entry.published_at, precision === 'second');
  return {
    platform: entry.platform,
    externalId: entry.external_id ?? '',
    title: entry.title,
    url: entry.url ?? '',
    creatorId: entry.creator_id === null ? '' : String(entry.creator_id),
    creatorLabel: entry.creator_label ?? '',
    groupId: entry.group_id === null ? '' : String(entry.group_id),
    groupLabel: entry.group_label ?? '',
    publishedInput,
    precision,
    publishedTouched: false,
    precisionNeedsInput: false,
  };
}

function convertDraftPrecision(input: string, from: Precision, to: Precision): { value: string; needsInput: boolean } {
  if (!input) return { value: '', needsInput: false };
  if (from === to) return { value: input, needsInput: false };
  const date = input.split('T')[0];
  if (to === 'day') return { value: date, needsInput: false };
  if (from === 'day') {
    return { value: to === 'minute' ? `${date}T00:00` : `${date}T00:00:00`, needsInput: true };
  }
  if (to === 'second' && from === 'minute') return { value: `${input}:00`, needsInput: true };
  if (to === 'minute' && from === 'second') return { value: input.slice(0, 16), needsInput: false };
  return { value: input, needsInput: false };
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function humanPrecision(precision?: string | null): string {
  if (!precision) return '精度未知';
  const normalized = precision.trim().toLowerCase();
  if (normalized === 'day' || normalized === 'date' || normalized === '日') return '日';
  if (normalized === 'minute' || normalized === '分钟' || normalized === '分') return '分钟';
  if (normalized === 'second' || normalized === 'seconds' || normalized === '秒') return '秒';
  return precision;
}

function safeFilePreviewType(mediaType?: string | null): 'image' | 'video' | 'audio' | null {
  if (!mediaType) return null;
  if (mediaType.startsWith('image/')) return 'image';
  if (mediaType.startsWith('video/')) return 'video';
  if (mediaType.startsWith('audio/')) return 'audio';
  return null;
}

function revisionChangedKeys(revision: ArchiveEntryDetail['revisions'][number]): string[] {
  return Object.keys(revision.after_values).filter(
    (key) => JSON.stringify(revision.before_values[key]) !== JSON.stringify(revision.after_values[key]),
  );
}

export default function ArchiveEntryDetailPanel({
  entryId,
  platformOptions,
  activeJob,
  onClose,
  jobLaunchBlocked,
  beginJobLaunch,
  endJobLaunch,
  onJobStarted,
  onChanged,
}: ArchiveEntryDetailPanelProps) {
  const entryQuery = useAsyncData(() => getArchiveEntry(entryId), [entryId]);
  const entry = entryQuery.data;
  const [awaitingPendingSync, setAwaitingPendingSync] = useState(false);
  usePolling(entryQuery.refetch, entry?.sync_status === 'pending' || awaitingPendingSync, 2500);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<MetadataDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [busyFile, setBusyFile] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ fileId: string; url: string; mediaType: string; name: string } | null>(null);
  const mountedRef = useRef(false);
  const wasSyncPending = useRef(false);
  const pendingSyncRefresh = useRef(false);
  const safeUrl = useMemo(() => safeHttpUrl(entry?.url), [entry?.url]);
  const previewUrl = preview?.url;
  const entryJobRunning = Boolean(activeJob && activeJob.archive_entry_id === entryId && (activeJob.status === 'queued' || activeJob.status === 'running'));

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!activeJob || activeJob.archive_entry_id !== entryId) return;
    if (activeJob.status === 'completed' || activeJob.status === 'partial' || activeJob.status === 'failed') {
      entryQuery.refetch();
      onChanged();
    }
  }, [activeJob?.id, activeJob?.status, activeJob?.archive_entry_id, entryId]);

  useEffect(() => {
    if (entryQuery.loading || entryQuery.error || !entry) return;
    const pending = entry?.sync_status === 'pending';
    if (pendingSyncRefresh.current) {
      pendingSyncRefresh.current = false;
      if (!pending) {
        setAwaitingPendingSync(false);
        wasSyncPending.current = false;
        onChanged();
        return;
      }
      setAwaitingPendingSync(false);
    }
    if (wasSyncPending.current && !pending) {
      setAwaitingPendingSync(false);
      onChanged();
    }
    wasSyncPending.current = pending;
  }, [entry?.id, entry?.sync_status, entryQuery.loading, entryQuery.error]);

  const startEditing = () => {
    if (!entry) return;
    setDraft(toDraft(entry));
    setFormError(null);
    setActionError(null);
    setEditing(true);
  };

  const submitMetadata = async () => {
    if (!entry || !draft || busyAction) return;
    setFormError(null);
    const title = draft.title.trim();
    if (!title) return setFormError('标题不能为空。');
    const creatorId = draft.creatorId.trim() ? Number(draft.creatorId) : null;
    const groupId = draft.groupId.trim() ? Number(draft.groupId) : null;
    if (creatorId !== null && (!Number.isInteger(creatorId) || creatorId < 1)) return setFormError('博主 ID 必须是正整数或留空。');
    if (groupId !== null && (!Number.isInteger(groupId) || groupId < 1)) return setFormError('分组 ID 必须是正整数或留空。');
    const url = draft.url.trim();
    if (url && !safeHttpUrl(url)) return setFormError('平台链接必须使用 http 或 https。');
    const publishedAt = draft.publishedInput
      ? fromBeijingDateInput(draft.publishedInput, draft.precision)
      : null;
    if (draft.publishedInput && !publishedAt) return setFormError('发布时间格式无效。');

    const body: ArchiveMetadataPatch = {};
    const externalId = draft.externalId.trim() || null;
    const creatorLabel = draft.creatorLabel.trim() || null;
    const groupLabel = draft.groupLabel.trim() || null;
    if (draft.platform !== entry.platform) body.platform = draft.platform as ArchiveMetadataPatch['platform'];
    if (externalId !== (entry.external_id ?? null)) body.external_id = externalId;
    if (title !== entry.title) body.title = title;
    if ((url || null) !== (entry.url ?? null)) body.url = url || null;
    if (creatorId !== entry.creator_id) body.creator_id = creatorId;
    if (creatorLabel !== (entry.creator_label ?? null)) body.creator_label = creatorLabel;
    if (groupId !== entry.group_id) body.group_id = groupId;
    if (groupLabel !== (entry.group_label ?? null)) body.group_label = groupLabel;
    if (draft.publishedTouched) {
      if (draft.precisionNeedsInput) return setFormError('请重新输入与所选精度一致的发布时间；切换到更高精度时不会自动补造时间。');
      const precision = publishedAt ? draft.precision : null;
      if (publishedAt !== entry.published_at || precision !== (entry.published_time_precision ?? null)) {
        body.published_at = publishedAt;
        body.published_time_precision = precision;
      }
    }
    if (Object.keys(body).length === 0) return setFormError('没有检测到字段变化。');

    setBusyAction('metadata');
    setActionError(null);
    try {
      const updatedEntry = await patchArchiveMetadata(entry.id, body);
      setEditing(false);
      setDraft(null);
      if (updatedEntry.sync_status === 'pending') {
        pendingSyncRefresh.current = true;
        setAwaitingPendingSync(true);
      }
      entryQuery.refetch();
      if (updatedEntry.sync_status !== 'pending') onChanged();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '保存修正失败');
    } finally {
      setBusyAction(null);
    }
  };

  const runJobAction = async (kind: 'refresh' | 'sync') => {
    if (!entry || busyAction || jobLaunchBlocked || entryJobRunning || editing || !beginJobLaunch()) return;
    setBusyAction(kind);
    setActionError(null);
    try {
      const job = kind === 'refresh'
        ? await refreshArchiveEntry(entry.id)
        : await retryArchiveSync(entry.id);
      onJobStarted(job);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '任务创建失败');
    } finally {
      setBusyAction(null);
      endJobLaunch();
    }
  };

  const exportCsv = async () => {
    if (!entry || busyAction) return;
    setBusyAction('csv');
    setActionError(null);
    try {
      const blob = await exportArchiveEntryCsv(entry.id);
      saveBlob(blob, `归档-${entry.id}-作品信息.csv`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'CSV 导出失败');
    } finally {
      setBusyAction(null);
    }
  };

  const handleFile = async (fileId: string, action: 'preview' | 'download', name: string, mediaType?: string | null) => {
    if (!entry || busyFile) return;
    setBusyFile(`${fileId}:${action}`);
    setActionError(null);
    try {
      const blob = await readArchiveMedia(entry.id, fileId);
      if (action === 'download') {
        saveBlob(blob, name);
      } else {
        const url = URL.createObjectURL(blob);
        if (!mountedRef.current) {
          URL.revokeObjectURL(url);
          return;
        }
        setPreview({ fileId, url, mediaType: mediaType ?? blob.type, name });
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '读取媒体失败');
    } finally {
      setBusyFile(null);
    }
  };

  if (entryQuery.loading) return <div className="rounded-lg border border-line bg-surface p-4"><LoadingState label="加载归档详情…" /></div>;
  if (entryQuery.error || !entry) return <div className="rounded-lg border border-line bg-surface p-4"><ErrorState message={entryQuery.error?.message ?? '归档记录不存在'} onRetry={entryQuery.refetch} /></div>;

  return (
    <section className="space-y-4 rounded-lg border border-primary/30 bg-surface p-4 shadow-card" aria-labelledby="archive-detail-title">
      <div className="flex flex-wrap items-center gap-2">
        <FileText className="h-4 w-4 text-primary" />
        <h2 id="archive-detail-title" className="min-w-0 flex-1 text-sm font-semibold text-ink">归档详情 · #{entry.id}</h2>
        <button type="button" onClick={onClose} className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-secondary hover:bg-sidebar">
          <X className="h-3.5 w-3.5" />关闭
        </button>
      </div>

      <div className="rounded-md bg-sidebar/70 p-3">
        <div className="flex flex-wrap items-start gap-2">
          <h3 className="min-w-0 flex-1 text-sm font-semibold text-ink">{entry.title}</h3>
          <span className="rounded-full bg-surface px-2 py-0.5 text-xs text-ink-secondary">
            核对：{CHECK_LABEL[entry.check_status] ?? entry.check_status}
          </span>
          <span className="rounded-full bg-surface px-2 py-0.5 text-xs text-ink-secondary">
            信息文件：{SYNC_LABEL[entry.sync_status] ?? entry.sync_status}
          </span>
        </div>
        <div className="mt-2 grid gap-2 text-xs text-ink-secondary sm:grid-cols-2">
          <p>平台：{platformOptions.find((item) => item.value === entry.platform)?.label ?? entry.platform}</p>
          <p>作品 ID：{entry.external_id ?? '未知'}</p>
          <p>博主：{entry.creator_label ?? '未知'}{entry.creator_id ? `（#${entry.creator_id}）` : ''}</p>
          <p>分组：{entry.group_label ?? '未知'}{entry.group_id ? `（#${entry.group_id}）` : ''}</p>
          <p>
            发布时间：{formatArchiveDateTime(entry.published_at, entry.published_time_precision, '发布时间待核实')}
            {' · '}{humanPrecision(entry.published_time_precision)} · 来源：{entry.published_time_source ?? '未知'}
          </p>
          <p>
            下载完成：{formatArchiveDateTime(entry.downloaded_at, entry.download_time_precision, entry.download_time_source === 'not_required' ? '无需媒体下载' : '下载时间未知')}
            {' · '}{humanPrecision(entry.download_time_precision)} · 来源：{entry.download_time_source ?? '未知'}
          </p>
          <p>核对状态更新时间：{formatDateTime(entry.metadata_checked_at)}</p>
          <p>信息文件状态：{entry.sync_error ? `失败：${entry.sync_error}` : entry.synced_at ? `最近同步 ${formatDateTime(entry.synced_at)}` : '尚无成功同步记录'}</p>
        </div>
        {entry.sync_status === 'pending' ? (
          <p role="status" className="mt-2 rounded bg-info-light px-3 py-2 text-xs text-info">
            修正后的信息文件正在排队同步；本页会自动更新状态。此同步不会替换当前跟踪的归档任务。
          </p>
        ) : null}
        <div className="mt-3 rounded border border-line bg-surface px-3 py-2">
          <p className="text-[11px] text-ink-muted">归档位置（相对路径）</p>
          <p className="mt-1 break-all font-mono text-xs text-ink-secondary">{entry.root_key} / {entry.relative_directory}</p>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {safeUrl ? (
            <a href={safeUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-secondary hover:bg-surface">
              <ExternalLink className="h-3.5 w-3.5" />打开原作品
            </a>
          ) : <span className="text-xs text-ink-muted">平台链接未知或不是安全的 HTTP(S) 链接</span>}
          <button type="button" onClick={exportCsv} disabled={Boolean(busyAction)} className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-secondary hover:bg-surface disabled:opacity-50">
            <Download className="h-3.5 w-3.5" />{busyAction === 'csv' ? '导出中…' : '下载作品 CSV'}
          </button>
          <button type="button" onClick={() => runJobAction('refresh')} disabled={Boolean(busyAction) || jobLaunchBlocked || entryJobRunning || editing} className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-secondary hover:bg-surface disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${busyAction === 'refresh' || (entryJobRunning && activeJob?.job_type === 'refresh') ? 'animate-spin' : ''}`} />{entryJobRunning && activeJob?.job_type === 'refresh' ? '刷新任务进行中' : '刷新平台信息'}
          </button>
          <button type="button" onClick={() => runJobAction('sync')} disabled={Boolean(busyAction) || jobLaunchBlocked || entryJobRunning || editing} className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-secondary hover:bg-surface disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${busyAction === 'sync' || (entryJobRunning && activeJob?.job_type === 'sync') ? 'animate-spin' : ''}`} />{entryJobRunning && activeJob?.job_type === 'sync' ? '同步任务进行中' : '重试信息文件同步'}
          </button>
          <button type="button" onClick={editing ? () => { setEditing(false); setDraft(null); setFormError(null); } : startEditing} disabled={Boolean(busyAction) || (entryJobRunning && !editing)} className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1.5 text-xs text-white hover:bg-primary-hover disabled:opacity-50">
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}{editing ? '取消修正' : '人工修正'}
          </button>
        </div>
      </div>

      {actionError ? <p role="alert" className="rounded bg-danger-light px-3 py-2 text-xs text-danger">{actionError}</p> : null}

      {editing && draft ? (
        <form className="space-y-3 rounded-md border border-line p-3" onSubmit={(event) => { event.preventDefault(); void submitMetadata(); }}>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-muted">修正归档元数据</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-xs text-ink-secondary">平台
              <select value={draft.platform} onChange={(event) => setDraft({ ...draft, platform: event.target.value })} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                {!platformOptions.some((option) => option.value === entry.platform) ? <option value={entry.platform}>{entry.platform}</option> : null}
                {platformOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">作品 ID
              <input value={draft.externalId} onChange={(event) => setDraft({ ...draft, externalId: event.target.value })} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary sm:col-span-2">标题
              <input required value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary sm:col-span-2">平台原作品 URL（留空表示未知）
              <input type="url" value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="https://…" className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">博主 ID
              <input inputMode="numeric" value={draft.creatorId} onChange={(event) => setDraft({ ...draft, creatorId: event.target.value })} placeholder="留空表示未关联" className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">博主名称
              <input value={draft.creatorLabel} onChange={(event) => setDraft({ ...draft, creatorLabel: event.target.value })} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">分组 ID
              <input inputMode="numeric" value={draft.groupId} onChange={(event) => setDraft({ ...draft, groupId: event.target.value })} placeholder="留空表示未关联" className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">分组名称
              <input value={draft.groupLabel} onChange={(event) => setDraft({ ...draft, groupLabel: event.target.value })} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">发布时间精度
              <select value={draft.precision} onChange={(event) => {
                const precision = event.target.value as Precision;
                const converted = convertDraftPrecision(draft.publishedInput, draft.precision, precision);
                setDraft({
                  ...draft,
                  precision,
                  publishedInput: converted.value,
                  publishedTouched: true,
                  precisionNeedsInput: converted.needsInput,
                });
              }} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                <option value="day">仅日期</option><option value="minute">精确到分钟</option><option value="second">精确到秒</option>
              </select>
            </label>
            <label className="space-y-1 text-xs text-ink-secondary">发布时间（北京时间）
              <input
                type={draft.precision === 'day' ? 'date' : 'datetime-local'}
                step={draft.precision === 'second' ? 1 : undefined}
                value={draft.publishedInput}
                onChange={(event) => setDraft({ ...draft, publishedInput: event.target.value, publishedTouched: true, precisionNeedsInput: false })}
                className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink"
              />
            </label>
            {draft.precisionNeedsInput ? (
              <p role="status" className="sm:col-span-2 rounded bg-warning-light px-3 py-2 text-xs text-warning">
                当前草稿已按新精度转换，请重新确认并输入完整时间。更高精度缺少的部分不会自动当作真实时间。
              </p>
            ) : null}
          </div>
          <p className="text-[11px] text-ink-muted">只修改公开元数据和发布时间。下载完成时间来自真实下载记录，此处不可编辑。日期/分钟精度以单独字段保存，不补造秒级精度。</p>
          {formError ? <p role="alert" className="text-xs text-danger">{formError}</p> : null}
          <button type="submit" disabled={Boolean(busyAction)} className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs text-white hover:bg-primary-hover disabled:opacity-50">
            <Save className="h-3.5 w-3.5" />{busyAction === 'metadata' ? '保存中…' : '保存修正'}
          </button>
        </form>
      ) : null}

      <div className="rounded-md border border-line p-3">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-muted">已登记媒体（{entry.files.length}）</h3>
        {entry.files.length === 0 ? <p className="mt-2 text-xs text-ink-muted">此归档目录没有登记媒体文件。</p> : (
          <ul className="mt-2 divide-y divide-line">
            {entry.files.map((file) => {
              const previewType = safeFilePreviewType(file.media_type);
              return (
                <li key={file.file_id} className="flex flex-wrap items-center gap-2 py-2 text-xs">
                  <div className="min-w-0 flex-1">
                    <p className="break-all font-medium text-ink">{file.name}</p>
                    <p className="break-all text-ink-muted">{file.relative_path} · {formatBytes(file.size_bytes)} · {file.media_type ?? '媒体类型未知'}</p>
                    {file.sha256 ? <p className="break-all font-mono text-[10px] text-ink-muted">SHA-256 {file.sha256}</p> : null}
                  </div>
                  {previewType ? (
                    <button type="button" disabled={Boolean(busyFile)} onClick={() => void handleFile(file.file_id, 'preview', file.name, file.media_type)} className="rounded border border-line px-2 py-1 text-ink-secondary hover:bg-sidebar disabled:opacity-50">
                      {busyFile === `${file.file_id}:preview` ? '读取中…' : '预览'}
                    </button>
                  ) : null}
                  <button type="button" disabled={Boolean(busyFile)} onClick={() => void handleFile(file.file_id, 'download', file.name, file.media_type)} className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-ink-secondary hover:bg-sidebar disabled:opacity-50">
                    <Download className="h-3 w-3" />{busyFile === `${file.file_id}:download` ? '下载中…' : '下载'}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {preview ? (
          <div className="mt-3 rounded-md border border-line bg-sidebar p-3">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs text-ink-secondary">
              <span className="truncate">预览：{preview.name}</span>
              <button type="button" onClick={() => setPreview(null)} className="rounded border border-line px-2 py-1 hover:bg-surface">关闭预览</button>
            </div>
            {preview.mediaType.startsWith('image/') ? <img src={preview.url} alt={preview.name} className="max-h-[28rem] max-w-full rounded object-contain" /> : null}
            {preview.mediaType.startsWith('video/') ? <video src={preview.url} controls className="max-h-[28rem] w-full rounded" /> : null}
            {preview.mediaType.startsWith('audio/') ? <audio src={preview.url} controls className="w-full" /> : null}
          </div>
        ) : null}
      </div>

      <div className="rounded-md border border-line p-3">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-muted">人工修订记录（{entry.revisions.length}）</h3>
        {entry.revisions.length === 0 ? <p className="mt-2 text-xs text-ink-muted">暂无人工修订记录。</p> : (
          <ul className="mt-2 space-y-2">
            {entry.revisions.slice().reverse().map((revision) => (
              <li key={revision.id} className="rounded bg-sidebar px-3 py-2 text-xs text-ink-secondary">
                <p>{formatDateTime(revision.changed_at)} · 来源：{revision.source}</p>
                <p className="mt-1">修改字段：{revisionChangedKeys(revision).join('、') || '无字段差异'}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
