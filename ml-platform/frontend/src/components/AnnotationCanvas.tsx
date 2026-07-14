import { useRef, useState, useEffect, useCallback } from "react";
import { Button, Space, Select, Tag, message } from "antd";
import { apiPut } from "../api/client";

interface Annotation {
  id: string; type: string; label: string;
  x: number; y: number; w: number; h: number; points?: number[][];
}

interface Props {
  sampleId: string;
  imageUrl?: string;
  existingAnnotations?: Annotation[];
  labels?: string[];
  onSave?: () => void;
}

const COLORS = ["#ff4d4f","#1890ff","#52c41a","#faad14","#722ed1","#eb2f96"];

export default function AnnotationCanvas({ sampleId, imageUrl, existingAnnotations = [], labels = ["defect","normal"], onSave }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<"rect"|"polygon"|"point"|"select">("rect");
  const [currentLabel, setCurrentLabel] = useState(labels[0]||"default");
  const [annotations, setAnnotations] = useState<Annotation[]>(existingAnnotations);
  const [drawing, setDrawing] = useState(false);
  const [startPos, setStartPos] = useState<{x:number;y:number}|null>(null);
  const [polyPoints, setPolyPoints] = useState<number[][]>([]);
  const [image, setImage] = useState<HTMLImageElement|null>(null);
  const [saving, setSaving] = useState(false);

  // Load image
  useEffect(() => {
    if (!imageUrl) return;
    const img = new Image();
    img.onload = () => setImage(img);
    img.src = imageUrl;
  }, [imageUrl]);

  const getCanvasPos = useCallback((e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }, []);

  // Draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Draw image
    if (image) {
      const scale = Math.min(w / image.width, h / image.height);
      const iw = image.width * scale;
      const ih = image.height * scale;
      const ox = (w - iw) / 2;
      const oy = (h - ih) / 2;
      ctx.drawImage(image, ox, oy, iw, ih);
    } else {
      ctx.fillStyle = "#f0f0f0";
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = "#999";
      ctx.font = "14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("No image loaded", w/2, h/2);
    }

    // Draw annotations
    annotations.forEach((ann, i) => {
      const color = COLORS[i % COLORS.length];
      ctx.strokeStyle = color;
      ctx.fillStyle = color + "30";
      ctx.lineWidth = 2;
      if (ann.type === "rect") {
        ctx.fillRect(ann.x, ann.y, ann.w, ann.h);
        ctx.strokeRect(ann.x, ann.y, ann.w, ann.h);
        ctx.fillStyle = color;
        ctx.font = "12px sans-serif";
        ctx.fillText(`${ann.label}`, ann.x + 4, ann.y + 16);
      } else if (ann.type === "polygon" && ann.points) {
        ctx.beginPath();
        ctx.moveTo(ann.points[0][0], ann.points[0][1]);
        ann.points.slice(1).forEach(([px,py]) => ctx.lineTo(px,py));
        ctx.closePath();
        ctx.fill(); ctx.stroke();
      } else if (ann.type === "point") {
        ctx.beginPath();
        ctx.arc(ann.x, ann.y, 6, 0, Math.PI*2);
        ctx.fill(); ctx.stroke();
      }
    });

    // Draw in-progress shape
    if (drawing && startPos && tool === "rect") {
      const pos = getCanvasPos({ clientX: 0, clientY: 0 } as any);
      ctx.strokeStyle = "#ff4d4f";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 5]);
      // Preview uses last mouse position from state
    }
  }, [annotations, image, drawing, tool]);

  const handleMouseDown = (e: React.MouseEvent) => {
    const pos = getCanvasPos(e);
    if (tool === "point") {
      setAnnotations(prev => [...prev, { id: crypto.randomUUID(), type: "point", label: currentLabel, x: pos.x, y: pos.y, w: 0, h: 0 }]);
    } else if (tool === "rect") {
      setDrawing(true);
      setStartPos(pos);
    } else if (tool === "polygon") {
      setPolyPoints(prev => [...prev, [pos.x, pos.y]]);
    }
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (!drawing || !startPos || tool !== "rect") return;
    const pos = getCanvasPos(e);
    const x = Math.min(startPos.x, pos.x);
    const y = Math.min(startPos.y, pos.y);
    const w = Math.abs(pos.x - startPos.x);
    const h = Math.abs(pos.y - startPos.y);
    if (w > 5 && h > 5) {
      setAnnotations(prev => [...prev, { id: crypto.randomUUID(), type: "rect", label: currentLabel, x, y, w, h }]);
    }
    setDrawing(false);
    setStartPos(null);
  };

  const finishPolygon = () => {
    if (polyPoints.length < 3) {
      message.warning("Need at least 3 points for polygon");
      return;
    }
    setAnnotations(prev => [...prev, { id: crypto.randomUUID(), type: "polygon", label: currentLabel, x: 0, y: 0, w: 0, h: 0, points: polyPoints }]);
    setPolyPoints([]);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiPut("/annotations/samples/" + sampleId, {
        annotations: annotations.map(a => ({ type: a.type, label: a.label, x: a.x, y: a.y, w: a.w, h: a.h, points: a.points })),
        status: "labeled",
      });
      message.success("Saved");
      onSave?.();
    } catch {
      message.error("Save failed");
    } finally { setSaving(false); }
  };

  const clearAnnotations = () => { setAnnotations([]); setPolyPoints([]); };

  return (
    <div ref={containerRef} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Space wrap>
        <Select value={tool} onChange={setTool} style={{ width: 100 }}
          options={[{value:"rect",label:"Rectangle"},{value:"polygon",label:"Polygon"},{value:"point",label:"Point"}]} />
        <Select value={currentLabel} onChange={setCurrentLabel} style={{ width: 120 }}
          options={labels.map(l => ({value:l, label:l}))} />
        <Tag color="blue">{annotations.length} annotations</Tag>
        {tool === "polygon" && polyPoints.length > 0 && (
          <Button size="small" onClick={finishPolygon}>Finish Polygon ({polyPoints.length} pts)</Button>
        )}
        <Button size="small" danger onClick={clearAnnotations}>Clear All</Button>
        <Button size="small" type="primary" loading={saving} onClick={handleSave}>Save</Button>
      </Space>
      <canvas
        ref={canvasRef}
        width={800} height={500}
        style={{ border: "1px solid #d9d9d9", borderRadius: 4, cursor: "crosshair", background: "#fafafa" }}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
      />
    </div>
  );
}
