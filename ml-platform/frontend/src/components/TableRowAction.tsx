import type { MouseEventHandler, ReactNode } from "react";
import { Button, Tooltip } from "antd";

interface TableRowActionProps {
  label: string;
  icon: ReactNode;
  onClick?: MouseEventHandler<HTMLElement>;
  danger?: boolean;
  warning?: boolean;
  disabled?: boolean;
  loading?: boolean;
}

export default function TableRowAction({
  label,
  icon,
  onClick,
  danger = false,
  warning = false,
  disabled = false,
  loading = false,
}: TableRowActionProps) {
  const className = [
    "table-row-action",
    danger ? "table-row-action--danger" : "",
    warning ? "table-row-action--warning" : "",
  ].filter(Boolean).join(" ");

  return (
    <Tooltip title={label}>
      <span className="table-row-action__tooltip-target">
        <Button
          type="text"
          size="small"
          className={className}
          danger={danger}
          icon={icon}
          aria-label={label}
          onClick={onClick}
          disabled={disabled}
          loading={loading}
        />
      </span>
    </Tooltip>
  );
}
