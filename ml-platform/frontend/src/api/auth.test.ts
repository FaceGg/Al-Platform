import { describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { login } from "./auth";

describe("auth API", () => {
  it("submits OAuth login as form data", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { access_token: "token" } });

    await login("admin", "admin123");

    expect(post).toHaveBeenCalledWith(
      "/auth/login",
      expect.any(URLSearchParams),
      { headers: { "Content-Type": "application/x-www-form-urlencoded" } },
    );
  });
});
