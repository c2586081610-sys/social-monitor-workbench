/**
 * 前后端共享类型契约 —— 由 docs/openapi-aggregator.yaml 对齐生成。
 * 变更必须先改 openapi-aggregator.yaml，再同步本文件。
 */

export type Platform = 'douyin' | 'bilibili' | 'xhs' | 'twitter' | 'wechat';

export type WorkStatus =
  | 'NEW'
  | 'QUEUED'
  | 'DOWNLOADING'
  | 'TRANSCRIBING'
  | 'FRAME_EXTRACTING'
  | 'NOTE_GENERATING'
  | 'DONE'
  | 'FAILED'
  | 'UNCLASSIFIED';

export type SourceType = 'monitor' | 'like' | 'favorite' | 'manual';

export type TagKind = 'big' | 'small';

export type CookieStatus = 'OK' | 'WARN' | 'NEEDS_RELOGIN' | 'UNKNOWN';

export type ComponentStatus = 'online' | 'offline' | 'degraded' | 'unknown';

export type StageName = 'parse' | 'download' | 'transcribe' | 'frames' | 'note';
export type StageStatus = 'pending' | 'running' | 'succeeded' | 'failed';

/** 统一响应包装 { code, data, message }；code=0 成功。 */
export interface Envelope<T> {
  code: number;
  data: T | null;
  message: string;
}

// ---------------- creators ----------------
export interface CreatorCreate {
  platform: Platform;
  name: string;
  profile_url: string;
  external_id: string;
  group_id?: number | null;
}

export interface CreatorUpdate {
  name?: string;
  group_id?: number | null;
  enabled?: boolean;
}

