import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import {
  createLlmProfile,
  deleteLlmProfile,
  listLlmProfiles,
  testLlmProfile,
  updateLlmProfile,
} from "./llmProfiles";

describe("llmProfiles client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("lists profiles", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [{ id: "p1" }] });
    await expect(listLlmProfiles()).resolves.toHaveLength(1);
    expect(get).toHaveBeenCalledWith("/llm-profiles");
  });

  it("creates a profile with write-only api key", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "p2" } });
    const payload = {
      name: "glm",
      provider: "openai_compatible",
      api_url: "https://api.example.com/v1/chat/completions",
      api_key: "sk-test",
      model_id: "glm-4.6",
      deployment: "cloud" as const,
    };
    await expect(createLlmProfile(payload)).resolves.toEqual({ id: "p2" });
    expect(post).toHaveBeenCalledWith("/llm-profiles", payload);
  });

  it("patches and deletes", async () => {
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: { id: "p1" } });
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue({});
    await updateLlmProfile("p1", { model_id: "glm-5" });
    expect(patch).toHaveBeenCalledWith("/llm-profiles/p1", { model_id: "glm-5" });
    await deleteLlmProfile("p1");
    expect(del).toHaveBeenCalledWith("/llm-profiles/p1");
  });

  it("runs connectivity probe", async () => {
    const post = vi
      .spyOn(apiClient, "post")
      .mockResolvedValue({ data: { ok: true, status_code: 200, latency_ms: 88.1, error: null } });
    await expect(testLlmProfile("p1")).resolves.toMatchObject({ ok: true });
    expect(post).toHaveBeenCalledWith("/llm-profiles/p1/test");
  });
});
