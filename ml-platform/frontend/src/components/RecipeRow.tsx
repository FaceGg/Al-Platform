import { useState } from "react";
import {
  listRecipeVersions,
  rollbackRecipe,
  type PipelineRecipeItem,
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

  const toggle = () => {
    if (versions) {
      setVersions(null);
      return;
    }
    listRecipeVersions(recipe.id).then(setVersions).catch(() => setVersions([]));
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
        </td>
      </tr>
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
                      ↩ {zh ? `回滚到 v${item.version}` : `Rollback to v${item.version}`}
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
