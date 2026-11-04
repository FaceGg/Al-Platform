import { useEffect, useMemo, useState } from "react";
import { Modal, Switch } from "antd";
import { ToolOutlined, SafetyOutlined, SettingOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

interface WhitelistItem {
  tool: string;
  label: string;
  kind: "read" | "write" | "insight";
  enabled: boolean;
}

interface WhitelistResponse {
  read_tools?: WhitelistItem[];
  insight_tools?: WhitelistItem[];
  write_tools?: WhitelistItem[];
}

interface PendingInvocation {
  tool: string;
  label: string;
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

  const load = () => {
    apiClient.get("/chat-tools/whitelist").then((r) => setWhitelist(r.data || {})).catch(() => setWhitelist({}));
  };

  useEffect(load, []);

  const entries = useMemo(() => {
    const list: WhitelistItem[] = [];
    (whitelist.insight_tools || []).forEach((item) => list.push(item));
    (whitelist.read_tools || []).forEach((item) => list.push(item));
    (whitelist.write_tools || []).forEach((item) => list.push(item));
    return list.filter((item) => item.enabled);
  }, [whitelist]);

  const kindLabel = (kind: PendingInvocation["kind"]) =>
    kind === "write" ? (zh ? "写" : "write") : kind === "insight" ? (zh ? "洞察" : "insight") : zh ? "读" : "read";
  const kindClass = (kind: PendingInvocation["kind"]) =>
    kind === "write" ? "v2-bgo" : kind === "insight" ? "v2-bp" : "v2-bb";

  const pick = (item: WhitelistItem) => {
    setSelected({ tool: item.tool, label: item.label, kind: item.kind, needsConfirm: false });
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
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8, alignItems: "center" }}>
          {entries.map((item) => (
            <button
              key={item.tool}
              type="button"
              title={item.tool}
              onClick={() => pick(item)}
              style={{
                fontSize: 11.5, padding: "2px 9px", borderRadius: 9, cursor: "pointer",
                border: "1px solid rgba(36,52,79,.9)", background: "rgba(22,34,58,.6)", color: "inherit",
              }}
            >
              {item.label} <span style={{ opacity: 0.75 }}>[{kindLabel(item.kind)}]</span>
            </button>
          ))}
          <AdminToolsConfig onSaved={() => load()} />
        </div>
      )}

      {selected && (
        <div style={{
          marginTop: 10, border: "1px solid rgba(92,178,255,.35)", borderRadius: 10,
          background: "rgba(47,155,245,.06)", padding: "10px 12px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span className={`v2-badge ${kindClass(selected.kind)}`} title={selected.tool}>{selected.label}</span>
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
          {error ? <div style={{ marginTop: 8, fontSize: 12, color: "#e66f75" }}>注意：{error}</div> : null}
        </div>
      )}
    </div>
  );
}

/** 管理员工具启停配置（全局生效）：只有 admin 能看到入口。 */
function AdminToolsConfig({ onSaved }: { onSaved: () => void }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const isAdmin = localStorage.getItem("role") === "admin";
  const [open, setOpen] = useState(false);
  const [tools, setTools] = useState<WhitelistItem[]>([]);
  const [saving, setSaving] = useState(false);

  if (!isAdmin) return null;

  const openPanel = () => {
    apiClient.get("/chat-tools/config").then((r) => {
      setTools(r.data?.tools ?? []);
      setOpen(true);
    }).catch(() => {});
  };

  const save = async () => {
    setSaving(true);
    try {
      const disabled = tools.filter((t) => !t.enabled).map((t) => t.tool);
      await apiClient.put("/chat-tools/config", { disabled });
      setOpen(false);
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={openPanel}
        title={zh ? "管理员配置工具启停（全局生效）" : "Admin: toggle tools globally"}
        style={{
          fontSize: 11.5, padding: "2px 9px", borderRadius: 9, cursor: "pointer",
          border: "1px dashed rgba(36,52,79,.9)", background: "transparent", color: "inherit", opacity: 0.85,
        }}
      >
        <SettingOutlined /> {zh ? "管理" : "Admin"}
      </button>
      <Modal
        title={zh ? "白名单工具配置（对全部用户生效）" : "Chat tools (global)"}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={save}
        confirmLoading={saving}
        okText={zh ? "保存" : "Save"}
        cancelText={zh ? "取消" : "Cancel"}
      >
        <div style={{ fontSize: 12, color: "var(--v2-dim, #999)", marginBottom: 10 }}>
          {zh ? "停用的工具对所有用户隐藏且拒绝执行；写操作始终保留用户确认。" : "Disabled tools are hidden and rejected for all users."}
        </div>
        {tools.map((tool) => (
          <div key={tool.tool} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
            <Switch
              size="small"
              checked={tool.enabled}
              onChange={(checked) => setTools((prev) => prev.map((t) => (t.tool === tool.tool ? { ...t, enabled: checked } : t)))}
            />
            <span style={{ fontSize: 13 }}>{tool.label}</span>
            <span style={{ fontSize: 11, color: "var(--v2-dim, #999)" }}>{tool.tool}</span>
          </div>
        ))}
      </Modal>
    </>
  );
}
