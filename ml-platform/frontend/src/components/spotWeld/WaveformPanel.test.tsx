import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { init, dispose, setOption, resize } = vi.hoisted(() => ({
  init: vi.fn(), dispose: vi.fn(), setOption: vi.fn(), resize: vi.fn(),
}));

vi.mock("echarts", () => ({
  init: (...args: unknown[]) => {
    init(...args);
    return { setOption, resize, dispose };
  },
}));

import WaveformPanel from "./WaveformPanel";

describe("WaveformPanel", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders four fixed waveform channels and disposes charts", () => {
    const { unmount } = render(<WaveformPanel waveforms={{
      current: [1, 2, 3], voltage: [4, 5, 6], resistance: [7, 8, 9], power: [10, 11, 12],
    }} />);

    expect(screen.getByText("电流")).toBeInTheDocument();
    expect(screen.getByText("电压")).toBeInTheDocument();
    expect(screen.getByText("电阻")).toBeInTheDocument();
    expect(screen.getByText("功率")).toBeInTheDocument();
    expect(init).toHaveBeenCalledTimes(4);
    expect(setOption).toHaveBeenCalledTimes(4);
    unmount();
    expect(dispose).toHaveBeenCalledTimes(4);
  });
});
