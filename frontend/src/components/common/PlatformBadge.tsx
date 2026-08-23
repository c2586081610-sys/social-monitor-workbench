/** 平台徽标（仅展示平台名，图标由调用方按需渲染）。 */
import { PLATFORM_LABEL } from '../../utils/constants';

export default function PlatformBadge({ platform }: { platform: string }) {
  const label = PLATFORM_LABEL[platform] ?? platform;
  return (
    <span className="inline-flex items-center rounded-full bg-sidebar px-2 py-0.5 text-xs font-medium text-ink-secondary">
      {label}
    </span>
  );
}
