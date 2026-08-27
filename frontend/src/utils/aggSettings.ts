/**
 * 聚合监控启用配置（localStorage 持久化，跨页面共享）。
 * - agg_global_enabled：总启用（控制自动刷新 + 立即爬取全部），默认 true
 * - agg_platform_enabled_<platform>：单平台启用，默认 true
 * - agg_auto_refresh：自动刷新开关，默认 false
 * - agg_auto_refresh_minutes：自动刷新间隔（分钟），默认 300
 */
const GLOBAL_KEY = 'agg_global_enabled';
const AUTO_REFRESH_KEY = 'agg_auto_refresh';
const AUTO_REFRESH_MINUTES_KEY = 'agg_auto_refresh_minutes';
const PLATFORM_PREFIX = 'agg_platform_enabled_';

function readBool(key: string, fallback: boolean): boolean {
  const raw = localStorage.getItem(key);
  if (raw === null) return fallback;
  return raw !== 'false';
}

function readMinutes(key: string, fallback: number): number {
  const raw = localStorage.getItem(key);
  if (raw === null) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : fallback;
}

export interface AggSettings {
  globalEnabled: boolean;
  autoRefresh: boolean;
  autoRefreshMinutes: number;
}

export function readAggSettings(): AggSettings {
  return {
    globalEnabled: readBool(GLOBAL_KEY, true),
    autoRefresh: readBool(AUTO_REFRESH_KEY, false),
    autoRefreshMinutes: readMinutes(AUTO_REFRESH_MINUTES_KEY, 300),
  };
}

export function setGlobalEnabled(value: boolean): void {
  localStorage.setItem(GLOBAL_KEY, String(value));
}

export function setAutoRefresh(value: boolean): void {
  localStorage.setItem(AUTO_REFRESH_KEY, String(value));
}

export function setAutoRefreshMinutes(value: number): void {
  localStorage.setItem(AUTO_REFRESH_MINUTES_KEY, String(Math.max(1, Math.round(value))));
}

export function readPlatformEnabled(platform: string): boolean {
  return readBool(`${PLATFORM_PREFIX}${platform}`, true);
}

export function setPlatformEnabled(platform: string, value: boolean): void {
  localStorage.setItem(`${PLATFORM_PREFIX}${platform}`, String(value));
}
