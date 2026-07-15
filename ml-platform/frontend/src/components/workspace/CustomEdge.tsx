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
          stroke: hovered ? "#ff4d4f" : (style.stroke || "#b1b1b7"),
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
            onClick={(e) => { e.stopPropagation(); removeEdge(id); }}
            style={{
              background: "#ff4d4f",
              borderRadius: "50%",
              width: 22,
              height: 22,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 2px 6px rgba(255,77,79,0.5)",
              cursor: "pointer",
            }}
            title="\u5220\u9664\u8fde\u7ebf"
          >
            <CloseOutlined style={{ color: "#fff", fontSize: 12, fontWeight: "bold" }} />
          </div>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}