/** 重新登录弹窗（P10）：扫码/重登引导 + 刷新健康状态。前端不持有凭据，只引导并回查。 */
import { QrCode, RefreshCw, ShieldCheck } from 'lucide-react';
import Modal from '../common/Modal';
import { PLATFORM_LABEL } from '../../utils/constants';

interface ReloginModalProps {
  open: boolean;
  platform: string | null;
  onClose: () => void;
  onRefresh: () => void;
}

const STEPS: { title: string; desc: string }[] = [
  { title: '打开对应平台 App', desc: '在手机端进入「设置 → 登录/安全」，准备扫码或获取新登录态。' },
  { title: '保持 CDP 会话 / 更新 cookie', desc: '抖音走 CDP 扫码持活会话；B站/小红书/推特在监控层配置中更新 cookie（加密存储）。' },
  { title: '完成后刷新健康状态', desc: '点击下方「我已重新登录」，系统回查各平台凭据健康度。任务与未完成作品不会丢失。' },
];

export default function ReloginModal({ open, platform, onClose, onRefresh }: ReloginModalProps) {
  const label = platform ? PLATFORM_LABEL[platform] ?? platform : '该平台';
  return (
    <Modal open={open} title={`重新登录 · ${label}`} onClose={onClose} widthClass="max-w-md">
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg bg-info-light p-3 text-sm text-info">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            凭据失效后系统不会静默丢弃任务：当前排队/进行中的任务会保留，待重登恢复后继续执行。
          </p>
        </div>

        <div className="flex justify-center py-2">
          <span className="flex h-24 w-24 items-center justify-center rounded-lg border border-line bg-surface text-ink-muted">
            <QrCode className="h-12 w-12" />
          </span>
        </div>
        <p className="text-center text-xs text-ink-muted">
          {label} 扫码登录示意（二维码由平台 App 生成）
        </p>

        <ol className="space-y-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-white">
                {i + 1}
              </span>
              <div>
                <p className="text-sm font-medium text-ink">{s.title}</p>
                <p className="text-xs leading-5 text-ink-secondary">{s.desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar"
        >
          稍后处理
        </button>
        <button
          type="button"
          onClick={() => {
            onRefresh();
            onClose();
          }}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          我已重新登录
        </button>
      </div>
    </Modal>
  );
}
