/** API 基地址与 Admin Token 配置（前端唯一配置入口）。 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

/** 开发兜底口令，与 backend/.env.example 默认值一致；生产通过设置页覆盖。 */
export const DEFAULT_TOKEN = 'dev-admin-token-change-me';

const TOKEN_KEY = 'aggregator_admin_token';

export function getToken(): string {
  const saved = localStorage.getItem(TOKEN_KEY);
  if (saved) return saved;
  return (import.meta.env.VITE_ADMIN_TOKEN as string | undefined) ?? DEFAULT_TOKEN;
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}
