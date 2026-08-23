/** 监控层手动触发 API 封装（对齐 openapi: monitor）。 */
import { postJson } from './http';
import type { Platform, PollResult } from '../types/api.d';

export function triggerPoll(platform?: Platform): Promise<PollResult> {
  return postJson<PollResult>('/api/v1/monitor/poll', platform ? { platform } : undefined);
}
