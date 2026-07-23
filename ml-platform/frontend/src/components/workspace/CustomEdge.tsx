import { useState } from "react";
import {
  BaseEdge, EdgeProps, getBezierPath, EdgeLabelRenderer,
} from "reactflow";
import { CloseOutlined } from "@ant-design/icons";
import { useWorkflowStore } from "../../stores/workflowStore";

export default function CustomEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition, style = {}, markerEnd,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });
  const removeEdge = useWorkflowStore((s) => s.removeEdge);

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          strokeWidth: hovered ? 3 : 2,
          stroke: hovered ? "var(--accent-error)" : (style.stroke || "var(--workflow-edge)"),
          cursor: "pointer",
          transition: "stroke 0.2s, stroke-width 0.2s",
        }}
      />
      {/* Invisible wide hitbox for easier hover */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={24}
        style={{ cursor: "pointer" }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: "absolute",
            left: labelX + "px",
            top: labelY + "px",
            transform: "translate(-50%, -50%)",
            zIndex: 100,
            opacity: hovered ? 1 : 0,
            transition: "opacity 0.15s ease",
            pointerEvents: hovered ? "auto" : "none",
          }}
        >
          <div
            className="workflow-edge-delete__button"
            onClick={(e) => { e.stopPropagation(); removeEdge(id); }}
            title="\u5220\u9664\u8fde\u7ebf"
          >
            <CloseOutlined />
          </div>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}