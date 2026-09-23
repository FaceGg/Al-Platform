import { describe, it, expect, beforeEach } from "vitest";
import apiClient, { formatApiError } from "./client";

describe("apiClient", () => {
  beforeEach(() => {
    localStorage.removeItem("lang");
  });

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

  it("localizes known error codes in Chinese by default", () => {
    const error = { response: { data: { detail: {
      code: "TASK_ACTIVE", message: "Cancel the active task before deleting it.",
    } } } };
    expect(formatApiError(error, "fallback")).toBe("请先取消进行中的任务，再执行删除。");
  });

  it("localizes known error codes in English when the UI language is English", () => {
    localStorage.setItem("lang", "en");
    const error = { response: { data: { detail: {
      code: "TASK_ACTIVE", message: "Cancel the active task before deleting it.",
    } } } };
    expect(formatApiError(error, "fallback")).toBe("Cancel the active task before deleting it.");
  });

  it("falls back to code and message for unknown error codes", () => {
    localStorage.setItem("lang", "zh");
    const error = { response: { data: { detail: {
      code: "SOMETHING_ELSE", message: "Unexpected failure",
    } } } };
    expect(formatApiError(error, "fallback")).toBe("SOMETHING_ELSE: Unexpected failure");
  });
});
