/** 轻量全局事件总线：跨组件通知（认证失效 / cookie 失效）。 */

export const EVENTS = {
  /** 401 未认证（token 缺失/错误） */
  UNAUTHORIZED: 'aggregator:unauthorized',
  /** code=2001 Cookie 失效，需重新登录（可携带平台） */
  RELOGIN_REQUIRED: 'aggregator:relogin-required',
} as const;

export function emitUnauthorized(): void {
  window.dispatchEvent(new CustomEvent(EVENTS.UNAUTHORIZED));
}

export function emitReloginRequired(platform?: string): void {
  window.dispatchEvent(new CustomEvent(EVENTS.RELOGIN_REQUIRED, { detail: { platform } }));
}

export function onUnauthorized(handler: () => void): () => void {
  window.addEventListener(EVENTS.UNAUTHORIZED, handler);
  return () => window.removeEventListener(EVENTS.UNAUTHORIZED, handler);
}

export function onReloginRequired(handler: (platform?: string) => void): () => void {
  const listener = (e: Event) => {
    const detail = (e as CustomEvent<{ platform?: string }>).detail;
    handler(detail?.platform);
  };
  window.addEventListener(EVENTS.RELOGIN_REQUIRED, listener);
  return () => window.removeEventListener(EVENTS.RELOGIN_REQUIRED, listener);
}
