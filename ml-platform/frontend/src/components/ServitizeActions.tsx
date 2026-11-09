import { useEffect, useRef, useState } from "react";
import {
  castDeploymentCurrent,
  castDeploymentStart,
  castDeploymentStatus,
  fixateRecipe,
  servitizeDraft,
  servitizeActivate,
} from "../api/agentCenter";

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
  const [deploymentId, setDeploymentId] = useState("");
  const [draft, setDraft] = useState<DraftResult | null>(null);
  const [published, setPublished] = useState(false);
  // 铸造新部署流（「启动并服务化」完整语义）
  const [castPhase, setCastPhase] = useState<CastPhase>("idle");
  const [castNote, setCastNote] = useState("");
  const castTimer = useRef<number | null>(null);

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

  // 「② 直接部署本次模型」：S3 验收冠军工件 → 注册/ONNX/批准/部署，秒级
  // 零重训（部署的就是 S4 验收评的那个模型）。旧任务无工件回落引擎重铸。
  const deployS3 = async () => {
    if (!recipeId || !projectId) return;
    setBusy(true);
    setError("");
    setCastPhase("casting");
    setCastNote(zh ? "正在直接部署本次验收的模型（注册→转换→上线，秒级）…" : "Deploying accepted model…");
    try {
      const result = await castDeploymentStart({
        recipe_id: recipeId,
        project_id: projectId,
        run_id: runId,
        mode: "s3",
      });
      if (result.status === "deployed" && result.deployment_id) {
        setCastPhase("deployed");
        setDeploymentId(result.deployment_id);
        setCastNote(zh ? "本次模型已直接部署并自动选中" : "Accepted model deployed & selected");
      }
      setBusy(false);
    } catch (caught) {
      setCastPhase("failed");
      setCastNote("");
      setError(String((caught as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message ?? caught));
      setBusy(false);
    }
  };

  // 「引擎重铸」次选项：按配方触发 AutoML 重训（全量+搜索+集成终选）。
  const startCast = async () => {
    if (!recipeId || !projectId) return;
    setBusy(true);
    setError("");
    setCastPhase("casting");
    setCastNote(zh ? "引擎重铸已触发（全量搜索，约 1-3 分钟）…" : "Engine recast dispatched…");
    try {
      const started = await castDeploymentStart({
        recipe_id: recipeId,
        project_id: projectId,
        run_id: runId,
        mode: "engine",
      });
      startPolling(started.job_id);
    } catch (caught) {
      setCastPhase("failed");
      setCastNote("");
      setError(String((caught as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message ?? caught));
      setBusy(false);
    }
  };

  // 轮询复用（新触发与 mount 恢复共用）
  const startPolling = (jobId: string) => {
    castTimer.current = window.setInterval(async () => {
      try {
        const status = await castDeploymentStatus(jobId, recipeId ?? "");
        if (status.status === "deployed" && status.deployment_id) {
          window.clearInterval(castTimer.current ?? undefined);
          castTimer.current = null;
          setCastPhase("deployed");
          setCastNote(zh
            ? `新部署已就绪（${status.deployment_state ?? "running"}）并已自动选中`
            : `New deployment ready (${status.deployment_state ?? "running"}) and selected`);
          setDeploymentId(status.deployment_id);
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
  };

  // 进入页面恢复铸造状态：退出重进后无需重新点②——在途自动续轮询、
  // 已部署自动选中（触发端幂等兜底重复点击）。
  useEffect(() => {
    if (!recipeId || !projectId) return;
    let cancelled = false;
    castDeploymentCurrent(recipeId)
      .then((state) => {
        if (cancelled) return;
        if (state.status === "deployed" && state.deployment_id) {
          setCastPhase("deployed");
          setDeploymentId(state.deployment_id);
          setCastNote(zh ? `铸造部署已就绪（${state.deployment_state ?? "running"}）` : "Cast deployment ready");
        } else if (["pending", "queued", "running", "cancel_requested"].includes(state.status) && state.job_id) {
          setCastPhase("casting");
          setBusy(true);
          setCastNote(zh ? "铸造进行中（已恢复轮询）…" : "Casting (resumed)…");
          startPolling(state.job_id);
        } else if (state.status === "failed" || state.status === "vetoed") {
          setCastPhase("failed");
          if (state.error) setError(state.error);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipeId, projectId]);

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
          {/* ② 直接部署本次模型：S3 验收冠军秒级上线（推荐）+引擎重铸次选项 */}
          <button
            type="button"
            className="v2-btn primary"
            style={{
              padding: "4px 14px",
              fontSize: 12,
              ...(castPhase === "deployed"
                ? { borderColor: "var(--v2-gold, #d4a72c)" }
                : {}),
            }}
            disabled={busy || castPhase === "casting" || castPhase === "deployed"}
            onClick={() => void deployS3()}
          >
            {zh ? "② 直接部署本次模型（秒级）" : "② Deploy accepted model"}
          </button>
          <button
            type="button"
            className="v2-btn"
            style={{ padding: "4px 14px", fontSize: 12 }}
            disabled={busy || castPhase === "casting" || castPhase === "deployed"}
            onClick={() => void startCast()}
          >
            {zh ? "引擎重铸（全量搜索）" : "Engine recast"}
          </button>
          {castNote ? (
            <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>{castNote}</span>
          ) : null}
          {castPhase === "deployed" ? (
            <span className="v2-badge v2-bgo">✓ {zh ? "新部署已就绪" : "deployed"}</span>
          ) : null}
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
