/** 监控层手动触发 API 封装（对齐 openapi: monitor；契约锁定 poll-now / poll-status）。 */
import { getJson, postJson } from './http';
import type { Platform, PollNowResult, PollStatusList } from '../types/api.d';

export interface PollNowParams {
  platform?: Platform;
  creator_id?: number;
}

/**
 * 立即触发一次性爬取（后端自行拉起 RSSHub→爬→关闭，不依赖监测层常驻）。
 * 不带参数 = 全部平台。
 */
export function pollNow(params?: PollNowParams): Promise<PollNowResult> {
  const hasParams = params !== undefined && (params.platform !== undefined || params.creator_id !== undefined);
  return postJson<PollNowResult>('/api/v1/monitor/poll-now', hasParams ? params : undefined);
}

/** 各平台最近爬取时间（来自 poll_logs）。 */
export function pollStatus(): Promise<PollStatusList> {
  return getJson<PollStatusList>('/api/v1/monitor/poll-status');
}
