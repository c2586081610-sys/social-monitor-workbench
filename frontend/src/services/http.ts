/**
 * 统一 HTTP 客户端：Bearer token + envelope {code, data, message} 解包。
 * - code === 0 → 返回 data
 * - code === 401 → 触发全局未认证事件（顶部横幅引导去设置页配 token）
 * - code === 2001 → 触发全局 cookie 失效事件（横幅 + 重新登录弹窗）
 * - 其余非 0 → 抛 ApiError（页面 ErrorState 展示）
 */
import { API_BASE_URL, getToken } from '../config/api';
import { emitReloginRequired, emitUnauthorized } from '../utils/events';
import type { Envelope } from '../types/api.d';

export class ApiError extends Error {
  readonly code: number;
  readonly status: number;
  readonly data: unknown;

  constructor(code: number, status: number, message: string, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.data = data;
  }
}

export function buildQuery(params: object = {}): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') search.append(key, String(item));
      });
      return;
    }
    search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, 0, '无法连接聚合 API，请确认后端已启动（uvicorn app.main:app --port 8000）');
  }

  let body: Envelope<T> | null = null;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    body = null;
  }

  if (body && body.code === 0) {
    return body.data as T;
  }

  const code = body?.code ?? res.status;
  const message = body?.message || `请求失败（HTTP ${res.status}）`;
  const data = body?.data ?? null;

  if (code === 401) emitUnauthorized();
  if (code === 2001) emitReloginRequired();

  throw new ApiError(code, res.status, message, data);
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' });
}

export function postJson<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function patchJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
}

export function deleteJson<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' });
}

/** 读取受 Bearer 保护的 CSV/媒体等原始响应；JSON 错误仍按 Envelope 抛出。 */
export async function requestBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: '*/*',
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, 0, '无法连接聚合 API，请确认后端已启动（uvicorn app.main:app --port 8000）');
  }

  const contentType = res.headers.get('content-type')?.toLowerCase() ?? '';
  const isJson = contentType.includes('application/json') || contentType.includes('+json');
  if (!res.ok || isJson) {
    let body: Partial<Envelope<unknown>> | null = null;
    try {
      body = (await res.json()) as Partial<Envelope<unknown>>;
    } catch {
      body = null;
    }

    const code = body?.code ?? res.status;
    if (code === 401 || res.status === 401) emitUnauthorized();
    if (code === 2001) emitReloginRequired();

    const message = body?.message || (isJson && res.ok ? '服务器未返回文件内容' : `请求失败（HTTP ${res.status}）`);
    throw new ApiError(code, res.status, message, body?.data ?? null);
  }

  return res.blob();
}
