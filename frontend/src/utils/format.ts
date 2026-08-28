/** 时间 / 时长格式化（统一本地时区展示；数据库存 ISO-8601 UTC）。 */

export function parseDate(iso?: string | null): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDateTime(iso?: string | null): string {
  const d = parseDate(iso);
  if (!d) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatDate(iso?: string | null): string {
  const d = parseDate(iso);
  if (!d) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function relativeTime(iso?: string | null): string {
  const d = parseDate(iso);
  if (!d) return '—';
  const diffMs = Date.now() - d.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return formatDate(iso);
}

/** 秒 → mm:ss（关键帧时间点展示）。 */
export function formatSeconds(seconds?: number | null): string {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) return '—';
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * 爬取时间相对展示：≤60s「刚刚」、<60min「X 分钟前」、<24h「X 小时前」、否则「X 天前」。
 * null / 非法时间返回「—」。
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return '—';
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return '刚刚';
  const seconds = Math.floor(diffMs / 1000);
  if (seconds <= 60) return '刚刚';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

/** 字节数人类可读（B/KB/MB/GB）。 */
export function formatBytes(bytes?: number | null): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes;
  let i = -1;
  do {
    v /= 1024;
    i += 1;
  } while (v >= 1024 && i < units.length - 1);
  return `${v.toFixed(1)} ${units[i]}`;
}
