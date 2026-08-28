/** 全局常量：平台 / 状态 / 标签页映射（展示文案与语义色）。 */
import type { Platform, WorkStatus } from '../types/api.d';

export interface PlatformMeta {
  value: Platform;
  label: string;
}

export const PLATFORMS: PlatformMeta[] = [
  { value: 'douyin', label: '抖音' },
  { value: 'bilibili', label: 'B站' },
  { value: 'xhs', label: '小红书' },
  { value: 'twitter', label: '推特X' },
];

export const PLATFORM_LABEL: Record<string, string> = PLATFORMS.reduce(
  (acc, p) => ({ ...acc, [p.value]: p.label }),
  {} as Record<string, string>,
);

export const STATUS_LABEL: Record<WorkStatus, string> = {
  NEW: '新作品',
  QUEUED: '排队中',
  DOWNLOADING: '下载中',
  TRANSCRIBING: '转写中',
  FRAME_EXTRACTING: '抽帧中',
  NOTE_GENERATING: 'AI 笔记未完成',
  DONE: '已完成',
  FAILED: '失败',
  UNCLASSIFIED: '待分类',
};

/** 进行中状态：作品列表存在这些状态时前端保持 5s 轮询，全部完成/失败后停轮。 */
export const RUNNING_STATUSES: ReadonlySet<WorkStatus> = new Set<WorkStatus>([
  'QUEUED',
  'DOWNLOADING',
  'TRANSCRIBING',
  'FRAME_EXTRACTING',
  'NOTE_GENERATING',
]);

export const COOKIE_STATUS_LABEL: Record<string, string> = {
  OK: '正常',
  WARN: '警告',
  NEEDS_RELOGIN: '需重新登录',
  UNKNOWN: '未知',
};

export const SYSTEM_COMPONENT_LABEL: Record<string, string> = {
  aggregator: '聚合 API',
  monitor: '监控层',
  rsshub: 'RSSHub',
  changedetection: '变更检测',
  downloader: '下载器',
  transcriber: '转写引擎',
  workbuddy_pending: 'AI 笔记对接',
};

export const SYSTEM_COMPONENT_STATUS: Record<string, string> = {
  online: '在线',
  offline: '离线',
  degraded: '降级',
  unknown: '未知',
};

export const SOURCE_TYPE_LABEL: Record<string, string> = {
  monitor: '监控',
  like: '点赞',
  favorite: '收藏',
  manual: '手动',
};

/** P3 作品状态筛选 Tab（全部 / 新作品 / 排队 / 下载中 / 转写中 / 笔记中 / 已完成 / 失败）。 */
export interface StatusTab {
  key: string;
  label: string;
  statuses: WorkStatus[] | null; // null = 全部
}

export const STATUS_TABS: StatusTab[] = [
  { key: 'all', label: '全部', statuses: null },
  { key: 'NEW', label: '新作品', statuses: ['NEW'] },
  { key: 'QUEUED', label: '排队', statuses: ['QUEUED'] },
  { key: 'DOWNLOADING', label: '下载中', statuses: ['DOWNLOADING'] },
  { key: 'TRANSCRIBING', label: '转写中', statuses: ['TRANSCRIBING', 'FRAME_EXTRACTING'] },
  { key: 'NOTE_GENERATING', label: '笔记中', statuses: ['NOTE_GENERATING'] },
  { key: 'DONE', label: '已完成', statuses: ['DONE'] },
  { key: 'FAILED', label: '失败', statuses: ['FAILED'] },
];

/** 轮询间隔配置（监控层 env 配置，前端展示说明用；P1 由监控层统一执行）。 */
export const POLL_INTERVAL_INFO = [
  { platform: 'RSSHub 平台（B站/小红书/推特X）', value: '5 – 10 分钟' },
  { platform: '抖音（CDP 会话检测）', value: '≥ 10 分钟（可配置，防风控）' },
  { platform: '下载并发', value: '默认 1（防风控，可调）' },
];
