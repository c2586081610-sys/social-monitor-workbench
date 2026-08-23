/** 基础弹窗：遮罩 + 面板 + 标题 + 关闭。动效仅 opacity/translate 轻量过渡。 */
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { useEffect } from 'react';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** 底部操作区（自定义按钮） */
  footer?: ReactNode;
  /** 面板宽度类，默认 max-w-lg */
  widthClass?: string;
}

export default function Modal({ open, title, onClose, children, footer, widthClass = 'max-w-lg' }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/40 p-4" role="dialog" aria-modal="true">
      <div className={`w-full ${widthClass} rounded-lg bg-surface shadow-panel transition-opacity`}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-ink-muted transition-colors hover:bg-sidebar hover:text-ink"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div> : null}
      </div>
    </div>
  );
}
