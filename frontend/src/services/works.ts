/** 作品资源 API 封装（对齐 openapi: works）。 */
import { buildQuery, getJson, postJson } from './http';
import type {
  AnalyzeResult,
  ClassifyRequest,
  FrameList,
  Work,
  WorkDetail,
  WorkListParams,
  WorkLocalView,
  WorkPage,
} from '../types/api.d';

export function listWorks(params: WorkListParams = {}): Promise<WorkPage> {
  return getJson<WorkPage>(`/api/v1/works${buildQuery(params)}`);
}

export function getWork(id: number): Promise<WorkDetail> {
  return getJson<WorkDetail>(`/api/v1/works/${id}`);
}

export function getWorkLocalView(id: number): Promise<WorkLocalView> {
  return getJson<WorkLocalView>(`/api/v1/works/${id}/local-view`);
}

export function retryWork(id: number): Promise<Work> {
  return postJson<Work>(`/api/v1/works/${id}/retry`);
}

export function analyzeWork(id: number): Promise<AnalyzeResult> {
  return postJson<AnalyzeResult>(`/api/v1/works/${id}/analyze`);
}

export function classifyWork(id: number, body: ClassifyRequest): Promise<Work> {
  return postJson<Work>(`/api/v1/works/${id}/classify`, body);
}

export function listWorkFrames(id: number): Promise<FrameList> {
  return getJson<FrameList>(`/api/v1/works/${id}/frames`);
}
