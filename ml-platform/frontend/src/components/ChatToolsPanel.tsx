import { useEffect, useMemo, useState } from "react";
import { ToolOutlined, SafetyOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

interface WhitelistResponse {
  read_tools?: string[];
  insight_tools?: string[];
  write_tools?: string[];
}

interface PendingInvocation {
  tool: string;
  kind: "read" | "write" | "insight";
  needsConfirm: boolean;
  message?: string;
}

/**
 * Whitelisted chat tools with the §15 write-confirmation card:
 * write tools first run unconfirmed, the backend answers
 * confirmation_required, and only an explicit user click re-submits
 * with confirmed=true.
 */
export default function ChatToolsPanel({ onResult }: { onResult: (text: string) => void }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [whitelist, setWhitelist] = useState<WhitelistResponse>({});
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<PendingInvocation | null>(null);
  const [paramsText, setParamsText] = useState("{}");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiClient.get("/chat-tools/whitelist").then((r) => setWhitelist(r.data || {})).catch(() => setWhitelist({}));
  }, []);

  const entries = useMemo(() => {
    const list: { tool: string; kind: PendingInvocation["kind"] }[] = [];
    (whitelist.insight_tools || []).forEach((tool) => list.push({ tool, kind: "insight" }));
    (whitelist.read_tools || []).forEach((tool) => list.push({ tool, kind: "read" }));
    (whitelist.write_tools || []).forEach((tool) => list.push({ tool, kind: "write" }));
    return list;
  }, [whitelist]);

  const kindLabel = (kind: PendingInvocation["kind"]) =>
    kind === "write" ? (zh ? "写" : "write") : kind === "insight" ? (zh ? "洞察" : "insight") : zh ? "读" : "read";
  const kindClass = (kind: PendingInvocation["kind"]) =>
    kind === "write" ? "v2-bgo" : kind === "insight" ? "v2-bp" : "v2-bb";

  const pick = (tool: string, kind: PendingInvocation["kind"]) => {
    setSelected({ tool, kind, needsConfirm: false });
    setParamsText("{}");
    setError("");
  };

  const run = async (confirmed: boolean) => {
    if (!selected) return;
    let params: Record<string, unknown>;
    try {
      params = paramsText.trim() ? JSON.parse(paramsText) : {};
    } catch {
      setError(zh ? "参数不是合法 JSON" : "params must be valid JSON");
      return;
    }
    setRunning(true);
    setError("");
    try {
      const res = await apiClient.post("/chat-tools/execute", { tool: selected.tool, params, confirmed });
      const data = res.data || {};
      if (data.status === "confirmation_required") {
        setSelected({ ...selected, needsConfirm: true, message: data.message });
      } else if (data.status === "success") {
        onResult(`[${selected.tool}] ${JSON.stringify(data.result, null, 2)}`);
        setSelected(null);
      } else {
        setError(`${data.code ?? "failed"}: ${data.message ?? ""}`.trim());
      }
    } catch (e: any) {
      setError(String(e?.response?.data?.detail || e?.message || e));
    } finally {
      setRunning(false);
    }
  };

  if (entries.length === 0) return null;

  return (
    <div style={{ marginBottom: 8 }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12,
          padding: "3px 10px", borderRadius: 8, cursor: "pointer",
          border: "1px solid rgba(92,178,255,.35)", background: "rgba(47,155,245,.10)",
          color: "inherit",
        }}
      >
        <ToolOutlined />{zh ? `白名单工具 (${entries.length})` : `Tools (${entries.length})`}{open ? " ▴" : " ▾"}
      </button>

      {open && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
          {entries.map(({ tool, kind }) => (
            <button
              key={tool}
              type="button"
              onClick={() => pick(tool, kind)}
              style={{
                fontSize: 11.5, padding: "2px 9px", borderRadius: 9, cursor: "pointer",
                border: "1px solid rgba(36,52,79,.9)", background: "rgba(22,34,58,.6)", color: "inherit",
              }}
            >
              {tool} <span style={{ opacity: 0.75 }}>[{kindLabel(kind)}]</span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div style={{
          marginTop: 10, border: "1px solid rgba(92,178,255,.35)", borderRadius: 10,
          background: "rgba(47,155,245,.06)", padding: "10px 12px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span className={`v2-badge ${kindClass(selected.kind)}`}>{selected.tool}</span>
            <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>
              {selected.kind === "write" ? (zh ? "写操作——需要确认后执行" : "write — requires confirmation") : zh ? "只读操作" : "read-only"}
            </span>
          </div>
          <textarea
            value={paramsText}
            onChange={(e) => setParamsText(e.target.value)}
            rows={3}
            aria-label={zh ? "工具参数 JSON" : "Tool params JSON"}
            style={{
              width: "100%", fontFamily: "Consolas, monospace", fontSize: 12,
              background: "rgba(13,20,32,.7)", color: "inherit",
              border: "1px solid rgba(36,52,79,.9)", borderRadius: 8, padding: "6px 10px",
            }}
          />
          {selected.needsConfirm ? (
            <div style={{
              display: "flex", alignItems: "center", gap: 10, marginTop: 8,
              border: "1px solid rgba(255,209,102,.4)", background: "rgba(255,209,102,.08)",
              borderRadius: 8, padding: "7px 10px", flexWrap: "wrap",
            }}>
              <SafetyOutlined style={{ color: "#ffd166" }} />
              <span style={{ fontSize: 12 }}>{selected.message}</span>
              <button
                type="button"
                onClick={() => void run(true)}
                disabled={running}
                style={{
                  marginLeft: "auto", fontSize: 12, padding: "4px 14px", borderRadius: 8, cursor: "pointer",
                  border: "none", background: "linear-gradient(135deg,#2f9bf5,#1d6fd0)", color: "#fff",
                }}
              >
                {running ? (zh ? "执行中…" : "Running…") : (zh ? "确认执行" : "Confirm & run")}
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button
                type="button"
                onClick={() => void run(false)}
                disabled={running}
                style={{
                  fontSize: 12, padding: "4px 14px", borderRadius: 8, cursor: "pointer",
                  border: "1px solid rgba(36,52,79,.9)", background: "rgba(27,42,71,.8)", color: "inherit",
                }}
              >
                {running ? (zh ? "执行中…" : "Running…") : (zh ? "执行" : "Run")}
              </button>
              <button
                type="button"
                onClick={() => setSelected(null)}
                style={{ fontSize: 12, padding: "4px 10px", borderRadius: 8, cursor: "pointer", border: "none", background: "transparent", color: "inherit", opacity: 0.7 }}
              >
                {zh ? "取消" : "Cancel"}
              </button>
            </div>
          )}
          {error ? <div style={{ marginTop: 8, fontSize: 12, color: "#e66f75" }}>⚠ {error}</div> : null}
        </div>
      )}
    </div>
  );
}
