/** 全局「重新登录」弹窗状态（P10）：任意页面可触发，宿主挂在 AppLayout。 */
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

interface ReloginState {
  platform: string | null;
  open: (platform: string) => void;
  close: () => void;
}

const ReloginContext = createContext<ReloginState>({
  platform: null,
  open: () => undefined,
  close: () => undefined,
});

export function ReloginProvider({ children }: { children: ReactNode }) {
  const [platform, setPlatform] = useState<string | null>(null);
  const open = useCallback((p: string) => setPlatform(p), []);
  const close = useCallback(() => setPlatform(null), []);
  const value = useMemo(() => ({ platform, open, close }), [platform, open, close]);
  return <ReloginContext.Provider value={value}>{children}</ReloginContext.Provider>;
}

export function useRelogin(): ReloginState {
  return useContext(ReloginContext);
}
