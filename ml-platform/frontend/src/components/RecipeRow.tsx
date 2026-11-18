import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, InputNumber, Modal, Popconfirm, Select, Switch, message } from "antd";
import { DeleteOutlined, EyeOutlined, PlayCircleOutlined } from "@ant-design/icons";
import { parseBackendTime } from "../utils/time";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import {
  deleteRecipe,
  getRecipeDetail,
  listRecipeVersions,
  reuseRecipe,
  rollbackRecipe,
  type PipelineRecipeItem,
  type RecipeDetail,
} from "../api/agentCenter";

interface RecipeVersion {
  version: number;
  status: string;
  change_note: string | null;
  created_at: string | null;
  baseline_metrics: Record<string, number>;
}

interface DatasetOption { id: string; name?: string; filename?: string; row_count?: number; column_count?: number }

/** 配方表行 + 可展开版本树（含 git 式回滚：回滚=发新版本携带旧内容）。 */
export default function RecipeRow({
  recipe,
  zh,
  onChanged,
}: {
  recipe: PipelineRecipeItem;
  zh: boolean;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [versions, setVersions] = useState<RecipeVersion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<RecipeDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // 一键复用（2026-11-18 用户需求）：选数据集 + 改配置项 → 按配方 guidance
  // 快照重建智能体任务并立即启动；源任务思考链随 S1 注入。
  const [reuseOpen, setReuseOpen] = useState(false);
  const [reuseBusy, setReuseBusy] = useState(false);
  const [reuseLoading, setReuseLoading] = useState(false);
  const [reuseDatasets, setReuseDatasets] = useState<DatasetOption[]>([]);
  const [reuseDatasetId, setReuseDatasetId] = useState("");
  const [reuseColumns, setReuseColumns] = useState<string[]>([]);
  const [reuseTarget, setReuseTarget] = useState("");
  const [reuseMaxRounds, setReuseMaxRounds] = useState(3);
  const [reuseEnsemble, setReuseEnsemble] = useState(false);
  const [reuseTopK, setReuseTopK] = useState(3);
  const [reuseTaskType, setReuseTaskType] = useState("supervised");
  const [reuseError, setReuseError] = useState("");

  const toggle = () => {
    if (versions) {
      setVersions(null);
      return;
    }
    listRecipeVersions(recipe.id).then(setVersions).catch(() => setVersions([]));
  };

  const openDetail = async () => {
    setDetailOpen(true);
    try {
      setDetail(await getRecipeDetail(recipe.id));
    } catch {
      setDetail(null);
      message.error(zh ? "配方详情加载失败" : "Failed to load recipe detail");
    }
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await deleteRecipe(recipe.id);
      message.success(zh ? "配方已删除" : "Recipe deleted");
      onChanged();
    } catch {
      message.error(zh ? "配方删除失败" : "Failed to delete recipe");
    } finally {
      setDeleting(false);
    }
  };

  const rollback = async (toVersion: number) => {
    setBusy(true);
    try {
      await rollbackRecipe(recipe.id, toVersion);
      const fresh = await listRecipeVersions(recipe.id);
      setVersions(fresh);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  // ---- 一键复用 ----
  const openReuse = async () => {
    setReuseOpen(true);
    setReuseError("");
    setReuseLoading(true);
    setReuseTarget(recipe.target_column ?? "");
    try {
      // 弹窗打开先取配方详情拿 guidance 快照默认值（复用=从配方出发改少量项）
      const fresh = detail ?? (await getRecipeDetail(recipe.id));
      setDetail(fresh);
      const guidance = (fresh.content?.guidance ?? {}) as {
        task_type?: string;
        max_rounds?: number;
        modeling?: { ensemble?: { enabled?: boolean; top_k?: number } };
      };
      setReuseTaskType(guidance.task_type ?? "supervised");
      setReuseMaxRounds(guidance.max_rounds ?? 3);
      setReuseEnsemble(Boolean(guidance.modeling?.ensemble?.enabled));
      setReuseTopK(guidance.modeling?.ensemble?.top_k ?? 3);
      if (guidance.task_type !== "anomaly" && fresh.target_column) {
        setReuseTarget(fresh.target_column);
      } else {
        setReuseTarget("");
      }
      const items = await listDatasets(recipe.project_id ?? undefined);
      setReuseDatasets(Array.isArray(items) ? items : []);
    } catch {
      setReuseError(zh ? "配方/数据集加载失败" : "Failed to load recipe/datasets");
    } finally {
      setReuseLoading(false);
    }
  };

  // 选定数据集后拉列清单（目标列下拉可选项）
  const onReuseDatasetChange = async (datasetId: string) => {
    setReuseDatasetId(datasetId);
    setReuseColumns([]);
    if (!datasetId) return;
    try {
      const data = await getDatasetPreview(datasetId);
      const cols: string[] = Array.isArray((data as { columns?: unknown }).columns)
        ? ((data as { columns: unknown[] }).columns.filter(
            (c): c is string => typeof c === "string",
          ))
        : [];
      setReuseColumns(cols);
      // 换数据后目标列不再有效就清掉；仍存在则保留预填
      if (cols.length && reuseTarget && !cols.includes(reuseTarget)) {
        setReuseTarget("");
      }
    } catch {
      // 列清单拉不到时目标列退化为手输框（Select showsSearch 兜底）
    }
  };

  const submitReuse = async () => {
    if (!reuseDatasetId) {
      setReuseError(zh ? "请选择数据集" : "Pick a dataset");
      return;
    }
    if (reuseTaskType !== "anomaly" && !reuseTarget) {
      setReuseError(zh ? "请选择目标列" : "Pick a target column");
      return;
    }
    setReuseBusy(true);
    setReuseError("");
    try {
      const result = await reuseRecipe(recipe.id, {
        dataset_artifact_id: reuseDatasetId,
        target_column: reuseTaskType === "anomaly" ? null : reuseTarget,
        project_id: recipe.project_id,
        guidance_overrides: {
          max_rounds: reuseMaxRounds,
          modeling: { ensemble: { enabled: reuseEnsemble, top_k: reuseTopK } },
        },
      });
      setReuseOpen(false);
      message.success(zh ? `复用任务已创建并启动（${result.run_id.slice(0, 8)}）` : "Reuse run started");
      onChanged();
      navigate(`/agent/task/${result.run_id}`);
    } catch (caught) {
      const detailMsg = (caught as { response?: { data?: { detail?: { message?: string } } } })
        ?.response?.data?.detail?.message;
      setReuseError(String(detailMsg ?? caught));
    } finally {
      setReuseBusy(false);
    }
  };

  const content = detail?.content ?? {};
  const gates = (content.acceptance_gates ?? {}) as Record<string, number>;
  const featureScript = String(content.feature_script ?? "");
  const algorithmIds = (content.retrain_algorithm_ids ?? []) as string[];
  const retrainEnsemble = (content.retrain_ensemble ?? {}) as { enabled?: boolean; top_k?: number };

  return (
    <>
      <tr>
        <td className="tt">{recipe.name}</td>
        <td>{recipe.project_name ?? "-"}</td>
        <td className="tt">{recipe.target_column ?? "-"}</td>
        <td>v{recipe.current_version}</td>
        <td>
          <span
            className={`v2-badge ${recipe.version_status === "current" ? "v2-bg" : "v2-bgray"}`}
          >
            {recipe.version_status ?? "-"}
          </span>
        </td>
        <td title={recipe.change_note ?? ""}>
          {recipe.change_note
            ? recipe.change_note.length > 24
              ? recipe.change_note.slice(0, 24) + "…"
              : recipe.change_note
            : "-"}
        </td>
        <td>{relative(recipe.updated_at ?? recipe.created_at, zh)}</td>
        <td style={{ whiteSpace: "nowrap" }}>
          <Button type="link" size="small" onClick={toggle}>
            {versions ? "▾" : "▸"} {zh ? "版本" : "Versions"}
          </Button>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => void openDetail()}>
            {zh ? "详情" : "Detail"}
          </Button>
          <Button
            type="link"
            size="small"
            icon={<PlayCircleOutlined />}
            title={zh ? "用该配方一键复用建模：选数据集、改少量配置后重建智能体任务" : "Reuse this recipe for a new run"}
            onClick={() => void openReuse()}
          >
            {zh ? "复用" : "Reuse"}
          </Button>
          <Popconfirm
            title={zh ? "删除配方？" : "Delete recipe?"}
            description={zh ? "将删除全部版本；不影响已部署模型（部署持内容副本）。" : "All versions removed; deployed models keep their copies."}
            okText={zh ? "删除" : "Delete"}
            cancelText={zh ? "取消" : "Cancel"}
            okButtonProps={{ danger: true }}
            onConfirm={() => void remove()}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled={deleting}>
              {zh ? "删除" : "Delete"}
            </Button>
          </Popconfirm>
        </td>
      </tr>
      <Modal
        open={detailOpen}
        title={`${recipe.name} · v${detail?.current_version ?? recipe.current_version}`}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={760}
      >
        {!detail ? (
          <div className="v2-empty">{zh ? "加载中…" : "Loading…"}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12.5 }}>
            <div>
              <b>{zh ? "基础" : "Basics"}</b>
              <div style={{ color: "var(--v2-sub)", marginTop: 4 }}>
                {zh ? "目标列" : "Target"}：
                <span className="tt">{detail.target_column || "-"}</span> · {zh ? "更新" : "Updated"}：
                {relative(detail.updated_at ?? detail.created_at, zh)}
              </div>
            </div>
            <div>
              <b>{zh ? "验收门禁" : "Acceptance gates"}</b>
              <div style={{ color: "var(--v2-sub)", marginTop: 4 }}>
                {Object.keys(gates).length
                  ? Object.entries(gates).map(([key, value]) => `${key} ≥ ${value}`).join("；")
                  : "-"}
              </div>
            </div>
            <div>
              <b>{zh ? "重训配置" : "Retrain config"}</b>
              <div style={{ color: "var(--v2-sub)", marginTop: 4 }}>
                {zh ? "集成" : "Ensemble"}：{retrainEnsemble.enabled
                  ? `${zh ? "开启（前" : "on (top-"}${retrainEnsemble.top_k ?? 3}${zh ? "名加权投票）" : " soft-voting)"}`
                  : zh ? "关闭" : "off"}
                {" · "}{zh ? "算法白名单" : "Whitelist"}：
                {algorithmIds.length ? algorithmIds.join("、") : (zh ? "全族" : "all")}
              </div>
            </div>
            <div>
              <b>{zh ? "特征脚本" : "Feature script"}</b>
              <div className="codebox" style={{ marginTop: 4, maxHeight: 260, overflowY: "auto" }}>
                {featureScript || (zh ? "（无）" : "(none)")}
              </div>
            </div>
            <div>
              <b>{zh ? `版本（${detail.versions.length}）` : `Versions (${detail.versions.length})`}</b>
              <div style={{ marginTop: 4 }}>
                {detail.versions.map((item) => (
                  <div key={item.version} style={{ display: "flex", gap: 10, padding: "2px 0" }}>
                    <b className="tt" style={{ width: 40 }}>v{item.version}</b>
                    <span className={`v2-badge ${item.status === "current" ? "v2-bg" : "v2-bgray"}`}>{item.status}</span>
                    <span style={{ color: "var(--v2-sub)", flex: 1 }}>{item.change_note ?? "-"}</span>
                    <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>{relative(item.created_at, zh)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>
      <Modal
        open={reuseOpen}
        title={`${zh ? "复用配方" : "Reuse recipe"}：${recipe.name}`}
        onCancel={() => setReuseOpen(false)}
        onOk={() => void submitReuse()}
        okText={zh ? "启动复用任务" : "Start reuse run"}
        cancelText={zh ? "取消" : "Cancel"}
        confirmLoading={reuseBusy}
        width={560}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12, fontSize: 12.5 }}>
          <div style={{ color: "var(--v2-sub)" }}>
            {zh
              ? "按配方的提交配置快照重建智能体任务（源任务的大模型思考与决策链会注入新任务的建模推理）。下方仅列常用修改项，其余配置沿用配方。"
              : "Rebuild a run from this recipe's guidance snapshot. The source task's LLM reasoning trace is injected into the new run."}
          </div>
          <label>
            <b>{zh ? "数据集（必选）" : "Dataset (required)"}</b>
            <Select
              showSearch
              optionFilterProp="label"
              style={{ width: "100%", marginTop: 4 }}
              placeholder={reuseLoading ? (zh ? "加载中…" : "Loading…") : zh ? "选择数据集" : "Pick a dataset"}
              value={reuseDatasetId || undefined}
              onChange={(value) => void onReuseDatasetChange(value as string)}
              options={reuseDatasets.map((item) => ({
                value: item.id,
                label: `${item.name ?? item.filename ?? item.id}（${item.row_count ?? "?"} 行）`,
              }))}
            />
          </label>
          {reuseTaskType !== "anomaly" ? (
            <label>
              <b>{zh ? "目标列" : "Target column"}</b>
              {reuseColumns.length ? (
                <Select
                  showSearch
                  style={{ width: "100%", marginTop: 4 }}
                  placeholder={zh ? "选择目标列" : "Pick target"}
                  value={reuseTarget || undefined}
                  onChange={(value) => setReuseTarget(value as string)}
                  options={reuseColumns.map((c) => ({ value: c, label: c }))}
                />
              ) : (
                <input
                  value={reuseTarget}
                  onChange={(e) => setReuseTarget(e.target.value)}
                  placeholder={recipe.target_column ?? ""}
                  style={{ width: "100%", marginTop: 4, padding: "4px 10px", borderRadius: 8, border: "1px solid var(--v2-line)", background: "var(--v2-input-bg)", color: "var(--v2-txt)" }}
                />
              )}
            </label>
          ) : (
            <div style={{ color: "var(--v2-sub)" }}>{zh ? "无监督配方：无目标列" : "Anomaly recipe: no target column"}</div>
          )}
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <b>{zh ? "迭代上限" : "Max rounds"}</b>
              <InputNumber min={1} max={10} value={reuseMaxRounds} onChange={(v) => setReuseMaxRounds(Number(v) || 3)} />
            </label>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <b>{zh ? "集成学习" : "Ensemble"}</b>
              <Switch checked={reuseEnsemble} onChange={(v) => setReuseEnsemble(v)} />
            </label>
            {reuseEnsemble ? (
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                <b>Top-K</b>
                <InputNumber min={2} max={5} value={reuseTopK} onChange={(v) => setReuseTopK(Number(v) || 3)} />
              </label>
            ) : null}
          </div>
          {reuseError ? <div style={{ color: "var(--v2-red, #e66f75)" }}>{reuseError}</div> : null}
        </div>
      </Modal>
      {versions ? (
        <tr>
          <td colSpan={8} style={{ background: "rgba(36,52,79,.25)", padding: "6px 18px" }}>
            {versions.length === 0 ? (
              <span className="v2-empty">{zh ? "无版本记录" : "No versions"}</span>
            ) : (
              versions.map((item) => (
                <div
                  key={item.version}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    fontSize: 12,
                    padding: "3px 0",
                  }}
                >
                  <b className="tt" style={{ width: 44 }}>v{item.version}</b>
                  <span
                    className={`v2-badge ${item.status === "current" ? "v2-bg" : "v2-bgray"}`}
                  >
                    {item.status}
                  </span>
                  <span style={{ color: "var(--v2-sub)", flex: 1 }}>
                    {item.change_note ?? "-"}
                    {item.baseline_metrics?.recall_minority !== undefined
                      ? ` · recall=${item.baseline_metrics.recall_minority}`
                      : ""}
                  </span>
                  <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>
                    {relative(item.created_at, zh)}
                  </span>
                  {item.status !== "current" ? (
                    <button
                      type="button"
                      className="v2-chip"
                      style={{ cursor: busy ? "wait" : "pointer" }}
                      disabled={busy}
                      onClick={() => rollback(item.version)}
                    >
                      {zh ? `回滚到 v${item.version}` : `Rollback to v${item.version}`}
                    </button>
                  ) : null}
                </div>
              ))
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}

function relative(value: string | null, zh: boolean): string {
  if (!value) return "-";
  // 后端时间为不带时区的 UTC ISO——必须经 parseBackendTime 补 Z 再解析，
  // 否则被当成本地时间，相对时间偏差一个时区（更新时间列 8 小时错位）。
  const parsed = parseBackendTime(value);
  if (!parsed) return value;
  const delta = Date.now() - parsed.getTime();
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return zh ? "刚刚" : "just now";
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return zh ? `${days} 天前` : `${days}d ago`;
}
