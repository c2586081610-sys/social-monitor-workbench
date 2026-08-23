/** 健康度资源 API 封装（对齐 openapi: health）。 */
import { getJson } from './http';
import type { CookieHealthList, SystemHealthList } from '../types/api.d';

export function getCookieHealth(): Promise<CookieHealthList> {
  return getJson<CookieHealthList>('/api/v1/health/cookie');
}

export function getSystemHealth(): Promise<SystemHealthList> {
  return getJson<SystemHealthList>('/api/v1/health/system');
}

/** 无认证存活探针（部署/运维用，不进 openapi 契约）。 */
export function pingHealth(): Promise<{ status: string }> {
  return getJson<{ status: string }>('/api/v1/healthz');
}
