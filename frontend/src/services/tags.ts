/** 标签资源 API 封装（对齐 openapi: tags）。 */
import { buildQuery, getJson } from './http';
import type { TagKind, TagList, WorkPage } from '../types/api.d';

export function listTags(kind?: TagKind): Promise<TagList> {
  return getJson<TagList>(`/api/v1/tags${buildQuery({ kind })}`);
}

export function listWorksByTag(
  tagName: string,
  params: { page?: number; limit?: number } = {},
): Promise<WorkPage> {
  const qs = buildQuery(params);
  return getJson<WorkPage>(`/api/v1/tags/${encodeURIComponent(tagName)}/works${qs}`);
}
