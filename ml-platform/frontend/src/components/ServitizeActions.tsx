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
 * 验收通过任务的服务化操作流（§四 + §12.1），分步进度呈现：
 * ① 固化配方 → ② 部署模型（S3 冠军直部署/引擎重铸）→ ③ 服务化草稿
 * → ④ 批准发布。每步 25% 进度；当前步高亮可操作、后续步置灰锁定、
 * 进行中的步显示旋转圆圈；完成自动进入下一步。任一步失败就地显示。
 */

interface DraftResult {
  model_api_id: string;
  model_api_name: string;
  error_classes: string[];
  ambiguous_labels: string[];
  smoke: { prediction?: string; error_matched?: boolean; dry_run?: boolean };
}

type CastPhase = "idle" | "casting" | "deployed" | "failed";

// 步骤状态：done=已完成 ✓ / active=当前可操作（蓝色）/ locked=未到（灰色）
// / busy=执行中（转圈，按钮锁定）
type StepState = "done" | "active" | "locked" | "busy";

function StepSpinner() {
  // 与 v2 风格一致的旋转圆圈（内联 SVG，无外部依赖）
  return (
    <span
      role="status"
      aria-label="loading"
      style={{
        display: "inline-block",
        width: 13,
        height: 13,
        borderRadius: "50%",
        border: "2px solid var(--v2-line, #d9d9d9)",
        borderTopColor: "var(--v2-blue, #1677ff)",
        animation: "v2-step-spin 0.8s linear infinite",
      }}
    />
  );
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
          // 服务化条目状态恢复：已发布 → ③④直接置完成；有草稿 → ④可点
          // （否则已发布的部署再点③会撞 already-published 防护报错）
          if (state.servitize?.status === "published") {
            setDraft((prev) => prev ?? {
              model_api_id: state.servitize?.model_api_id ?? "",
              model_api_name: state.servitize?.model_api_name ?? "",
              error_classes: [],
              ambiguous_labels: [],
              smoke: {},
            });
            setPublished(true);
            setCastNote(zh ? "该部署的服务化条目已发布" : "Servitize entry already published");
          } else if (state.servitize?.status === "offline" && state.servitize.model_api_id) {
            setDraft((prev) => prev ?? {
              model_api_id: state.servitize?.model_api_id ?? "",
              model_api_name: state.servitize?.model_api_name ?? "",
              error_classes: [],
              ambiguous_labels: [],
              smoke: {},
            });
          }
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

  // ---- 分步进度派生（4 步 × 25%）----
  const step1Done = Boolean(recipeId);
  const step2Done = castPhase === "deployed" && Boolean(deploymentId);
  const step3Done = Boolean(draft);
  const step4Done = published;
  const doneCount = [step1Done, step2Done, step3Done, step4Done].filter(Boolean).length;
  const percent = Math.round((doneCount / 4) * 100);
  // 当前步 = 第一个未完成步；其之前的步全 done、之后的全 locked
  const currentStep = step1Done ? (step2Done ? (step3Done ? (step4Done ? 5 : 4) : 3) : 2) : 1;
  const stepBusy = (n: number): boolean => {
    if (n === 1) return busy && !step1Done;
    if (n === 2) return castPhase === "casting";
    if (n === 3) return busy && step2Done && !step3Done;
    if (n === 4) return busy && step3Done && !step4Done;
    return false;
  };
  const stateOf = (n: number): StepState => {
    const done = n === 1 ? step1Done : n === 2 ? step2Done : n === 3 ? step3Done : step4Done;
    if (done) return "done";
    if (n === currentStep) return stepBusy(n) ? "busy" : "active";
    return "locked";
  };

  const stepLabels = zh
    ? ["固化配方", "部署模型", "服务化草稿", "批准发布"]
    : ["Fixate recipe", "Deploy model", "Servitize draft", "Approve"];

  const stepBadge = (state: StepState, n: number) => {
    if (state === "done") return <span style={{ color: "var(--v2-go, #52c41a)", fontWeight: 700 }}>✓</span>;
    if (state === "busy") return <StepSpinner />;
    if (state === "active")
      return <span style={{ color: "var(--v2-blue, #1677ff)", fontWeight: 700 }}>{n}</span>;
    return <span style={{ color: "var(--v2-dim, #bbb)", fontWeight: 700 }}>{n}</span>;
  };

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid var(--v2-line)",
        borderRadius: 10,
        background: "var(--v2-bg)",
        padding: "10px 14px",
      }}
    >
      <style>{`@keyframes v2-step-spin { to { transform: rotate(360deg); } }`}</style>
      {/* 进度条（4 步各 25%） */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <b style={{ fontSize: 13, color: "var(--v2-txt)", whiteSpace: "nowrap" }}>
          {zh ? "服务化操作流" : "Servitization"}
        </b>
        <div
          style={{
            flex: 1,
            minWidth: 120,
            height: 8,
            borderRadius: 4,
            background: "var(--v2-line, #eee)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${percent}%`,
              height: "100%",
              borderRadius: 4,
              background: "linear-gradient(90deg, #52c41a, #389e0d)",
              transition: "width .4s ease",
            }}
          />
        </div>
        <span style={{ fontSize: 12, color: "var(--v2-sub)", whiteSpace: "nowrap" }}>
          {percent}%
        </span>
        {published ? (
          <span className="v2-badge v2-bgo">✓ {zh ? "已发布" : "Published"}</span>
        ) : null}
      </div>

      {/* 步骤条：圆形节点 + 箭头连线（完成段绿色，未到段灰色），
          节点下方步骤名；当前步蓝色高亮、进行中转圈、锁定步灰显 */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          margin: "4px 0 12px",
        }}
      >
        {stepLabels.map((label, index) => {
          const n = index + 1;
          const st = stateOf(n);
          const nextDone = index < 3 && stateOf(n + 1) === "done";
          const connectorDone = st === "done" && (nextDone || n === currentStep - 1 || n === 4);
          const nodeColor =
            st === "done" ? "#52c41a"
              : st === "active" || st === "busy" ? "#1677ff"
                : "#c3c3c3";
          return (
            <div
              key={label}
              style={{
                display: "flex",
                alignItems: "center",
                flex: index < 3 ? "1 1 auto" : "0 0 auto",
                minWidth: 0,
              }}
            >
              {/* 节点列：圆 + 名称 */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 5,
                  minWidth: 76,
                }}
              >
                <div
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 13,
                    fontWeight: 700,
                    border: `2px solid ${nodeColor}`,
                    background:
                      st === "done" ? "rgba(82,196,26,.12)"
                        : st === "active" || st === "busy" ? "rgba(22,119,255,.10)"
                          : "transparent",
                    boxShadow:
                      st === "active" || st === "busy"
                        ? "0 0 0 4px rgba(22,119,255,.10)"
                        : "none",
                    transition: "all .3s ease",
                  }}
                >
                  {st === "done" ? (
                    <span style={{ color: "#52c41a", lineHeight: 1 }}>✓</span>
                  ) : st === "busy" ? (
                    <StepSpinner />
                  ) : (
                    <span style={{ color: st === "active" ? "#1677ff" : "#b5b5b5", lineHeight: 1 }}>{n}</span>
                  )}
                </div>
                <span
                  style={{
                    fontSize: 12,
                    whiteSpace: "nowrap",
                    color:
                      st === "locked" ? "var(--v2-dim, #aaa)"
                        : st === "done" ? "#389e0d"
                          : st === "active" || st === "busy" ? "#1677ff"
                            : "var(--v2-txt)",
                    fontWeight: st === "active" || st === "busy" ? 600 : 400,
                  }}
                >
                  {label}
                </span>
              </div>
              {/* 箭头连线（最后一步之后无） */}
              {index < 3 ? (
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    margin: "0 8px 18px",
                    minWidth: 28,
                  }}
                  aria-hidden
                >
                  <div
                    style={{
                      flex: 1,
                      height: 2,
                      background: connectorDone ? "#52c41a" : "var(--v2-line, #ddd)",
                      transition: "background .3s ease",
                    }}
                  />
                  <div
                    style={{
                      width: 0,
                      height: 0,
                      borderTop: "5px solid transparent",
                      borderBottom: "5px solid transparent",
                      borderLeft: `7px solid ${connectorDone ? "#52c41a" : "var(--v2-line, #ddd)"}`,
                      transition: "border-color .3s ease",
                    }}
                  />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {/* 当前步操作区 */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        {stateOf(1) === "active" ? (
          <button
            type="button"
            className="v2-btn primary"
            style={{ padding: "4px 14px", fontSize: 12 }}
            disabled={busy}
            onClick={() => void fixate()}
          >
            {zh ? "① 固化配方" : "① Fixate recipe"}
          </button>
        ) : null}

        {recipeId && !draft && !published && (stateOf(2) === "active" || stateOf(2) === "busy") ? (
          <>
            <button
              type="button"
              className="v2-btn primary"
              style={{ padding: "4px 14px", fontSize: 12 }}
              disabled={busy || castPhase === "casting"}
              onClick={() => void deployS3()}
            >
              {zh ? "② 直接部署本次模型（秒级）" : "② Deploy accepted model"}
            </button>
            <button
              type="button"
              className="v2-btn"
              style={{ padding: "4px 14px", fontSize: 12 }}
              disabled={busy || castPhase === "casting"}
              onClick={() => void startCast()}
            >
              {zh ? "引擎重铸（全量搜索）" : "Engine recast"}
            </button>
          </>
        ) : null}
        {castNote ? (
          <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>{castNote}</span>
        ) : null}

        {recipeId && !draft && !published && (stateOf(3) === "active" || stateOf(3) === "busy") ? (
          <button
            type="button"
            className="v2-btn primary"
            style={{ padding: "4px 14px", fontSize: 12 }}
            disabled={busy || !deploymentId}
            onClick={() => void draftServitize()}
          >
            {zh ? "③ 一键服务化（草稿+冒烟）" : "③ Servitize draft"}
          </button>
        ) : null}

        {draft && !published ? (
          <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>
            {zh ? "草稿就绪：" : "Draft: "}
            {draft.model_api_name} · {zh ? "缺陷类" : "error classes"}
            [{draft.error_classes.join(",")}] · smoke {draft.smoke?.prediction ?? "-"}
            {draft.smoke?.error_matched ? (zh ? "（命中回流类，dry_run 未写入）" : " (dry-run, no backflow)") : ""}
          </span>
        ) : null}
        {draft && !published && (stateOf(4) === "active" || stateOf(4) === "busy") ? (
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
            ✓ {zh ? "模型 API 已上市场" : "Published to market"}
          </span>
        ) : null}

        {error ? (
          <span style={{ fontSize: 12, color: "var(--v2-red, #e66f75)" }}>注意：{error}</span>
        ) : null}
      </div>
    </div>
  );
}
