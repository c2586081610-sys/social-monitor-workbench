/**
 * 三件套（下载 → 转写 → AI笔记）阶段进度推导。
 * 输入作品 status（+ 可选 WorkDetail.stages），输出三阶段状态，供进度条/状态卡渲染。
 */
import type { StageName, TaskStage, WorkStatus } from '../types/api.d';

export type StageKey = 'download' | 'transcribe' | 'note';
export type StageState = 'idle' | 'active' | 'done' | 'failed';

export interface StageProgressItem {
  key: StageKey;
  label: string;
  state: StageState;
  /** 阶段级错误信息（有则展示失败原因） */
  error: string | null;
}

/** 状态机顺序：数值越大越靠后；FAILED 无顺序（-1）。 */
const ORDER: Record<WorkStatus, number> = {
  NEW: 0,
  QUEUED: 0,
  DOWNLOADING: 1,
  TRANSCRIBING: 2,
  FRAME_EXTRACTING: 3,
  NOTE_GENERATING: 4,
  DONE: 5,
  UNCLASSIFIED: 5,
  FAILED: -1,
};

const STAGE_LABEL: Record<StageKey, string> = {
  download: '下载',
  transcribe: '转写',
  note: 'AI 笔记',
};

interface ResolveInput {
  key: StageKey;
  stageNames: StageName[];
  order: number;
  status: WorkStatus;
  overallFailed: boolean;
  stageMap: Map<string, TaskStage>;
  doneThreshold: number;
  activeStatuses: WorkStatus[];
}

function resolve({ key, stageNames, order, status, overallFailed, stageMap, doneThreshold, activeStatuses }: ResolveInput): StageProgressItem {
  const succeeded = stageNames.some((s) => stageMap.get(s)?.status === 'succeeded');
  const failed = stageNames.some((s) => stageMap.get(s)?.status === 'failed');
  const error = stageNames.map((s) => stageMap.get(s)?.error).find((e) => e) ?? null;

  let state: StageState;
  if (succeeded || order >= doneThreshold) {
    state = 'done';
  } else if (failed || (overallFailed && order >= 0 && order < doneThreshold)) {
    state = 'failed';
  } else if (activeStatuses.includes(status)) {
    state = 'active';
  } else {
    state = 'idle';
  }

  return { key, label: STAGE_LABEL[key], state, error };
}

export function stageProgress(status: WorkStatus, stages?: TaskStage[]): StageProgressItem[] {
  const order = ORDER[status] ?? 0;
  const overallFailed = status === 'FAILED';
  const stageMap = new Map<string, TaskStage>();
  (stages ?? []).forEach((s) => stageMap.set(s.stage, s));

  const items: StageProgressItem[] = [
    resolve({
      key: 'download',
      stageNames: ['download'],
      order,
      status,
      overallFailed,
      stageMap,
      doneThreshold: 2,
      activeStatuses: ['DOWNLOADING'],
    }),
    resolve({
      key: 'transcribe',
      stageNames: ['transcribe', 'frames'],
      order,
      status,
      overallFailed,
      stageMap,
      doneThreshold: 4,
      activeStatuses: ['TRANSCRIBING', 'FRAME_EXTRACTING'],
    }),
    resolve({
      key: 'note',
      stageNames: ['note'],
      order,
      status,
      overallFailed,
      stageMap,
      doneThreshold: 5,
      activeStatuses: ['NOTE_GENERATING'],
    }),
  ];

  // FAILED 且完全无阶段明细时：保守地把第一个未完成阶段标为失败，其后为 idle
  if (overallFailed && stageMap.size === 0) {
    const firstIdx = items.findIndex((it) => it.state !== 'done');
    if (firstIdx >= 0) {
      items.forEach((it, idx) => {
        it.state = idx === firstIdx ? 'failed' : idx < firstIdx ? 'done' : 'idle';
      });
    }
  }

  return items;
}
