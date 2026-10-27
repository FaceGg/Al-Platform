import { act, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAdaptivePolling } from "./useAdaptivePolling";

// hook 的计时链在回调 resolve 的微任务里排下一跳，
// 假定时器推进后需冲刷微任务（与页面轮询测试同一惯例）
async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function PollingProbe(props: {
  enabled: boolean;
  intervalMs: number;
  maxIntervalMs?: number;
  signature?: string | null;
  immediate?: boolean;
}) {
  const [ticks, setTicks] = useState(0);
  const [signature, setSignature] = useState(props.signature ?? null);
  useAdaptivePolling(() => { setTicks((current) => current + 1); }, {
    enabled: props.enabled,
    intervalMs: props.intervalMs,
    maxIntervalMs: props.maxIntervalMs,
    signature,
    immediate: props.immediate,
  });
  (window as any).__bumpSignature = () => setSignature(`sig-${ticks}`);
  return <div data-testid="ticks">{ticks}</div>;
}

describe("useAdaptivePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    delete (window as any).__bumpSignature;
  });

  it("polls at the base interval first and backs off while nothing changes", async () => {
    const { getByTestId } = render(
      <PollingProbe enabled intervalMs={1000} maxIntervalMs={4000} />,
    );

    expect(getByTestId("ticks").textContent).toBe("0");
    await advance(1000);
    expect(getByTestId("ticks").textContent).toBe("1");
    // 无变化 → 1500ms
    await advance(1499);
    expect(getByTestId("ticks").textContent).toBe("1");
    await advance(1);
    expect(getByTestId("ticks").textContent).toBe("2");
    // 仍无变化 → 2250ms
    await advance(2250);
    expect(getByTestId("ticks").textContent).toBe("3");
    // 3375ms（2250×1.5），未到 4000 封顶
    await advance(3374);
    expect(getByTestId("ticks").textContent).toBe("3");
    await advance(1);
    expect(getByTestId("ticks").textContent).toBe("4");
    // 5062.5 → 封顶 4000
    await advance(4000);
    expect(getByTestId("ticks").textContent).toBe("5");
  });

  it("resets to the base interval when the signature changes", async () => {
    const { getByTestId } = render(
      <PollingProbe enabled intervalMs={1000} maxIntervalMs={8000} />,
    );
    await advance(1000);
    expect(getByTestId("ticks").textContent).toBe("1");

    // 第一次退避（1500ms）已在签名变化前排定，本次仍按退避间隔触发；
    // 触发后比较签名发现变化 → 下一轮回到基础 1000ms
    await act(async () => {
      (window as any).__bumpSignature();
      await Promise.resolve();
    });
    await advance(1500);
    expect(getByTestId("ticks").textContent).toBe("2");
    // 签名变化后回到基础间隔
    await advance(1000);
    expect(getByTestId("ticks").textContent).toBe("3");
    // 此后签名不再变化 → 再次退避到 1500ms
    await advance(1499);
    expect(getByTestId("ticks").textContent).toBe("3");
    await advance(1);
    expect(getByTestId("ticks").textContent).toBe("4");
  });

  it("stops polling entirely while disabled and fires immediately when requested", async () => {
    const { getByTestId, rerender } = render(
      <PollingProbe enabled={false} intervalMs={1000} />,
    );
    await advance(10000);
    expect(getByTestId("ticks").textContent).toBe("0");

    rerender(<PollingProbe enabled intervalMs={1000} immediate />);
    expect(getByTestId("ticks").textContent).toBe("1");
    await advance(1000);
    expect(getByTestId("ticks").textContent).toBe("2");

    rerender(<PollingProbe enabled={false} intervalMs={1000} immediate />);
    await advance(10000);
    expect(getByTestId("ticks").textContent).toBe("2");
  });

  it("keeps the chain alive when a callback rejects", async () => {
    let calls = 0;
    function Broken() {
      useAdaptivePolling(async () => {
        calls += 1;
        if (calls === 1) throw new Error("transient");
      }, { enabled: true, intervalMs: 100 });
      return null;
    }
    render(<Broken />);
    await advance(100);
    expect(calls).toBe(1);
    await advance(150);
    expect(calls).toBe(2);
  });
});
