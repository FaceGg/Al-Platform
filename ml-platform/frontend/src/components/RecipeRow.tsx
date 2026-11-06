import { useState } from "react";
import { Modal, Popconfirm, message } from "antd";
import {
  deleteRecipe,
  getRecipeDetail,
  listRecipeVersions,
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
  const [versions, setVersions] = useState<RecipeVersion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<RecipeDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

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
        <td>{recipe.domain ?? "-"}</td>
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
        <td>
          <button
            type="button"
            className="v2-chip"
            style={{ cursor: "pointer" }}
            onClick={toggle}
          >
            {versions ? "▾" : "▸"} {zh ? "版本" : "Versions"}
          </button>
          <button
            type="button"
            className="v2-chip"
            style={{ cursor: "pointer", marginLeft: 6 }}
            onClick={() => void openDetail()}
          >
            {zh ? "详情" : "Detail"}
          </button>
          <Popconfirm
            title={zh ? "删除配方？" : "Delete recipe?"}
            description={zh ? "将删除全部版本；不影响已部署模型（部署持内容副本）。" : "All versions removed; deployed models keep their copies."}
            okText={zh ? "删除" : "Delete"}
            cancelText={zh ? "取消" : "Cancel"}
            okButtonProps={{ danger: true }}
            onConfirm={() => void remove()}
          >
            <button
              type="button"
              className="v2-chip"
              style={{ cursor: deleting ? "wait" : "pointer", marginLeft: 6, color: "var(--v2-red)" }}
              disabled={deleting}
            >
              {zh ? "删除" : "Delete"}
            </button>
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
                {zh ? "域" : "Domain"}：{detail.domain || "-"} · {zh ? "目标列" : "Target"}：
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
      {versions ? (
        <tr>
          <td colSpan={9} style={{ background: "rgba(36,52,79,.25)", padding: "6px 18px" }}>
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
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return value;
  const delta = Date.now() - timestamp;
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return zh ? "刚刚" : "just now";
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return zh ? `${days} 天前` : `${days}d ago`;
}
