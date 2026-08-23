/** P8 设置：cookie 状态 + 重新扫码引导 + 轮询间隔配置 + API 连接 + 系统健康 + 公众号占位。 */
import { useState } from 'react';
import { KeyRound, RefreshCw, Settings2 } from 'lucide-react';
import { CookieStatusBadge, ToneBadge } from '../components/common/StatusBadge';
import { ErrorState, LoadingState } from '../components/common/StateViews';
import { getCookieHealth, getSystemHealth, pingHealth } from '../services/health';
import { useAsyncData, usePolling } from '../hooks/useApi';
import { useRelogin } from '../state/relogin';
import { API_BASE_URL, getToken, setToken } from '../config/api';
import { PLATFORM_LABEL, POLL_INTERVAL_INFO, SYSTEM_COMPONENT_LABEL, SYSTEM_COMPONENT_STATUS } from '../utils/constants';
import { formatDateTime } from '../utils/format';

const SYSTEM_TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = {
  online: 'success',
  offline: 'danger',
  degraded: 'warning',
  unknown: 'neutral',
};

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      {desc ? <p className="mt-0.5 text-xs text-ink-muted">{desc}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

export default function SettingsPage() {
  const [tokenInput, setTokenInput] = useState(getToken());
  const [connMsg, setConnMsg] = useState<string | null>(null);
  const [connOk, setConnOk] = useState<boolean | null>(null);
  const { open } = useRelogin();

  const cookieQuery = useAsyncData(() => getCookieHealth(), []);
  const systemQuery = useAsyncData(() => getSystemHealth(), []);
  usePolling(cookieQuery.refetch, true, 30000);

  const cookies = cookieQuery.data?.items ?? [];
  const systems = systemQuery.data?.items ?? [];

  const testConnection = async () => {
    setTokenInput(tokenInput.trim());
    setToken(tokenInput.trim());
    setConnMsg(null);
    setConnOk(null);
    try {
      await pingHealth();
      setConnOk(true);
      setConnMsg('连接成功：聚合 API 可达（无认证探针）。');
    } catch (e) {
      setConnOk(false);
      setConnMsg(e instanceof Error ? `连接失败：${e.message}` : '连接失败');
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">设置</h1>
        <p className="text-xs text-ink-muted">API 地址 {API_BASE_URL}</p>
      </div>

      {/* API 连接 / Token */}
      <Section title="API 连接与口令" desc="前端通过 Bearer token 访问聚合 API；口令保存在浏览器本地。">
        <div className="flex flex-wrap items-center gap-2">
          <KeyRound className="h-4 w-4 text-ink-muted" />
          <input
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="ADMIN_TOKEN"
            type="password"
            className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 font-mono text-sm focus:border-primary focus:outline-none"
          />
          <button
            type="button"
            onClick={testConnection}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm text-white transition-colors hover:bg-primary-hover"
          >
            <RefreshCw className="h-4 w-4" />
            保存并测试
          </button>
        </div>
        {connMsg ? (
          <p className={`mt-2 text-sm ${connOk ? 'text-success' : 'text-danger'}`}>{connMsg}</p>
        ) : null}
      </Section>

      {/* 凭据健康度 */}
      <Section title="凭据健康度" desc="各平台 cookie / CDP 会话状态；失效不静默，可引导重新登录。">
        {cookieQuery.loading ? (
          <LoadingState label="加载凭据状态…" />
        ) : cookieQuery.error ? (
          <ErrorState message={cookieQuery.error.message} onRetry={cookieQuery.refetch} />
        ) : cookies.length === 0 ? (
          <p className="text-xs text-ink-muted">暂无凭据健康数据。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-widest text-ink-muted">
                  <th className="px-3 py-2 font-semibold">平台</th>
                  <th className="px-3 py-2 font-semibold">状态</th>
                  <th className="px-3 py-2 font-semibold">最近检查</th>
                  <th className="px-3 py-2 font-semibold">备注</th>
                  <th className="px-3 py-2 text-right font-semibold">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {cookies.map((c) => (
                  <tr key={c.platform}>
                    <td className="px-3 py-2.5 font-medium text-ink">{PLATFORM_LABEL[c.platform] ?? c.platform}</td>
                    <td className="px-3 py-2.5"><CookieStatusBadge status={c.status} /></td>
                    <td className="px-3 py-2.5 text-xs text-ink-muted">{formatDateTime(c.last_checked_at)}</td>
                    <td className="px-3 py-2.5 text-xs text-ink-secondary">{c.note ?? '—'}</td>
                    <td className="px-3 py-2.5 text-right">
                      {c.status === 'NEEDS_RELOGIN' ? (
                        <button
                          type="button"
                          onClick={() => open(c.platform)}
                          className="rounded-md border border-danger/40 px-2 py-1 text-xs text-danger transition-colors hover:bg-danger hover:text-white"
                        >
                          重新登录
                        </button>
                      ) : (
                        <span className="text-xs text-ink-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* 系统健康 */}
      <Section title="系统健康" desc="监控层 / 外部服务 / 流水线引擎在线状态。">
        {systemQuery.loading ? (
          <LoadingState label="加载系统健康…" />
        ) : systemQuery.error ? (
          <ErrorState message={systemQuery.error.message} onRetry={systemQuery.refetch} />
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {systems.map((s) => (
              <div key={s.component} className="flex items-center justify-between rounded-md border border-line px-3 py-2">
                <span className="text-sm text-ink">{SYSTEM_COMPONENT_LABEL[s.component] ?? s.component}</span>
                <span className="flex items-center gap-2">
                  <span className="text-xs text-ink-muted">{s.detail ?? ''}</span>
                  <ToneBadge tone={SYSTEM_TONE[s.status] ?? 'neutral'} label={SYSTEM_COMPONENT_STATUS[s.status] ?? s.status} />
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* 轮询间隔配置 */}
      <Section title="轮询间隔配置" desc="P1 由监控层统一调度（环境变量配置），此处仅展示当前默认值。">
        <div className="divide-y divide-line rounded-md border border-line">
          {POLL_INTERVAL_INFO.map((row) => (
            <div key={row.platform} className="flex items-center justify-between px-3 py-2 text-sm">
              <span className="text-ink-secondary">{row.platform}</span>
              <span className="font-mono text-xs text-ink">{row.value}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-muted">
          <Settings2 className="h-3.5 w-3.5" />
          调整方式：monitor 层环境变量（如 RSSHUB_POLL_MINUTES / DOUYIN_POLL_MINUTES），修改后重启监控层生效。
        </p>
      </Section>

      {/* 公众号导入占位 */}
      <Section title="公众号导入" desc="接口预留（B1 Backlog），P1 不实现自动监测与 AI 分析。">
        <button
          type="button"
          disabled
          className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-muted"
          title="接口占位 501"
        >
          公众号导入（预留，暂不可用）
        </button>
      </Section>
    </div>
  );
}
