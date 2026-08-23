/**
 * 轻量数据请求 Hooks（任务锁定 HTTP：fetch，未引入 react-query）：
 * - useAsyncData：异步加载 + 手动 refetch
 * - usePolling：条件轮询（作品列表存在 running 状态时 5s 轮询，完成后停轮）
 * - useMutation：写操作（loading / error / run）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiError } from '../services/http';

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
}

/**
 * @param fn      数据获取函数（每次渲染取最新引用）
 * @param deps    触发重新加载的依赖
 * @param enabled 是否启用（false 时不发起请求）
 */
export function useAsyncData<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  enabled = true,
): AsyncState<T> & { refetch: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: enabled, error: null });
  const [version, setVersion] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    fnRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((err: ApiError) => {
        if (!cancelled) setState((prev) => ({ ...prev, loading: false, error: err }));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version, ...deps]);

  const refetch = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, refetch };
}

/** 条件轮询：enabled 为 true 时每 intervalMs 调用一次 fn。 */
export function usePolling(fn: () => void, enabled: boolean, intervalMs = 5000): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => fnRef.current(), intervalMs);
    return () => window.clearInterval(id);
  }, [enabled, intervalMs]);
}

interface MutationState {
  loading: boolean;
  error: ApiError | null;
}

export function useMutation<TArgs, TRes>(fn: (args: TArgs) => Promise<TRes>) {
  const [state, setState] = useState<MutationState>({ loading: false, error: null });
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async (args?: TArgs): Promise<TRes> => {
    setState({ loading: true, error: null });
    try {
      const result = await fnRef.current(args as TArgs);
      setState({ loading: false, error: null });
      return result;
    } catch (err) {
      const apiErr = err as ApiError;
      setState({ loading: false, error: apiErr });
      throw apiErr;
    }
  }, []);

  return { ...state, run };
}
