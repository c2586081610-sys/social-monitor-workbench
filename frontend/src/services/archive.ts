/** 本地归档 API：列表使用服务器分页，CSV/媒体使用带 Bearer 的原始响应。 */
import { buildQuery, getJson, patchJson, postJson, requestBlob } from './http';
import type {
  ArchiveEntry,
  ArchiveEntryDetail,
  ArchiveFilters,
  ArchiveJob,
  ArchiveMetadataPatch,
  ArchivePage,
  ArchivePolicy,
  ArchiveScanRequest,
} from '../types/api.d';

export type ArchiveListFilters = Omit<ArchiveFilters, 'page' | 'limit'>;

export function listArchiveEntries(params: ArchiveFilters = {}): Promise<ArchivePage> {
  return getJson<ArchivePage>(`/api/v1/archive${buildQuery(params)}`);
}

export function getArchivePolicy(): Promise<ArchivePolicy> {
  return getJson<ArchivePolicy>('/api/v1/archive/policy');
}

/** 导出全部匹配项；分页字段不属于导出筛选。 */
export function exportArchiveCsv(filters: ArchiveListFilters = {}): Promise<Blob> {
  return requestBlob(`/api/v1/archive/export.csv${buildQuery(filters)}`);
}

export function createArchiveScan(body: ArchiveScanRequest): Promise<ArchiveJob> {
  return postJson<ArchiveJob>('/api/v1/archive/scan', body);
}

export function getArchiveJob(jobId: string): Promise<ArchiveJob> {
  return getJson<ArchiveJob>(`/api/v1/archive/jobs/${encodeURIComponent(jobId)}`);
}

export function getArchiveEntry(id: number): Promise<ArchiveEntryDetail> {
  return getJson<ArchiveEntryDetail>(`/api/v1/archive/${id}`);
}

export function exportArchiveEntryCsv(id: number): Promise<Blob> {
  return requestBlob(`/api/v1/archive/${id}/info.csv`);
}

/** 只接收后端登记的稳定 file_id，不接受本地路径。 */
export function readArchiveMedia(id: number, fileId: string): Promise<Blob> {
  return requestBlob(`/api/v1/archive/${id}/files/${encodeURIComponent(fileId)}`);
}

export function refreshArchiveEntry(id: number): Promise<ArchiveJob> {
  return postJson<ArchiveJob>(`/api/v1/archive/${id}/refresh`);
}

export function patchArchiveMetadata(id: number, body: ArchiveMetadataPatch): Promise<ArchiveEntry> {
  return patchJson<ArchiveEntry>(`/api/v1/archive/${id}/metadata`, body);
}

export function retryArchiveSync(id: number): Promise<ArchiveJob> {
  return postJson<ArchiveJob>(`/api/v1/archive/${id}/sync`);
}

/** 拉取某个 Work 的所有物理归档目录，跨过单页上限直到服务端总数齐全。 */
export async function listAllArchiveEntriesByWork(workId: number): Promise<ArchiveEntry[]> {
  const limit = 200;
  const entries: ArchiveEntry[] = [];
  let page = 1;
  let total = Number.POSITIVE_INFINITY;

  while (entries.length < total) {
    const result = await listArchiveEntries({ work_id: workId, page, limit });
    entries.push(...result.items);
    total = result.total;
    if (result.items.length === 0 || !result.has_more) break;
    page += 1;
  }

  return entries;
}
