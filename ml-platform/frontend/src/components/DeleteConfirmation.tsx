import type { ReactElement } from "react";
import { DeleteOutlined } from "@ant-design/icons";
import { Popconfirm } from "antd";

import { useI18n } from "../i18n";
import TableRowAction from "./TableRowAction";

interface DeleteConfirmationProps {
  label: string;
  targetName?: string;
  selectedCount?: number;
  onConfirm: () => void | Promise<void>;
  disabled?: boolean;
  loading?: boolean;
  children?: ReactElement;
}

export default function DeleteConfirmation({
  label,
  targetName,
  selectedCount,
  onConfirm,
  disabled = false,
  loading = false,
  children,
}: DeleteConfirmationProps) {
  const i18n = useI18n();
  const t = i18n.t as typeof i18n.t & { common?: Record<string, string> };
  const common = t.common || {};
  const currentLanguage = i18n.lang || (i18n as typeof i18n & { language?: string }).language;
  const isEnglish = currentLanguage === "en" || common.delete === "Delete" || common.error === "Error";
  const confirmTitle = common.confirm_delete_title || (isEnglish ? "Confirm deletion?" : "确认删除？");
  const targetPrompt = common.delete_target_prompt || (isEnglish ? 'Delete "{name}"?' : "确定删除“{name}”吗？");
  const selectedPrompt = common.delete_selected_prompt || (isEnglish ? "Delete the selected {count} items?" : "确定删除选中的 {count} 项吗？");
  const irreversible = common.delete_irreversible || (isEnglish ? "This action cannot be undone." : "删除后无法恢复。");
  const prompt = selectedCount !== undefined
    ? selectedPrompt.replace("{count}", String(selectedCount))
    : targetPrompt.replace("{name}", targetName || label);

  return (
    <Popconfirm
      placement="topRight"
      rootClassName="delete-confirmation__overlay"
      title={confirmTitle}
      description={`${prompt}${irreversible}`}
      okText={common.delete || (isEnglish ? "Delete" : "删除")}
      cancelText={common.cancel || (isEnglish ? "Cancel" : "取消")}
      okButtonProps={{ danger: true, loading }}
      disabled={disabled || loading}
      onConfirm={onConfirm}
    >
      <span className="delete-confirmation__trigger">
        {children || (
          <TableRowAction
            label={label}
            icon={<DeleteOutlined />}
            danger
            disabled={disabled}
            loading={loading}
          />
        )}
      </span>
    </Popconfirm>
  );
}
