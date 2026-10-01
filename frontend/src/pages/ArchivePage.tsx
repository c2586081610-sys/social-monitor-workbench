/** 本地归档索引：筛选、全量导出、目录扫描和单条核对。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Archive, Download, Filter, FolderSearch, Search } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import ArchiveEntryDetailPanel from '../components/archive/ArchiveEntryDetailPanel';
import ArchiveJobProgress from '../components/archive/ArchiveJobProgress';
import Pagination from '../components/common/Pagination';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { useAsyncData, useMutation, usePolling } from '../hooks/useApi';
import { createArchiveScan, exportArchiveCsv, getArchiveJob, getArchivePolicy, listArchiveEntries } from '../services/archive';
import type { ArchiveListFilters } from '../services/archive';
import { listCreators } from '../services/creators';
import { listGroups } from '../services/groups';
import type { ArchiveCheckStatus, ArchiveEntry, ArchiveJob, ArchiveTimeField, Creator, Group } from '../types/api.d';
import { formatArchiveDateTime, formatBytes } from '../utils/format';
import { safeHttpUrl } from '../utils/urls';

const JOB_STORAGE_KEY = 'aggregator_archive_job_id';
const PAGE_LIMIT = 50;

type CheckFilter = ArchiveCheckStatus | '';

interface FilterDraft {
  platform: string;
  creatorId: string;
  groupId: string;
  rootKey: string;
  q: string;
  checkStatus: CheckFilter;
  timeField: ArchiveTimeField;
  dateFrom: string;
  dateTo: string;
  includeUnknownTime: boolean;
  unknownTimeOnly: boolean;
}

const CHECK_LABEL: Record<ArchiveCheckStatus, string> = {
  verified: '已核实',
  needs_review: '待核实',
  conflict: '存在冲突',
  failed: '失败',
};

const SYNC_LABEL: Record<string, string> = { pending: '待同步', ready: '已同步', failed: '同步失败' };

async function listAllCreators(): Promise<Creator[]> {
  const limit = 100;
  const first = await listCreators({ page: 1, limit });
  const pages = Math.ceil(first.total / limit);
  const later = await Promise.all(
    Array.from({ length: Math.max(0, pages - 1) }, (_, index) => listCreators({ page: index + 2, limit })),
  );
  return [first, ...later].flatMap((page) => page.items);
}

function relativePathIsSafe(path: string): boolean {
  if (!path.trim()) return true;
  if (/^(?:[a-z]:|[\\/])/i.test(path)) return false;
  return !path.split(/[\\/]+/).some((part) => part === '..');
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

function toListFilters(draft: FilterDraft, workId: number | null): ArchiveListFilters {
  return {
    ...(draft.platform ? { platform: draft.platform as ArchiveListFilters['platform'] } : {}),
    ...(draft.creatorId ? { creator_id: Number(draft.creatorId) } : {}),
    ...(draft.groupId ? { group_id: Number(draft.groupId) } : {}),
    ...(draft.rootKey ? { root_key: draft.rootKey } : {}),
    ...(workId ? { work_id: workId } : {}),
    ...(draft.q.trim() ? { q: draft.q.trim() } : {}),
    ...(draft.checkStatus ? { check_status: draft.checkStatus } : {}),
    time_field: draft.timeField,
    ...(draft.dateFrom ? { date_from: draft.dateFrom } : {}),
    ...(draft.dateTo ? { date_to: draft.dateTo } : {}),
    ...(draft.includeUnknownTime && !draft.unknownTimeOnly ? { include_unknown_time: true } : {}),
    ...(draft.unknownTimeOnly ? { unknown_time_only: true } : {}),
  };
}

function TimeValue({
  value,
  precision,
  source,
  unknown,
}: {
  value: string | null;
  precision: string | null;
  source: string | null;
  unknown: string;
}) {
  return (
    <span className="block text-xs text-ink-secondary">
      <span>{formatArchiveDateTime(value, precision, unknown)}</span>
      <span className="ml-1 text-[10px] text-ink-muted">{precision ? `精度 ${precision}` : '精度未知'} · 来源 {source ?? '未知'}</span>
    </span>
  );
}

function ArchiveEntryRow({
  entry,
  rootLabel,
  platformLabel,
  selected,
  onSelect,
}: {
  entry: ArchiveEntry;
  rootLabel: string;
  platformLabel: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const safeUrl = safeHttpUrl(entry.url);
  return (
    <article className={`rounded-lg border bg-surface p-3 shadow-card ${selected ? 'border-primary/50' : 'border-line'}`}>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="min-w-0 text-sm font-semibold text-ink">{entry.title || '（无标题）'}</h2>
            <span className="rounded-full bg-sidebar px-2 py-0.5 text-[11px] text-ink-secondary">{platformLabel}</span>
            <span className="rounded-full bg-info-light px-2 py-0.5 text-[11px] text-info">{CHECK_LABEL[entry.check_status]}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] ${entry.sync_status === 'ready' ? 'bg-success-light text-success' : entry.sync_status === 'failed' ? 'bg-danger-light text-danger' : 'bg-warning-light text-warning'}`}>
              {SYNC_LABEL[entry.sync_status] ?? entry.sync_status}
            </span>
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            {entry.creator_label ?? '博主未知'}{entry.creator_id ? ` · #${entry.creator_id}` : ''}
            {' · '}{entry.group_label ?? '未分组'}{entry.group_id ? ` · #${entry.group_id}` : ''}
            {' · '}{entry.external_id ?? '平台 ID 未知'}
          </p>
        </div>
        <button type="button" onClick={onSelect} aria-expanded={selected} className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-secondary transition-colors hover:bg-sidebar">
          {selected ? '收起详情' : '核对详情'}
        </button>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <div><p className="mb-0.5 text-[10px] uppercase tracking-wide text-ink-muted">发布时间（北京时间）</p><TimeValue value={entry.published_at} precision={entry.published_time_precision} source={entry.published_time_source} unknown="发布时间待核实" /></div>
        <div><p className="mb-0.5 text-[10px] uppercase tracking-wide text-ink-muted">下载完成时间（北京时间）</p><TimeValue value={entry.downloaded_at} precision={entry.download_time_precision} source={entry.download_time_source} unknown={entry.download_time_source === 'not_required' ? '无需媒体下载' : '下载时间未知'} /></div>
        <div className="min-w-0">
          <p className="mb-0.5 text-[10px] uppercase tracking-wide text-ink-muted">本地位置 · 相对路径</p>
          <p className="break-all font-mono text-[11px] text-ink-secondary" title={`${rootLabel} / ${entry.relative_directory}`}>{rootLabel} / {entry.relative_directory}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-2 text-[11px] text-ink-muted">
        <span>媒体 {entry.files.length} 个</span>
        {entry.files.slice(0, 4).map((file) => <span key={file.file_id} className="max-w-full break-all">{file.name}（{formatBytes(file.size_bytes)}）</span>)}
        {entry.files.length > 4 ? <span>及其他 {entry.files.length - 4} 个</span> : null}
        {safeUrl ? <a href={safeUrl} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-primary hover:underline">打开平台原链接</a> : <span className="ml-auto">平台链接未知或不是安全的 HTTP(S) 地址</span>}
      </div>
    </article>
  );
}

export default function ArchivePage() {
  const location = useLocation();
  const workIdFromUrl = useMemo(() => {
    const value = Number(new URLSearchParams(location.search).get('work_id'));
    return Number.isInteger(value) && value > 0 ? value : null;
  }, [location.search]);
  const initialDraft: FilterDraft = {
    platform: '', creatorId: '', groupId: '', rootKey: '', q: '', checkStatus: '',
    timeField: 'published_at', dateFrom: '', dateTo: '', includeUnknownTime: false, unknownTimeOnly: false,
  };
  const [draft, setDraft] = useState<FilterDraft>(initialDraft);
  const [appliedFilters, setAppliedFilters] = useState<ArchiveListFilters>(() => ({ time_field: 'published_at', ...(workIdFromUrl ? { work_id: workIdFromUrl } : {}) }));
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [scanRootKey, setScanRootKey] = useState('');
  const [relativeDirectory, setRelativeDirectory] = useState('');
  const [scanError, setScanError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(() => window.localStorage.getItem(JOB_STORAGE_KEY));
  const [jobLookupId, setJobLookupId] = useState(activeJobId);
  const [jobLaunchPending, setJobLaunchPending] = useState(false);
  const jobLaunchPendingRef = useRef(false);
  const persistedJobBlocksLaunchRef = useRef(false);
  const scanMutation = useMutation(({ root_key, relative_directory }: { root_key: string; relative_directory: string | null }) =>
    createArchiveScan({ root_key, relative_directory }),
  );

  const policyQuery = useAsyncData(() => getArchivePolicy(), []);
  const groupsQuery = useAsyncData(() => listGroups(), []);
  const creatorsQuery = useAsyncData(() => listAllCreators(), []);
  const filterKey = JSON.stringify(appliedFilters);
  const listQuery = useAsyncData(
    () => listArchiveEntries({ ...appliedFilters, page, limit: PAGE_LIMIT }),
    [page, filterKey],
  );
  const jobQuery = useAsyncData(() => getArchiveJob(activeJobId as string), [activeJobId], Boolean(activeJobId));
  const activeJob = jobQuery.data?.id === activeJobId ? jobQuery.data : null;
  const jobRunning = activeJob?.status === 'queued' || activeJob?.status === 'running';
  const savedJobHasKnownRunningStatus = jobQuery.data?.status === 'queued' || jobQuery.data?.status === 'running';
  const persistedJobBlocksLaunch = Boolean(activeJobId && (jobQuery.loading || jobQuery.error || !activeJob || jobRunning));
  persistedJobBlocksLaunchRef.current = persistedJobBlocksLaunch;
  const jobLaunchBlocked = persistedJobBlocksLaunch || jobLaunchPending;
  const beginJobLaunch = useCallback((): boolean => {
    if (jobLaunchPendingRef.current || persistedJobBlocksLaunchRef.current) return false;
    jobLaunchPendingRef.current = true;
    setJobLaunchPending(true);
    return true;
  }, []);
  const endJobLaunch = useCallback(() => {
    jobLaunchPendingRef.current = false;
    setJobLaunchPending(false);
  }, []);
  usePolling(jobQuery.refetch, Boolean(jobRunning), 1800);

  useEffect(() => {
    setJobLookupId(activeJobId);
  }, [activeJobId]);

  useEffect(() => {
    setAppliedFilters((current) => ({ ...current, work_id: workIdFromUrl ?? undefined }));
    setPage(1);
    if (workIdFromUrl) setSelectedId(null);
  }, [workIdFromUrl]);

  useEffect(() => {
    const roots = policyQuery.data?.roots ?? [];
    if (!scanRootKey && roots.length > 0) {
      setScanRootKey(roots.find((root) => root.configured)?.root_key ?? roots[0].root_key);
    }
  }, [policyQuery.data, scanRootKey]);

  useEffect(() => {
    if (!activeJob || jobRunning) return;
    if (window.localStorage.getItem(JOB_STORAGE_KEY) === activeJob.id) window.localStorage.removeItem(JOB_STORAGE_KEY);
    listQuery.refetch();
  }, [activeJob?.id, activeJob?.status]);

  const creators = creatorsQuery.data ?? [];
  const groups = groupsQuery.data?.items ?? [];
  const entries = listQuery.data?.items ?? [];
  const rootLabel = useCallback((rootKey: string) => policyQuery.data?.roots.find((root) => root.root_key === rootKey)?.label ?? rootKey, [policyQuery.data]);
  const refreshList = useCallback(() => listQuery.refetch(), [listQuery.refetch]);

  const setDraftValue = <K extends keyof FilterDraft>(key: K, value: FilterDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const applyFilters = () => {
    setFilterError(null);
    if (draft.dateFrom && draft.dateTo && draft.dateFrom > draft.dateTo) {
      setFilterError('结束日期不能早于开始日期。');
      return;
    }
    if (draft.creatorId && (!Number.isInteger(Number(draft.creatorId)) || Number(draft.creatorId) < 1)) {
      setFilterError('博主筛选值无效。');
      return;
    }
    if (draft.groupId && (!Number.isInteger(Number(draft.groupId)) || Number(draft.groupId) < 1)) {
      setFilterError('分组筛选值无效。');
      return;
    }
    setAppliedFilters(toListFilters(draft, workIdFromUrl));
    setPage(1);
    setSelectedId(null);
  };

  const exportAll = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await exportArchiveCsv(appliedFilters);
      saveBlob(blob, `本地归档-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : '全量 CSV 导出失败');
    } finally {
      setExporting(false);
    }
  };

  const startScan = async () => {
    setScanError(null);
    const root = policyQuery.data?.roots.find((item) => item.root_key === scanRootKey);
    if (!root || !root.configured) return setScanError('请选择当前可用的归档根目录。');
    if (!relativePathIsSafe(relativeDirectory)) return setScanError('子目录只能是根目录内的相对路径，不能包含盘符、绝对路径或 ..。');
    if (!beginJobLaunch()) return setScanError('已有归档任务正在恢复、启动或执行；请等到任务结束后再发起新任务。');
    try {
      const job = await scanMutation.run({ root_key: root.root_key, relative_directory: relativeDirectory.trim() || null });
      setActiveJobId(job.id);
      window.localStorage.setItem(JOB_STORAGE_KEY, job.id);
      persistedJobBlocksLaunchRef.current = true;
    } catch (error) {
      setScanError(error instanceof Error ? error.message : '扫描任务创建失败');
    } finally {
      endJobLaunch();
    }
  };

  const onJobStarted = (job: ArchiveJob) => {
    setActiveJobId(job.id);
    window.localStorage.setItem(JOB_STORAGE_KEY, job.id);
    persistedJobBlocksLaunchRef.current = true;
  };

  const clearActiveJob = () => {
    setActiveJobId(null);
    persistedJobBlocksLaunchRef.current = false;
    window.localStorage.removeItem(JOB_STORAGE_KEY);
  };

  const savedJobIsNotFound = jobQuery.error?.status === 404 && jobQuery.error.message === 'ARCHIVE_JOB_NOT_FOUND';
  const canClearSavedJob = savedJobIsNotFound;
  const scanButtonLabel = jobLaunchPending || scanMutation.loading
    ? '提交中…'
    : jobRunning
      ? '已有任务执行中'
      : jobLaunchBlocked && activeJobId
        ? jobQuery.error ? '先处理任务读取问题' : '正在恢复已保存任务'
        : '开始扫描';

  const selectTimeField = (timeField: ArchiveTimeField) => {
    setDraft((current) => ({ ...current, timeField, unknownTimeOnly: false }));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-2">
        <Archive className="mt-0.5 h-5 w-5 text-primary" />
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold text-ink">本地归档</h1>
          <p className="text-xs text-ink-muted">索引本机已登记目录，核对元数据并导出筛选结果。未知时间会保持未知；日期按北京时间筛选。</p>
          {workIdFromUrl ? <p className="mt-1 text-xs text-primary">当前限定关联作品 #{workIdFromUrl}</p> : null}
        </div>
        <button type="button" onClick={exportAll} disabled={exporting || listQuery.loading} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-50">
          <Download className="h-4 w-4" />{exporting ? '导出中…' : '导出全部匹配 CSV'}
        </button>
      </div>

      {exportError ? <p role="alert" className="rounded-md bg-danger-light px-3 py-2 text-sm text-danger">{exportError}</p> : null}

      <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
        <div className="mb-3 flex items-center gap-2">
          <Filter className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-ink">筛选归档记录</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-1 text-xs text-ink-secondary">平台
            <select value={draft.platform} onChange={(event) => setDraftValue('platform', event.target.value)} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              <option value="">全部平台</option>
              {(policyQuery.data?.platforms ?? []).map((platform) => <option key={platform.value} value={platform.value}>{platform.label}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">博主
            <select value={draft.creatorId} onChange={(event) => setDraftValue('creatorId', event.target.value)} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              <option value="">全部博主</option>
              {creators.map((creator) => <option key={creator.id} value={creator.id}>{creator.name} · {creator.platform}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">分组
            <select value={draft.groupId} onChange={(event) => setDraftValue('groupId', event.target.value)} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              <option value="">全部分组</option>
              {groups.map((group: Group) => <option key={group.id} value={group.id}>{group.name}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">归档根目录
            <select value={draft.rootKey} onChange={(event) => setDraftValue('rootKey', event.target.value)} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              <option value="">全部根目录</option>
              {(policyQuery.data?.roots ?? []).map((root) => <option key={root.root_key} value={root.root_key}>{root.label}{root.configured ? '' : '（当前不可用）'}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary sm:col-span-2">关键词
            <span className="relative block">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-ink-muted" />
              <input value={draft.q} onChange={(event) => setDraftValue('q', event.target.value)} placeholder="标题、作品 ID、链接、博主或分组" className="w-full rounded-md border border-line bg-surface py-2 pl-8 pr-2 text-sm text-ink" />
            </span>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">核对状态
            <select value={draft.checkStatus} onChange={(event) => setDraftValue('checkStatus', event.target.value as CheckFilter)} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              <option value="">全部状态</option>
              <option value="verified">已核实</option><option value="needs_review">待核实</option><option value="conflict">存在冲突</option><option value="failed">失败</option>
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">时间字段
            <select value={draft.timeField} onChange={(event) => selectTimeField(event.target.value as ArchiveTimeField)} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              <option value="published_at">发布时间</option><option value="downloaded_at">下载完成时间</option>
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">开始日期（北京时间）
            <input type="date" value={draft.dateFrom} disabled={draft.unknownTimeOnly} onChange={(event) => setDraft((current) => ({ ...current, dateFrom: event.target.value, unknownTimeOnly: false }))} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink disabled:opacity-50" />
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">结束日期（北京时间，含当天）
            <input type="date" value={draft.dateTo} disabled={draft.unknownTimeOnly} onChange={(event) => setDraft((current) => ({ ...current, dateTo: event.target.value, unknownTimeOnly: false }))} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink disabled:opacity-50" />
          </label>
        </div>

        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
          <label className="flex items-start gap-2 text-xs text-ink-secondary">
            <input type="checkbox" checked={draft.includeUnknownTime} disabled={draft.unknownTimeOnly || (!draft.dateFrom && !draft.dateTo)} onChange={(event) => setDraft((current) => ({ ...current, includeUnknownTime: event.target.checked, unknownTimeOnly: false }))} className="mt-0.5 accent-primary" />
            <span>日期筛选额外包含所选时间未知的条目</span>
          </label>
          <label className="flex items-start gap-2 text-xs text-ink-secondary">
            <input type="checkbox" checked={draft.unknownTimeOnly} onChange={(event) => setDraft((current) => ({ ...current, unknownTimeOnly: event.target.checked, includeUnknownTime: false, dateFrom: event.target.checked ? '' : current.dateFrom, dateTo: event.target.checked ? '' : current.dateTo }))} className="mt-0.5 accent-primary" />
            <span>只查看所选时间未知的条目</span>
          </label>
        </div>
        {filterError ? <p role="alert" className="mt-2 text-xs text-danger">{filterError}</p> : null}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" onClick={applyFilters} className="rounded-md bg-primary px-3 py-1.5 text-sm text-white hover:bg-primary-hover">应用筛选</button>
          <button type="button" onClick={() => { setDraft(initialDraft); setFilterError(null); setAppliedFilters({ time_field: 'published_at', ...(workIdFromUrl ? { work_id: workIdFromUrl } : {}) }); setPage(1); setSelectedId(null); }} className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary hover:bg-sidebar">清空筛选</button>
          {creatorsQuery.loading || groupsQuery.loading || policyQuery.loading ? <span className="text-xs text-ink-muted">正在读取筛选选项…</span> : null}
          {policyQuery.error ? <span className="text-xs text-danger">规则读取失败：{policyQuery.error.message}</span> : null}
          {creatorsQuery.error ? <span className="text-xs text-danger">博主筛选项读取失败：{creatorsQuery.error.message}</span> : null}
          {groupsQuery.error ? <span className="text-xs text-danger">分组筛选项读取失败：{groupsQuery.error.message}</span> : null}
        </div>
      </section>

      <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
        <div className="mb-3 flex items-center gap-2">
          <FolderSearch className="h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold text-ink">扫描已存在的归档目录</h2>
            <p className="text-xs text-ink-muted">扫描只建立索引任务，不会创建媒体下载任务。根目录由服务端配置，页面只提交根标识和可选相对目录。</p>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-[minmax(12rem,1fr)_2fr_auto] sm:items-end">
          <label className="space-y-1 text-xs text-ink-secondary">允许的根目录
            <select value={scanRootKey} onChange={(event) => setScanRootKey(event.target.value)} disabled={policyQuery.loading} className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
              {(policyQuery.data?.roots ?? []).map((root) => <option key={root.root_key} value={root.root_key} disabled={!root.configured}>{root.label} · {root.configured ? '可用' : '不可用'}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-ink-secondary">相对目录（可选）
            <input value={relativeDirectory} onChange={(event) => setRelativeDirectory(event.target.value)} placeholder="例：博主/作品目录；留空扫描整个根目录" className="w-full rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink" />
            <span className="block text-[10px] text-ink-muted">不要填写盘符、绝对路径或根目录之外的路径。</span>
          </label>
          <button type="button" onClick={() => void startScan()} disabled={jobLaunchBlocked || scanMutation.loading || !scanRootKey || !policyQuery.data?.roots.some((root) => root.root_key === scanRootKey && root.configured)} className="rounded-md bg-primary px-3 py-2 text-sm text-white hover:bg-primary-hover disabled:opacity-50">
            {scanButtonLabel}
          </button>
        </div>
        {scanError ? <p role="alert" className="mt-2 text-xs text-danger">{scanError}</p> : null}
      </section>

      {activeJobId && jobQuery.error ? (
        <div className="space-y-2">
          <ErrorState message={`读取已保存任务失败：${jobQuery.error.message}。读取成功前，新的归档任务会暂停。`} onRetry={jobQuery.refetch} />
          {canClearSavedJob ? (
            <div className="text-center">
              <button type="button" onClick={clearActiveJob} className="rounded-md border border-danger/40 px-3 py-1.5 text-xs text-danger hover:bg-danger-light">
                清除服务器已不存在的任务记录
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
      {activeJob ? <ArchiveJobProgress job={activeJob} policy={policyQuery.data} onDismiss={!jobRunning ? clearActiveJob : undefined} /> : jobQuery.loading && activeJobId ? <LoadingState label="恢复已保存的归档任务…新任务暂时暂停" /> : null}
      {activeJobId && jobLookupId === activeJobId && !activeJob && !jobQuery.loading && !jobQuery.error ? (
        <div role="alert" className="rounded-lg border border-warning/40 bg-warning-light p-3 text-xs text-warning">
          已保存任务 ID 与服务器返回记录不匹配。新任务已暂停。
          <button type="button" onClick={() => jobQuery.refetch()} className="ml-3 underline">重试读取</button>
          {!savedJobHasKnownRunningStatus ? <button type="button" onClick={clearActiveJob} className="ml-3 underline">清除无法恢复的任务记录</button> : null}
        </div>
      ) : null}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-ink">归档记录{listQuery.data ? ` · 共 ${listQuery.data.total} 条` : ''}</h2>
          {appliedFilters.unknown_time_only ? <span className="rounded-full bg-warning-light px-2 py-1 text-xs text-warning">仅显示时间未知</span> : null}
        </div>
        {listQuery.loading ? <LoadingState label="加载归档记录…" /> : listQuery.error ? <ErrorState message={listQuery.error.message} onRetry={listQuery.refetch} /> : entries.length === 0 ? (
          <EmptyState icon={<Archive className="h-5 w-5" />} title="没有符合条件的归档记录" hint="可调整筛选条件，或扫描一个已配置的本机归档根目录。未知时间不会被扫描时间替代。" />
        ) : (
          <>
            <div className="space-y-3">
              {entries.map((entry) => (
                <div key={entry.id} className="space-y-2">
                  <ArchiveEntryRow
                    entry={entry}
                    rootLabel={rootLabel(entry.root_key)}
                    platformLabel={policyQuery.data?.platforms.find((platform) => platform.value === entry.platform)?.label ?? entry.platform}
                    selected={selectedId === entry.id}
                    onSelect={() => setSelectedId((current) => current === entry.id ? null : entry.id)}
                  />
                  {selectedId === entry.id ? (
                    <ArchiveEntryDetailPanel
                      key={entry.id}
                      entryId={entry.id}
                      platformOptions={policyQuery.data?.platforms ?? []}
                      activeJob={activeJob}
                      onClose={() => setSelectedId(null)}
                      jobLaunchBlocked={jobLaunchBlocked}
                      beginJobLaunch={beginJobLaunch}
                      endJobLaunch={endJobLaunch}
                      onJobStarted={onJobStarted}
                      onChanged={refreshList}
                    />
                  ) : null}
                </div>
              ))}
            </div>
            <Pagination page={page} limit={PAGE_LIMIT} total={listQuery.data?.total ?? 0} onChange={setPage} />
          </>
        )}
      </section>
    </div>
  );
}
