import { useEffect, useState } from "react";
import { Input, Modal, Typography } from "antd";
import { WarningFilled } from "@ant-design/icons";

const { Text } = Typography;

interface TypeToDeleteModalProps {
  open: boolean;
  /** 必须逐字输入的名称（批量删除时可传固定短语，如"确认删除"） */
  targetName: string;
  /** 弹窗标题，默认"确认删除" */
  title?: string;
  /** 警告正文（说明删除会连带删除哪些数据） */
  description: React.ReactNode;
  /** 输入框上方的提示，默认要求输入目标名称 */
  prompt?: string;
  confirmLabel?: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function TypeToDeleteModal({
  open,
  targetName,
  title = "确认删除",
  description,
  prompt,
  confirmLabel = "确认删除",
  loading = false,
  onCancel,
  onConfirm,
}: TypeToDeleteModalProps) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue("");
  }, [open]);

  const matched = value.trim() === targetName;

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onCancel}
      onOk={() => onConfirm()}
      okText={confirmLabel}
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !matched }}
      confirmLoading={loading}
      maskClosable={false}
      width={520}
    >
      <p style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
        <WarningFilled style={{ color: "#faad14", fontSize: 20 }} />
        <Text strong type="danger">此操作不可撤销！</Text>
      </p>
      <div style={{ marginBottom: 16 }}>{description}</div>
      <Text type="secondary">{prompt ?? `请输入「${targetName}」以确认：`}</Text>
      <Input
        style={{ marginTop: 8 }}
        value={value}
        placeholder={targetName}
        onChange={(event) => setValue(event.target.value)}
        onPressEnter={() => {
          if (matched && !loading) onConfirm();
        }}
      />
    </Modal>
  );
}
