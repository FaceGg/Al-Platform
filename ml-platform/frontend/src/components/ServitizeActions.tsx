import { useEffect, useRef, useState } from "react";
import {
  castDeploymentStart,
  castDeploymentStatus,
  fixateRecipe,
  servitizeDraft,
  servitizeActivate,
} from "../api/agentCenter";
import { listDeployments } from "../api/modelRegistry";

/**
 * 验收通过任务的操作流尾部（§四 + §12.1）：
 * 「固化配方」→「铸造新部署」（按配方最优/集成落地为 running 部署）→
 * 「一键服务化」草稿 →「批准发布」。任一步失败就地显示错误，不弹全局框。
 */

interface DraftResult {
  model_api_id: string;
  model_api_name: string;
  error_classes: string[];
  ambiguous_labels: string[];
  smoke: { prediction?: string; error_matched?: boolean; dry_run?: boolean };
}

type CastPhase = "idle" | "casting" | "deployed" | "failed";

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
  // 铸造新部署流（「启动并服务化」完整语义）
  const [castPhase, setCastPhase] = useState<CastPhase>("idle");
  const [castNote, setCastNote] = useState("");
  const castTimer = useRef<number | null>(null);

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

  // 「② 铸造新部署」：按配方触发引擎铸造（白名单/集成/列随配方）→ 轮询 →
  // 完成后自动选中新部署并刷新下拉；失败/否决就地提示。
  const startCast = async () => {
    if (!recipeId || !projectId) return;
    setBusy(true);
    setError("");
    setCastPhase("casting");
    setCastNote(zh ? "铸造任务已触发，引擎训练最优模型中（约 1-3 分钟）…" : "Casting job dispatched…");
    try {
      const started = await castDeploymentStart({
        recipe_id: recipeId,
        project_id: projectId,
        run_id: runId,
      });
      const jobId = started.job_id;
      castTimer.current = window.setInterval(async () => {
        try {
          const status = await castDeploymentStatus(jobId, recipeId);
          if (status.status === "deployed" && status.deployment_id) {
            window.clearInterval(castTimer.current ?? undefined);
            castTimer.current = null;
            setCastPhase("deployed");
            setCastNote(zh
              ? `新部署已就绪（${status.deployment_state ?? "running"}）并已自动选中`
              : `New deployment ready (${status.deployment_state ?? "running"}) and selected`);
            setDeploymentId(status.deployment_id);
            // 刷新下拉让新部署可见
            listDeployments(projectId)
              .then((items) => setDeployments(items.map((item) => ({ id: String(item.id), name: (item as { name?: string }).name }))))
              .catch(() => undefined);
            setBusy(false);
          } else if (status.status === "failed" || status.status === "vetoed") {
            window.clearInterval(castTimer.current ?? undefined);
            castTimer.current = null;
            setCastPhase("failed");
            setCastNote("");
            setError(status.error ?? status.status);
            setBusy(false);
          } else {
            setCastNote(zh
              ? `铸造中（${status.status === "running" ? "训练执行中" : "排队中"}）…`
              : `Casting (${status.status})…`);
          }
        } catch {
          // 单次轮询失败忽略，下一轮再查
        }
      }, 10000);
    } catch (caught) {
      setCastPhase("failed");
      setCastNote("");
      setError(String((caught as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message ?? caught));
      setBusy(false);
    }
  };

  useEffect(() => () => {
    if (castTimer.current) window.clearInterval(castTimer.current);
  }, []);

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
          {/* ② 铸造新部署：按配方最优模型/集成落地为 running 部署（推荐路径） */}
          <button
            type="button"
            className="v2-btn"
            style={{
              padding: "4px 14px",
              fontSize: 12,
              ...(castPhase === "deployed"
                ? { borderColor: "var(--v2-gold, #d4a72c)" }
                : {}),
            }}
            disabled={busy || castPhase === "casting" || castPhase === "deployed"}
            onClick={() => void startCast()}
          >
            {zh ? "② 铸造新部署（本次最优）" : "② Cast new deployment"}
          </button>
          {castNote ? (
            <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>{castNote}</span>
          ) : null}
          {castPhase === "deployed" ? (
            <span className="v2-badge v2-bgo">✓ {zh ? "新部署已就绪" : "deployed"}</span>
          ) : null}
          <span style={{ fontSize: 11.5, color: "var(--v2-dim)" }}>
            {zh ? "或绑定既有部署：" : "Or bind existing:"}
          </span>
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
            {zh ? "③ 一键服务化（草稿+冒烟）" : "③ Servitize draft"}
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
          {zh ? "④ 批准发布" : "④ Approve"}
        </button>
      ) : null}

      {published ? (
        <span className="v2-badge v2-bgo">
          ✓ {zh ? "已发布（模型 API 已上市场）" : "Published"}
        </span>
      ) : null}

      {error ? (
        <span style={{ fontSize: 12, color: "var(--v2-red, #e66f75)" }}>注意：{error}</span>
      ) : null}
    </div>
  );
}
