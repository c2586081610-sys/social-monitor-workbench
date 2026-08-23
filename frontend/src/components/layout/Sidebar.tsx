/** 侧边导航（桌面为主；移动端折叠为顶部横向滚动条）。 */
import { NavLink } from 'react-router-dom';
import {
  Folder,
  Inbox,
  Library,
  Settings,
  Tags,
  Users,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '博主列表', icon: Users, end: true },
  { to: '/groups', label: '分组管理', icon: Folder },
  { to: '/tags', label: '标签检索', icon: Tags },
  { to: '/unclassified', label: '待分类', icon: Inbox },
  { to: '/lexicon', label: '词库管理', icon: Library },
  { to: '/settings', label: '设置', icon: Settings },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
    isActive
      ? 'bg-primary text-white'
      : 'text-ink-secondary hover:bg-surface hover:text-ink'
  }`;
}

export default function Sidebar() {
  return (
    <>
      {/* 桌面侧栏 */}
      <aside className="hidden w-52 shrink-0 border-r border-line bg-sidebar md:flex md:flex-col">
        <div className="flex h-14 items-center gap-2 border-b border-line px-4">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-white">
            <Users className="h-4 w-4" />
          </span>
          <span className="text-sm font-semibold text-ink">博主监控工作台</span>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3 text-xs leading-5 text-ink-muted">
          Obsidian + 本地媒体库
          <br />
          AI 笔记零 API 成本
        </div>
      </aside>

      {/* 移动端顶部横向导航 */}
      <nav className="flex gap-1 overflow-x-auto border-b border-line bg-sidebar p-2 md:hidden">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
            <item.icon className="h-4 w-4 shrink-0" />
            <span className="whitespace-nowrap">{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </>
  );
}
