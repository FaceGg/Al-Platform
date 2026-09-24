import { afterEach, describe, expect, it, vi } from "vitest";

import { createUuid } from "./uuid";

describe("createUuid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses randomUUID when the browser exposes it", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "secure-id" });

    expect(createUuid()).toBe("secure-id");
  });

  it("generates a UUID in an HTTP context without randomUUID", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0xab);
        return bytes;
      },
    });

    expect(createUuid()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("still generates a UUID when Web Crypto is unavailable", () => {
    vi.stubGlobal("crypto", undefined);

    expect(createUuid()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
