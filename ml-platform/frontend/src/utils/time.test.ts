import { describe, expect, it } from "vitest";

import { formatLocalTime, parseBackendTime } from "./time";

describe("parseBackendTime", () => {
  it("treats naive backend timestamps as UTC, not local", () => {
    // 后端统一存无时区标记的 UTC；直接 new Date 会按本地时区解析（UTC+8 少 8 小时）。
    const parsed = parseBackendTime("2026-10-06T14:04:07");
    expect(parsed).not.toBeNull();
    expect(parsed!.toISOString()).toBe("2026-10-06T14:04:07.000Z");
  });

  it("keeps timestamps that already carry a timezone", () => {
    const parsed = parseBackendTime("2026-10-06T22:04:07+08:00");
    expect(parsed!.toISOString()).toBe("2026-10-06T14:04:07.000Z");

    const zulu = parseBackendTime("2026-10-06T14:04:07Z");
    expect(zulu!.toISOString()).toBe("2026-10-06T14:04:07.000Z");
  });

  it("returns null for empty or invalid values", () => {
    expect(parseBackendTime(null)).toBeNull();
    expect(parseBackendTime(undefined)).toBeNull();
    expect(parseBackendTime("")).toBeNull();
    expect(parseBackendTime("not-a-date")).toBeNull();
  });
});

describe("formatLocalTime", () => {
  it("formats the parsed UTC moment through the local timezone", () => {
    // 断言与 Intl 对同一 UTC 时刻的本地化结果一致（不依赖测试机所在时区）。
    const value = "2026-10-06T14:04:07";
    const parsed = parseBackendTime(value)!;
    const expected = new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).format(parsed).replace(/\//g, "-");
    expect(formatLocalTime(value, true)).toBe(expected);
  });

  it("falls back to a dash for missing values", () => {
    expect(formatLocalTime(null)).toBe("-");
    expect(formatLocalTime("")).toBe("-");
  });
});
