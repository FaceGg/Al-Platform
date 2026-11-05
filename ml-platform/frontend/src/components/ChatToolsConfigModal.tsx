import { useEffect, useState } from "react";
import { Modal, Switch, Tag } from "antd";
import { SafetyOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

interface ToolItem {
  tool: string;
  label: string;
  kind: "read" | "write" | "insight";
  enabled: boolean;
}

const KIND_LABEL: Record<ToolItem["kind"], { zh: string; en: string }> = {
  read: { zh: "读", en: "read" },
  write: { zh: "写", en: "write" },
  insight: { zh: "洞察", en: "insight" },
};

/**
 * 白名单工具管理弹窗（+ 菜单入口，替代输入框上方的工具面板）：
 * - 管理员：启停 Switch 对全部用户全局生效（保存写 platform_options）；
 * - 所有用户：启用的工具可在弹窗内手动执行（写操作保留确认卡），
 *   结果以助手消息插入对话。
 */
export default function ChatToolsConfigModal({
  open, onClose, onSaved, onResult,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
  onResult?: (text: string) => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const isAdmin = localStorage.getItem("role") === "admin";
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [saving, setSaving] = useState(false);
  // 手动执行（原 ChatToolsPanel 流程整体迁移）
  const [selected, setSelected] = useState<ToolItem | null>(null);
  const [paramsText, setParamsText] = useState("{}");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setSelected(null);
    setError("");
    if (isAdmin) {
      apiClient.get("/chat-tools/config").then((r) => setTools(r.data?.tools ?? [])).catch(() => {});
    } else {
      // 普通用户只读：拉启用白名单拼成同形列表
      apiClient.get("/chat-tools/whitelist").then((r) => {
        const data = r.data || {};
        setTools([
          ...(data.insight_tools ?? []),
          ...(data.read_tools ?? []),
          ...(data.write_tools ?? []),
        ]);
      }).catch(() => {});
    }
  }, [open, isAdmin]);

  const pick = (item: ToolItem) => {
    setSelected(item);
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
        setSelected({ ...selected, needsConfirm: true, message: data.message } as ToolItem & { needsConfirm?: boolean; message?: string });
      } else if (data.status === "success") {
        onResult?.(`[${selected.tool}] ${JSON.stringify(data.result, null, 2)}`);
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

  const save = async () => {
    setSaving(true);
    try {
      const disabled = tools.filter((t) => !t.enabled).map((t) => t.tool);
      await apiClient.put("/chat-tools/config", { disabled });
      onClose();
      onSaved?.();
    } finally {
      setSaving(false);
    }
  };

  const selectedExtra = selected as (ToolItem & { needsConfirm?: boolean; message?: string }) | null;

  return (
    <Modal
      title={zh ? "白名单工具管理" : "Chat tools"}
      open={open}
      onCancel={onClose}
      footer={isAdmin ? undefined : null}
      onOk={save}
      confirmLoading={saving}
      okText={zh ? "保存" : "Save"}
      cancelText={zh ? "取消" : "Cancel"}
      width={520}
    >
      <div style={{ fontSize: 12, color: "var(--v2-dim, #999)", marginBottom: 10 }}>
        {isAdmin
          ? zh ? "停用的工具对所有用户隐藏且拒绝执行；写操作始终保留用户确认。" : "Disabled tools are hidden and rejected for all users."
          : zh ? "以下工具可在此执行（写操作需确认），结果将插入对话；启用范围由管理员统一配置。" : "Run enabled tools here (writes need confirmation); managed by the admin."}
      </div>
      {tools.map((tool) => (
        <div key={tool.tool} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
          {isAdmin ? (
            <Switch
              size="small"
              checked={tool.enabled}
              onChange={(checked) => setTools((prev) => prev.map((t) => (t.tool === tool.tool ? { ...t, enabled: checked } : t)))}
            />
          ) : null}
          <span style={{ fontSize: 13, flex: selected && selectedExtra?.tool === tool.tool ? "0 0 auto" : 1 }}>{tool.label}</span>
          <Tag style={{ marginRight: 0 }}>{zh ? KIND_LABEL[tool.kind].zh : KIND_LABEL[tool.kind].en}</Tag>
          {!isAdmin || tool.enabled ? (
            <button
              type="button"
              onClick={() => pick(tool)}
              style={{
                fontSize: 11.5, padding: "2px 9px", borderRadius: 9, cursor: "pointer",
                border: "1px solid rgba(36,52,79,.9)", background: "transparent", color: "inherit", opacity: 0.85,
              }}
            >
              {zh ? "执行" : "Run"}
            </button>
          ) : null}
        </div>
      ))}
      {selectedExtra && (
        <div style={{
          marginTop: 10, border: "1px solid rgba(92,178,255,.35)", borderRadius: 10,
          background: "rgba(47,155,245,.06)", padding: "10px 12px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>
              {selectedExtra.kind === "write" ? (zh ? "写操作——需要确认后执行" : "write — requires confirmation") : zh ? "只读操作" : "read-only"}
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
          {selectedExtra.needsConfirm ? (
            <div style={{
              display: "flex", alignItems: "center", gap: 10, marginTop: 8,
              border: "1px solid rgba(255,209,102,.4)", background: "rgba(255,209,102,.08)",
              borderRadius: 8, padding: "7px 10px", flexWrap: "wrap",
            }}>
              <SafetyOutlined style={{ color: "#ffd166" }} />
              <span style={{ fontSize: 12 }}>{selectedExtra.message}</span>
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
    </Modal>
  );
}
