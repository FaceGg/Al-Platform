import { useEffect, useState } from "react";
import { Modal, Switch } from "antd";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

interface WhitelistItem {
  tool: string;
  label: string;
  kind: "read" | "write" | "insight";
  enabled: boolean;
}

/**
 * 白名单工具管理弹窗（AI对话「+」菜单入口）：全局启停配置。
 * 停用对所有用户生效（执行层同源拒绝）；仅管理员可保存。工具的
 * 对话内调用走自然语言编排（/chat tool_call），不再手填参数。
 */
export default function ChatToolsModal({
  open, onClose,
}: { open: boolean; onClose: () => void }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [tools, setTools] = useState<WhitelistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setForbidden(false);
    apiClient.get("/chat-tools/config")
      .then((r) => setTools(r.data?.tools ?? []))
      .catch((e) => {
        setForbidden(e?.response?.status === 403);
        setTools([]);
      })
      .finally(() => setLoading(false));
  }, [open]);

  const save = async () => {
    setSaving(true);
    try {
      const disabled = tools.filter((t) => !t.enabled).map((t) => t.tool);
      await apiClient.put("/chat-tools/config", { disabled });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const kindLabel = (kind: WhitelistItem["kind"]) =>
    kind === "write" ? (zh ? "写" : "write") : kind === "insight" ? (zh ? "洞察" : "insight") : zh ? "读" : "read";

  return (
    <Modal
      title={zh ? "白名单工具配置（对全部用户生效）" : "Whitelist tools (global)"}
      open={open}
      onCancel={onClose}
      onOk={save}
      confirmLoading={saving}
      okText={zh ? "保存" : "Save"}
      cancelText={zh ? "取消" : "Cancel"}
      width={520}
    >
      <div style={{ fontSize: 12, color: "var(--v2-dim, #999)", marginBottom: 10 }}>
        {zh
          ? "停用的工具对所有用户隐藏且拒绝执行；写操作在对话中仍保留二次确认。工具可直接在对话里用自然语言调用（缺参数时助手会追问）。"
          : "Disabled tools are hidden and rejected for all users; writes keep their confirmation step. Tools can be invoked from the chat in natural language."}
      </div>
      {loading ? (
        <div style={{ fontSize: 12, color: "var(--v2-dim, #999)", padding: "12px 0" }}>
          {zh ? "加载中…" : "Loading…"}
        </div>
      ) : forbidden ? (
        <div style={{ fontSize: 12, color: "var(--v2-dim, #999)", padding: "12px 0" }}>
          {zh ? "仅管理员可配置白名单工具。" : "Admin only."}
        </div>
      ) : (
        tools.map((tool) => (
          <div key={tool.tool} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
            <Switch
              size="small"
              checked={tool.enabled}
              onChange={(checked) => setTools((prev) => prev.map((t) => (t.tool === tool.tool ? { ...t, enabled: checked } : t)))}
            />
            <span style={{ fontSize: 13, flex: 1 }}>{tool.label}</span>
            <span style={{ fontSize: 11, color: "var(--v2-dim, #999)" }}>[{kindLabel(tool.kind)}] {tool.tool}</span>
          </div>
        ))
      )}
    </Modal>
  );
}
