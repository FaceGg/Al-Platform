import { describe, expect, it } from "vitest";
import { translations } from "./index";

/** zh/en 键齐平校验（正规化 i18n 双套完整性的守护测试）。 */
describe("i18n zh/en parity", () => {
  it("every zh key has an en counterpart", () => {
    const zh = translations.zh as unknown as Record<string, unknown>;
    const en = translations.en as unknown as Record<string, unknown>;
    const missing: string[] = [];
    const walk = (z: unknown, e: unknown, path: string) => {
      if (typeof z === "object" && z !== null) {
        for (const key of Object.keys(z as Record<string, unknown>)) {
          const eVal = (e as Record<string, unknown>)?.[key];
          if (eVal === undefined) {
            missing.push(path + key);
          } else {
            walk((z as Record<string, unknown>)[key], eVal, `${path}${key}.`);
          }
        }
      }
    };
    walk(zh, en, "");
    if (missing.length > 0) {
      throw new Error(`missing ${missing.length} en keys: ${missing.slice(0, 30).join(", ")}`);
    }
    expect(missing.length).toBe(0);
  });
});
