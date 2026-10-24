import { useEffect, useState } from "react";
import { fixateRecipe, servitizeDraft, servitizeActivate } from "../api/agentCenter";
import { listDeployments } from "../api/modelRegistry";

/**
 * 验收通过任务的操作流尾部（§四 + §12.1）：
 * 「固化配方」→（选部署）「一键服务化」草稿 →「批准发布」。
 * 任一步失败就地显示错误，不弹全局框。
 */

interface DraftResult {
  model_api_id: string;
  model_api_name: string;
  error_classes: string[];
  ambiguous_labels: string[];
  smoke: { prediction?: string; error_matched?: boolean; dry_run?: boolean };
}

export default function ServitizeActions({
  runId,
  projectId,
  recipeId,
  zh,
  onRecipeFixed,
}: {
  runId: string;
  projectId: string | null;
  recipeId: string | null;
  zh: boolean;
  onRecipeFixed: (recipeId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deployments, setDeployments] = useState<Array<{ id: string; name?: string }>>([]);
  const [deploymentId, setDeploymentId] = useState("");
  const [draft, setDraft] = useState<DraftResult | null>(null);
  const [published, setPublished] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    listDeployments(projectId)
      .then((items) => setDeployments(items.map((item) => ({ id: String(item.id), name: (item as { name?: string }).name }))))
      .catch(() => setDeployments([]));
  }, [projectId]);

  const fixate = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await fixateRecipe(runId);
      onRecipeFixed(result.recipe_id);
    } catch (caught) {
      setError(String((caught as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message ?? caught));
    } finally {
      setBusy(false);
    }
  };

  const draftServitize = async () => {
    if (!recipeId || !deploymentId) return;
    setBusy(true);
    setError("");
    try {
      const result = await servitizeDraft({
        recipe_id: recipeId,
        deployment_id: deploymentId,
        project_id: projectId ?? undefined,
      });
      setDraft(result);
    } catch (caught) {
      setError(String((caught as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message ?? caught));
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      await servitizeActivate(draft.model_api_id);
      setPublished(true);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid var(--v2-line)",
        borderRadius: 10,
        background: "var(--v2-bg)",
        padding: "10px 14px",
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexWrap: "wrap",
      }}
    >
      <b style={{ fontSize: 13, color: "var(--v2-txt)" }}>
        {zh ? "服务化操作流" : "Servitization"}
      </b>

      {recipeId ? (
        <span className="v2-badge v2-bg">recipe ✓ {recipeId.slice(0, 8)}</span>
      ) : (
        <button
          type="button"
          className="v2-btn primary"
          style={{ padding: "4px 14px", fontSize: 12 }}
          disabled={busy}
          onClick={() => void fixate()}
        >
          {zh ? "① 固化配方" : "① Fixate recipe"}
        </button>
      )}

      {recipeId && !draft && !published ? (
        <>
          <select
            className="v2-select"
            style={{ maxWidth: 220 }}
            value={deploymentId}
            onChange={(event) => setDeploymentId(event.target.value)}
          >
            <option value="">{zh ? "选择部署…" : "Pick a deployment…"}</option>
            {deployments.map((deployment) => (
              <option key={deployment.id} value={deployment.id}>
                {deployment.name ?? deployment.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="v2-btn"
            style={{ padding: "4px 14px", fontSize: 12 }}
            disabled={busy || !deploymentId}
            onClick={() => void draftServitize()}
          >
            {zh ? "② 一键服务化（草稿+冒烟）" : "② Servitize draft"}
          </button>
        </>
      ) : null}

      {draft && !published ? (
        <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>
          {zh ? "草稿就绪：" : "Draft: "}
          {draft.model_api_name} · {zh ? "缺陷类" : "error classes"}
          [{draft.error_classes.join(",")}] · smoke {draft.smoke?.prediction ?? "-"}
          {draft.smoke?.error_matched ? (zh ? "（命中回流类，dry_run 未写入）" : " (dry-run, no backflow)") : ""}
        </span>
      ) : null}
      {draft && !published ? (
        <button
          type="button"
          className="v2-btn primary"
          style={{ padding: "4px 14px", fontSize: 12 }}
          disabled={busy}
          onClick={() => void approve()}
        >
          {zh ? "③ 批准发布" : "③ Approve"}
        </button>
      ) : null}

      {published ? (
        <span className="v2-badge v2-bgo">
          ✓ {zh ? "已发布（模型 API 已上市场）" : "Published"}
        </span>
      ) : null}

      {error ? (
        <span style={{ fontSize: 12, color: "var(--v2-red, #e66f75)" }}>⚠ {error}</span>
      ) : null}
    </div>
  );
}
