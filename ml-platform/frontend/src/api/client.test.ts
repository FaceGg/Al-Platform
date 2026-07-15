import { describe, it, expect } from "vitest";
import apiClient, { formatApiError } from "./client";

describe("apiClient", () => {
  it("creates axios instance with base URL", () => {
    expect(apiClient).toBeDefined();
    expect(apiClient.defaults.baseURL).toBeDefined();
  });

  it("has JSON content type", () => {
    expect(apiClient.defaults.headers["Content-Type"]).toBe("application/json");
  });

  it("has request interceptor", () => {
    expect(apiClient.interceptors.request).toBeDefined();
  });

  it("has response interceptor", () => {
    expect(apiClient.interceptors.response).toBeDefined();
  });

  it("formats structured API errors without object coercion", () => {
    const error = { response: { data: { detail: {
      code: "WORKFLOW_INVALID", message: "Workflow validation failed",
    } } } };
    expect(formatApiError(error, "fallback")).toBe("WORKFLOW_INVALID: Workflow validation failed");
  });
});