export interface Creator {
  id: number;
  group_id: number | null;
  platform: Platform;
  name: string;
  profile_url: string;
  external_id: string;
  enabled: boolean;
  last_poll_at: string | null;
  last_work_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreatorDetail extends Creator {
  recent_works: WorkSummary[];
}

export interface PageMeta {
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface CreatorPage extends PageMeta {
  items: Creator[];
}

// ---------------- works ----------------
export interface Work {
  id: number;
  creator_id: number | null;
  group_id: number | null;
  platform: Platform;
  external_id: string;
  title: string;
  url: string;
  published_at: string | null;
  downloaded_at: string | null;
  download_time_source: string | null;
  archive_check_status?: ArchiveCheckStatus | null;
  source_type: SourceType;
  status: WorkStatus;
  task_id: string | null;
  media_path: string | null;
  note_path: string | null;
  content_type: string;
  cover_url: string | null;
  frame_count: number;
  retry_count: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkSummary {
  id: number;
  title: string;
  status: WorkStatus;
  published_at: string | null;
  downloaded_at?: string | null;
  download_time_source?: string | null;
  archive_check_status?: ArchiveCheckStatus | null;
  /** 笔记已完成标记：note_path 存在 = 笔记已生成（后端 recent_works 当前未返回该字段，预留可选）。 */
  note_path?: string | null;
}

export interface TaskStage {
  stage: StageName;
  status: StageStatus;
  attempts: number;
  error: string | null;
}

export interface WorkTag {
  id: number;
  name: string;
  kind: TagKind;
  work_count?: number;
}

export interface WorkDetail extends Work {
  tags: WorkTag[];
  stages: TaskStage[];
  transcript_path: string | null;
  frame_manifest_path: string | null;
}

export interface WorkPage extends PageMeta {
  items: Work[];
}

// ---------------- local archive ----------------
export type ArchiveCheckStatus = 'verified' | 'needs_review' | 'conflict' | 'failed';
export type ArchiveSyncStatus = 'pending' | 'ready' | 'failed';
export type ArchiveJobType = 'scan' | 'refresh' | 'sync';
export type ArchiveJobStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed';
export type ArchiveTimeField = 'published_at' | 'downloaded_at';

export interface ArchiveFile {
  /** Stable identifier used by the authenticated media-file endpoint. */
  file_id: string;
  /** Path relative to this archive entry, never an absolute machine path. */
  relative_path: string;
  name: string;
  size_bytes: number;
  media_type?: string | null;
  sha256?: string | null;
}

export interface ArchiveEntry {
  id: number;
  root_key: string;
  relative_directory: string;
  work_id: number | null;
  platform: Platform;
  external_id: string | null;
  title: string;
  url: string | null;
  creator_id: number | null;
  creator_label: string | null;
  group_id: number | null;
  group_label: string | null;
  published_at: string | null;
  published_time_source: string | null;
  published_time_precision: string | null;
  downloaded_at: string | null;
  download_time_source: string | null;
  download_time_precision: string | null;
  metadata_checked_at: string | null;
  check_status: ArchiveCheckStatus;
  metadata_version: number;
  metadata: Record<string, unknown>;
  files: ArchiveFile[];
  sync_status: ArchiveSyncStatus;
  sync_error: string | null;
  synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArchiveRevision {
  id: number;
  archive_entry_id: number;
  before_values: Record<string, unknown>;
  after_values: Record<string, unknown>;
  source: string;
  changed_at: string;
}

export interface ArchiveEntryDetail extends ArchiveEntry {
  revisions: ArchiveRevision[];
}

export interface ArchivePage extends PageMeta {
  items: ArchiveEntry[];
}

export interface ArchiveRootPolicy {
  root_key: string;
  label: string;
  configured: boolean;
}

export interface ArchivePlatformOption {
  value: Platform;
  label: string;
}

export interface ArchivePolicy {
  timezone: 'Asia/Shanghai';
  directory_template: string;
  information_files: string[];
  collection_file_name: string;
  catalog_file_name: string;
  platforms: ArchivePlatformOption[];
  roots: ArchiveRootPolicy[];
}

export interface ArchiveJob {
  id: string;
  job_type: ArchiveJobType;
  status: ArchiveJobStatus;
  root_key: string | null;
  relative_directory: string | null;
  archive_entry_id: number | null;
  cursor: Record<string, unknown>;
  statistics: Record<string, unknown>;
  error: string | null;
  lease_owner: string | null;
  lease_expires_at: string | null;
  lease_attempts: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ArchiveFilters {
  platform?: Platform;
  creator_id?: number;
  group_id?: number;
  /** Repeated values are supported because one Work can have several local copies. */
  work_id?: number | number[];
  root_key?: string;
  q?: string;
  check_status?: ArchiveCheckStatus;
  time_field?: ArchiveTimeField;
  date_from?: string;
  date_to?: string;
  include_unknown_time?: boolean;
  unknown_time_only?: boolean;
  page?: number;
  limit?: number;
}

export interface ArchiveScanRequest {
  root_key: string;
  relative_directory?: string | null;
}

export interface ArchiveMetadataPatch {
  platform?: Platform;
  external_id?: string | null;
  title?: string;
  url?: string | null;
  creator_id?: number | null;
  creator_label?: string | null;
  group_id?: number | null;
  group_label?: string | null;
  published_at?: string | null;
  published_time_precision?: string | null;
}

export interface LocalMediaFile {
  name: string;
  size: number;
  path: string;
  url: string;
}

export interface WorkLocalView {
  id: number;
  title: string;
  platform: Platform;
  url: string | null;
  note_path: string | null;
  media_files: LocalMediaFile[];
  note_content: string | null;
}

export interface WorkListParams {
  group_id?: number;
  creator_id?: number;
  tag?: string;
  platform?: Platform;
  status?: WorkStatus;
  source_type?: SourceType;
  unclassified?: boolean;
  q?: string;
  page?: number;
  limit?: number;
}

export interface ClassifyRequest {
  group_id: number;
  tags?: string[];
  creator_id?: number | null;
}

export interface AnalyzeResult {
  note_pending: boolean;
  pending_file?: string;
}

export type LinkAnalysisMode = 'one_time' | 'monitor';

export interface LinkAnalysisCreate {
  url: string;
  platform: Exclude<Platform, 'wechat'>;
  external_id: string;
  mode?: LinkAnalysisMode;
}

export interface LinkAnalysisResult {
  work: Work;
  created: boolean;
  mode: LinkAnalysisMode;
}

export interface NoteCompletionRequest {
  note_path: string;
}

export interface FrameHit {
  term: string;
  action: 'increase' | 'decrease';
  weight: number;
}

export interface Frame {
  file: string;
  time_seconds: number;
  window_start: number | null;
  window_end: number | null;
  hits: FrameHit[];
  confidence: number;
}

export interface FrameList {
  semantic_aligned: boolean;
  fallback: boolean;
  items: Frame[];
}

// ---------------- groups ----------------
export interface Group {
  id: number;
  name: string;
  creator_count: number;
  created_at: string;
  updated_at: string;
}

export interface GroupList {
  items: Group[];
}

export interface DeleteResult {
  deleted: boolean;
  moved_creators?: number;
}

// ---------------- tags ----------------
export interface Tag {
  id: number;
  name: string;
  kind: TagKind;
  work_count: number;
}

export interface TagList {
  items: Tag[];
}

// ---------------- lexicon ----------------
export interface LexiconCreate {
  term: string;
  action: 'increase' | 'decrease';
  weight?: number;
  enabled?: boolean;
  platform_scope?: string | null;
  category?: string | null;
}

export interface LexiconUpdate {
  term?: string;
  action?: 'increase' | 'decrease';
  weight?: number;
  enabled?: boolean;
  platform_scope?: string | null;
  category?: string | null;
}

export interface LexiconItem {
  id: number;
  term: string;
  action: 'increase' | 'decrease';
  weight: number;
  enabled: boolean;
  platform_scope: string | null;
  category: string | null;
  created_at: string;
  updated_at: string;
}

export interface LexiconList {
  items: LexiconItem[];
}

// ---------------- health ----------------
export interface CookieHealth {
  platform: Platform;
  status: CookieStatus;
  last_checked_at: string | null;
  expires_at: string | null;
  note: string | null;
}

export interface CookieHealthList {
  items: CookieHealth[];
}

export interface SystemHealth {
  component:
    | 'aggregator'
    | 'monitor'
    | 'rsshub'
    | 'changedetection'
    | 'downloader'
    | 'transcriber'
    | 'workbuddy_pending';
  status: ComponentStatus;
  detail: string | null;
}

export interface SystemHealthList {
  items: SystemHealth[];
}

// ---------------- monitor ----------------
/** 立即爬取触发结果（POST /api/v1/monitor/poll-now）。 */
export interface PollNowResult {
  triggered: boolean;
  pid: number;
}

/** 各平台最近爬取记录（GET /api/v1/monitor/poll-status）。 */
export interface PollStatusItem {
  platform: Platform;
  last_poll_at: string | null;
  status: string;
  /** 本次爬取检测到的新作品数（status=ok 时有意义）。 */
  new_works: number;
  /** 失败原因（如 no_rsshub_route / CDP 未启用 / route 失效），成功时为 null。 */
  detail: string | null;
}

export interface PollStatusList {
  items: PollStatusItem[];
}
