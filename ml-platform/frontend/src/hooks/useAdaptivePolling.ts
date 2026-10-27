import { useEffect, useRef } from "react";

export interface AdaptivePollingOptions {
  /** false 时停止轮询并清除定时器（终态停轮口径由调用方的门控决定，不变） */
  enabled: boolean;
  /** 基础轮询间隔（毫秒） */
  intervalMs: number;
  /** 无变化时的退避上限（毫秒），默认 4×intervalMs */
  maxIntervalMs?: number;
  /** 每次退避的乘数，默认 1.5 */
  backoffFactor?: number;
  /**
   * 数据签名（如任务状态串）：与上一次轮询后不同视为"有动静"，
   * 间隔重置回基础值；相同则继续退避。省略表示无法判定，恒为"无动静"。
   */
  signature?: string | number | null;
  /** enabled 生效时是否立即触发一次（默认 false；首发刷新仍由调用方现有逻辑负责） */
  immediate?: boolean;
}

const DEFAULT_BACKOFF_FACTOR = 1.5;

/**
 * 自适应轮询：数据静止时指数退避降低请求密度，签名变化时回到基础间隔。
 * 以 setTimeout 链调度（上一次请求结束后才排下一次，不重叠）。
 */
export function useAdaptivePolling(
  callback: () => void | Promise<unknown>,
  options: AdaptivePollingOptions,
): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const signatureRef = useRef(options.signature);
  signatureRef.current = options.signature;

  const {
    enabled,
    intervalMs,
    maxIntervalMs,
    backoffFactor = DEFAULT_BACKOFF_FACTOR,
    immediate = false,
  } = options;
  const effectiveMaxMs = Math.max(intervalMs, maxIntervalMs ?? intervalMs * 4);

  useEffect(() => {
    if (!enabled) return undefined;
    let disposed = false;
    let currentIntervalMs = intervalMs;
    let lastSignature = signatureRef.current;
    let timer: ReturnType<typeof setTimeout> | undefined;

    if (immediate) {
      void Promise.resolve(callbackRef.current()).catch(() => undefined);
    }

    const scheduleNext = () => {
      timer = setTimeout(async () => {
        if (disposed) return;
        await Promise.resolve(callbackRef.current()).catch(() => undefined);
        if (disposed) return;
        if (signatureRef.current !== lastSignature) {
          lastSignature = signatureRef.current;
          currentIntervalMs = intervalMs;
        } else {
          currentIntervalMs = Math.min(
            currentIntervalMs * backoffFactor,
            effectiveMaxMs,
          );
        }
        scheduleNext();
      }, currentIntervalMs);
    };
    scheduleNext();

    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
    // callback 与 signature 经 ref 读取最新值：签名变化不应重启计时链。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, backoffFactor, effectiveMaxMs, immediate]);
}
