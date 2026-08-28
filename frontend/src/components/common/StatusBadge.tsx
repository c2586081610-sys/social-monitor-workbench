/** 状态徽标：作品状态 / 凭据健康度 / 通用语义色。图标统一 lucide-react（无 emoji）。 */
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Inbox,
  Loader2,
  XCircle,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { STATUS_LABEL, COOKIE_STATUS_LABEL } from '../../utils/constants';
import type { CookieStatus, WorkStatus } from '../../types/api.d';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'bg-sidebar text-ink-secondary',
  info: 'bg-info-light text-info',
  success: 'bg-success-light text-success',
  warning: 'bg-warning-light text-warning',
  danger: 'bg-danger-light text-danger',
};

interface WorkBadgeMeta {
  tone: Tone;
  icon: LucideIcon;
  spin?: boolean;
}

const WORK_META: Record<WorkStatus, WorkBadgeMeta> = {
  NEW: { tone: 'neutral', icon: Clock },
  QUEUED: { tone: 'info', icon: Clock },
  DOWNLOADING: { tone: 'info', icon: Loader2, spin: true },
  TRANSCRIBING: { tone: 'info', icon: Loader2, spin: true },
  FRAME_EXTRACTING: { tone: 'info', icon: Loader2, spin: true },
  // NOTE_GENERATING：当前系统无真正生成中的信号，一律不转圈；「已完成」分支见 StatusBadge 的 notePath 判断
  NOTE_GENERATING: { tone: 'neutral', icon: FileText },
  DONE: { tone: 'success', icon: CheckCircle2 },
  FAILED: { tone: 'danger', icon: XCircle },
  UNCLASSIFIED: { tone: 'warning', icon: Inbox },
};

const COOKIE_META: Record<CookieStatus, { tone: Tone; icon: LucideIcon }> = {
  OK: { tone: 'success', icon: CheckCircle2 },
  WARN: { tone: 'warning', icon: AlertTriangle },
  NEEDS_RELOGIN: { tone: 'danger', icon: XCircle },
  UNKNOWN: { tone: 'neutral', icon: Clock },
};

function BadgeInner({ icon: Icon, spin, label, tone }: { icon: LucideIcon; spin?: boolean; label: string; tone: Tone }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}>
      <Icon className={`h-3 w-3 ${spin ? 'animate-spin' : ''}`} />
      {label}
    </span>
  );
}

/** 作品状态徽标。notePath 非空时 NOTE_GENERATING 视为已完成（二分显示）。 */
export function StatusBadge({ status, notePath }: { status: WorkStatus; notePath?: string | null }) {
  if (status === 'NOTE_GENERATING' && notePath) {
    return <BadgeInner icon={CheckCircle2} label="已完成" tone="success" />;
  }
  const meta = WORK_META[status] ?? WORK_META.NEW;
  return <BadgeInner icon={meta.icon} spin={meta.spin} label={STATUS_LABEL[status] ?? status} tone={meta.tone} />;
}

/** 凭据健康度徽标。 */
export function CookieStatusBadge({ status }: { status: CookieStatus }) {
  const meta = COOKIE_META[status] ?? COOKIE_META.UNKNOWN;
  return (
    <BadgeInner
      icon={meta.icon}
      label={COOKIE_STATUS_LABEL[status] ?? status}
      tone={meta.tone}
    />
  );
}

/** 通用语义徽标（组件状态等）。 */
export function ToneBadge({ tone, label }: { tone: Tone; label: string }) {
  const icon = tone === 'success' ? CheckCircle2 : tone === 'danger' ? XCircle : tone === 'warning' ? AlertTriangle : Clock;
  return <BadgeInner icon={icon} label={label} tone={tone} />;
}
