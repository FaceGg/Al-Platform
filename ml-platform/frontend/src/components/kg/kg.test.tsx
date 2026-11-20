import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import ExtractionControl from "./ExtractionControl";
import FusionPanel from "./FusionPanel";
import OntologyModal from "./OntologyModal";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({ default: { get, post } }));
vi.mock("../../i18n", () => ({
  useI18n: () => ({ t: { common: { error: "Error", loading: "No data" } }, lang: "zh" }),
}));

describe("ExtractionControl", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("quick extract posts rules mode and reports the result", async () => {
    post.mockResolvedValue({ data: { entities_created: 3, relations_created: 2 } });
    const onExtracted = vi.fn();
    render(<ExtractionControl kbId="kb-1" onExtracted={onExtracted} />);

    fireEvent.click(screen.getByRole("button", { name: /快速抽取/ }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/extract", { mode: "rules" });
    });
    await waitFor(() => {
      expect(onExtracted).toHaveBeenCalled();
    });
  });

  it("deep extract starts a job and polls until succeeded", async () => {
    post.mockResolvedValue({ data: { mode: "llm", job_id: "job-1", channel: "celery" } });
    get.mockResolvedValue({
      data: {
        id: "job-1", status: "succeeded", total_units: 4, done_units: 4,
        progress: 100, entities_found: 9, relations_found: 5,
        llm_calls: 4, llm_errors: 0,
      },
    });
    const onExtracted = vi.fn();
    render(<ExtractionControl kbId="kb-1" onExtracted={onExtracted} />);
    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    // 轮询间隔 2s（真实定时器），首次轮询即终态
    await waitFor(() => expect(onExtracted).toHaveBeenCalled(), { timeout: 5000 });
    expect(get).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/extract/jobs/job-1");
  }, 15000);
});

describe("FusionPanel", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("lists pending suggestions and accepts a merge", async () => {
    get.mockResolvedValue({
      data: [
        {
          id: "s-1", type: "merge_entity", status: "pending", method: "llm",
          similarity: 0.95, canonical_name: null,
          entity_a: { id: "a", name: "点焊", type: "工艺" },
          entity_b: { id: "b", name: "spot welding", type: "工艺" },
          payload: { reason: "同义" },
        },
      ],
    });
    post.mockResolvedValue({ data: { status: "accepted" } });
    const onChanged = vi.fn();
    render(<FusionPanel kbId="kb-1" onChanged={onChanged} />);

    await screen.findByTestId("kg-fusion-item");
    expect(screen.getByText("点焊")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /确认/ }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/fusion/suggestions/s-1/accept", {});
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("resolves attribute conflicts with the chosen value", async () => {
    get.mockResolvedValue({
      data: [
        {
          id: "s-2", type: "attribute_conflict", status: "pending", method: "auto",
          similarity: null, canonical_name: null,
          entity_a: { id: "a", name: "电流", type: "指标" }, entity_b: null,
          payload: { attribute: "典型值", values: [{ value: "8kA" }, { value: "10kA" }] },
        },
      ],
    });
    post.mockResolvedValue({ data: { status: "accepted" } });
    render(<FusionPanel kbId="kb-1" />);

    await screen.findByTestId("kg-conflict-radio");
    fireEvent.click(screen.getByLabelText("10kA"));
    fireEvent.click(screen.getByRole("button", { name: /确认/ }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        "/knowledge/bases/kb-1/graph/fusion/suggestions/s-2/accept",
        { resolved: { value: "10kA" } },
      );
    });
  });
});

describe("OntologyModal", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("loads the ontology and saves edits", async () => {
    get.mockResolvedValue({
      data: {
        ontology: { entity_types: ["工艺", "缺陷"], relation_types: ["导致缺陷"] },
        custom: false,
      },
    });
    const put = vi.fn().mockResolvedValue({ data: {} });
    (await import("../../api/client")).default.put = put;
    render(<OntologyModal kbId="kb-1" open onClose={() => {}} />);

    await screen.findByText("工艺");
    expect(get).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/ontology");
    expect(screen.getByText("工艺")).toBeInTheDocument();
    expect(screen.getByText("导致缺陷")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() => {
      expect(put).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/ontology", {
        entity_types: ["工艺", "缺陷"],
        relation_types: ["导致缺陷"],
      });
    });
  });
});
