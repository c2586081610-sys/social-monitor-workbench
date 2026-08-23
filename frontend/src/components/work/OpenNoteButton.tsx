/** 打开 AI 笔记：note_path 为 Obsidian 本地相对路径，前端复制路径并提示（无后端静态服务时不可直接预览）。 */
import { useState } from 'react';
import { Check, Copy, ExternalLink, NotebookPen } from 'lucide-react';

interface OpenNoteButtonProps {
  notePath: string;
  /** 笔记可访问的外部链接（如 WorkBuddy/Obsidian 导出地址），缺省仅复制路径 */
  href?: string;
}

export default function OpenNoteButton({ notePath, href }: OpenNoteButtonProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(notePath);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const buttonClass =
    'inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:bg-sidebar hover:text-ink';

  return (
    <span className="inline-flex items-center gap-1.5">
      <button type="button" onClick={copy} className={buttonClass} title="复制 Obsidian 笔记路径">
        {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        {copied ? '已复制' : '笔记路径'}
      </button>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-hover"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          打开
        </a>
      ) : (
        <span className="inline-flex items-center gap-1.5 rounded-md bg-primary-light px-2.5 py-1.5 text-xs font-medium text-primary" title={notePath}>
          <NotebookPen className="h-3.5 w-3.5" />
          Obsidian 笔记
        </span>
      )}
    </span>
  );
}
