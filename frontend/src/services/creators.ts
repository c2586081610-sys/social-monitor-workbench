/** 博主资源 API 封装（对齐 openapi: creators）。 */
import { buildQuery, deleteJson, getJson, patchJson, postJson } from './http';
import type {
  Creator,
  CreatorCreate,
  CreatorDetail,
  CreatorPage,
  CreatorUpdate,
  WorkPage,
} from '../types/api.d';

export interface ListCreatorsParams {
  group_id?: number;
  platform?: string;
  q?: string;
  page?: number;
  limit?: number;
}

export function listCreators(params: ListCreatorsParams = {}): Promise<CreatorPage> {
  return getJson<CreatorPage>(`/api/v1/creators${buildQuery(params)}`);
}

export function getCreator(id: number): Promise<CreatorDetail> {
  return getJson<CreatorDetail>(`/api/v1/creators/${id}`);
}

export function createCreator(body: CreatorCreate): Promise<Creator> {
  return postJson<Creator>('/api/v1/creators', body);
}

export function updateCreator(id: number, body: CreatorUpdate): Promise<Creator> {
  return patchJson<Creator>(`/api/v1/creators/${id}`, body);
}

export function deleteCreator(id: number): Promise<{ deleted: boolean }> {
  return deleteJson<{ deleted: boolean }>(`/api/v1/creators/${id}`);
}

export function listCreatorWorks(
  creatorId: number,
  params: { page?: number; limit?: number } = {},
): Promise<WorkPage> {
  return getJson<WorkPage>(`/api/v1/creators/${creatorId}/works${buildQuery(params)}`);
}
