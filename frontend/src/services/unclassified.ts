/** 待分类队列 API 封装（对齐 openapi: unclassified）。 */
import { buildQuery, getJson } from './http';
import type { WorkPage } from '../types/api.d';

export function listUnclassified(params: { page?: number; limit?: number } = {}): Promise<WorkPage> {
  return getJson<WorkPage>(`/api/v1/unclassified${buildQuery(params)}`);
}
