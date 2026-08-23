/** 确认弹窗：危险操作二次确认（删除分组/删除博主等）。 */
import Modal from './Modal';
import { AlertTriangle } from 'lucide-react';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmText = '确认删除',
  danger = true,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal open={open} title={title} onClose={onCancel}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger-light text-danger">
          <AlertTriangle className="h-4 w-4" />
        </span>
        <p className="text-sm leading-6 text-ink-secondary">{message}</p>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar disabled:opacity-60"
        >
          取消
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={loading}
          className={`rounded-md px-3 py-1.5 text-sm text-white transition-colors disabled:opacity-60 ${
            danger ? 'bg-danger hover:bg-danger/90' : 'bg-primary hover:bg-primary-hover'
          }`}
        >
          {loading ? '处理中…' : confirmText}
        </button>
      </div>
    </Modal>
  );
}
