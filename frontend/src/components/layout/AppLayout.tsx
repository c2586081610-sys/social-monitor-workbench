/** 应用布局：侧栏 + 主区（CookieBanner / 未认证横幅 / ReloginModal 宿主 / Outlet）。 */
import { useState } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { KeyRound } from 'lucide-react';
import Sidebar from './Sidebar';
import CookieBanner from '../common/CookieBanner';
import ReloginModal from '../relogin/ReloginModal';
import { useRelogin } from '../../state/relogin';
import { emitReloginRequired, onUnauthorized } from '../../utils/events';
import { useEffect } from 'react';

export default function AppLayout() {
  const { platform, close } = useRelogin();
  const [unauthorized, setUnauthorized] = useState(false);

  useEffect(() => onUnauthorized(() => setUnauthorized(true)), []);

  return (
    <div className="flex min-h-screen flex-col bg-canvas md:flex-row">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-line bg-surface px-4">
          <p className="text-sm text-ink-muted">四平台博主监控 · 下载 / 转写 / 语义关键帧 / AI 笔记</p>
          <Link to="/settings" className="text-xs text-primary hover:text-primary-hover">
            连接与设置
          </Link>
        </header>

        {unauthorized ? (
          <div className="flex items-center justify-between gap-3 bg-danger-light px-4 py-2 text-sm text-danger">
            <span className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 shrink-0" />
              未认证：当前 ADMIN_TOKEN 缺失或错误，请前往设置页配置后重试。
            </span>
            <Link
              to="/settings"
              onClick={() => setUnauthorized(false)}
              className="shrink-0 rounded-md border border-danger/40 bg-surface px-2.5 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger hover:text-white"
            >
              去配置
            </Link>
          </div>
        ) : null}

        <CookieBanner />

        <main className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>

      <ReloginModal
        open={platform !== null}
        platform={platform}
        onClose={close}
        onRefresh={() => emitReloginRequired()}
      />
    </div>
  );
}
