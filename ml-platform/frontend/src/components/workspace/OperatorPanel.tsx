import { useState } from "react";
import { Collapse, Input, Tag, Tooltip } from "antd";
import {
  AppstoreOutlined, ApartmentOutlined, BarChartOutlined, DatabaseOutlined,
  ExperimentOutlined, FilterOutlined, FundOutlined, ThunderboltOutlined, ToolOutlined,
} from "@ant-design/icons";
import { useWorkflowStore } from "../../stores/workflowStore";
import { useI18n } from "../../i18n";

const CATEGORY_LABELS: Record<string, { zh: string; en: string }> = {
  data_io: { zh: "数据输入输出", en: "Data I/O" },
  io: { zh: "数据输入输出", en: "Data I/O" },
  processing: { zh: "数据处理", en: "Processing" },
  blending: { zh: "数据融合", en: "Data Blending" },
  ml: { zh: "传统机器学习", en: "ML" },
  dl: { zh: "深度学习", en: "Deep Learning" },
  evaluation: { zh: "模型评估", en: "Evaluation" },
  visualization: { zh: "可视化", en: "Visualization" },
  control: { zh: "流程控制", en: "Control Flow" },
  mechanism: { zh: "机理模型", en: "Mechanism" },
  optimization: { zh: "参数优化", en: "Optimization" },
  utility: { zh: "工具", en: "Utilities" },
};

const CAT_ORDER = ["data_io", "io", "processing", "blending", "ml", "dl", "evaluation", "visualization", "control", "mechanism", "optimization", "utility"];

const CATEGORY_ICONS: Record<string, typeof AppstoreOutlined> = {
  data_io: DatabaseOutlined,
  io: DatabaseOutlined,
  processing: FilterOutlined,
  blending: ApartmentOutlined,
  ml: ExperimentOutlined,
  dl: ThunderboltOutlined,
  evaluation: BarChartOutlined,
  visualization: FundOutlined,
  control: ApartmentOutlined,
  mechanism: ToolOutlined,
  optimization: ExperimentOutlined,
  utility: AppstoreOutlined,
};

export default function OperatorPanel() {
  const { operators } = useWorkflowStore();
  const { t, lang } = useI18n();
  const [search, setSearch] = useState("");

  const getOpName = (op: any) => {
    const key = op.id as string;
    return (t as any).operator?.[key] || op.name || op.id;
  };

  const getCategoryLabel = (category: string) => {
    const cfg = CATEGORY_LABELS[category];
    if (!cfg) return category;
    return lang === "zh" ? cfg.zh : cfg.en;
  };

  const filtered = operators.filter((op: any) => {
    const name = getOpName(op);
    const query = search.toLowerCase();
    return name.toLowerCase().includes(query) || op.name?.toLowerCase().includes(query) || op.id.toLowerCase().includes(query);
  });

  const categories = [...new Set(filtered.map((op: any) => op.category))]
    .sort((a, b) => {
      const ai = CAT_ORDER.indexOf(a);
      const bi = CAT_ORDER.indexOf(b);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });

  const onDragStart = (event: React.DragEvent, operator: any) => {
    event.dataTransfer.setData("application/reactflow", JSON.stringify(operator));
    event.dataTransfer.effectAllowed = "move";
  };

  const items = categories.map((category) => {
    const categoryOperators = filtered.filter((operator: any) => operator.category === category);
    const CategoryIcon = CATEGORY_ICONS[category] || AppstoreOutlined;

    return {
      key: category as string,
      label: (
        <span className="operator-palette__category-heading">
          <span className="operator-palette__category-icon"><CategoryIcon /></span>
          <span className="operator-palette__category-name">{getCategoryLabel(category)}</span>
          <Tag className="operator-palette__category-count">{categoryOperators.length}</Tag>
        </span>
      ),
      children: (
        <div className="operator-palette__list">
          {categoryOperators.map((operator: any) => (
            <Tooltip key={operator.id} title={operator.description || operator.name} placement="right">
              <div
                className="operator-palette__item"
                data-testid={`operator-palette-item-${operator.id}`}
                draggable
                onDragStart={(event) => onDragStart(event, operator)}
              >
                <span className="operator-palette__item-icon"><CategoryIcon /></span>
                <span className="operator-palette__item-copy">
                  <span className="operator-palette__item-name">{getOpName(operator)}</span>
                  <span className="operator-palette__item-id">{operator.id}</span>
                </span>
              </div>
            </Tooltip>
          ))}
        </div>
      ),
    };
  });

  return (
    <aside className="operator-palette" data-testid="operator-palette">
      <div className="operator-palette__search">
        <Input.Search
          className="operator-palette__search-input"
          placeholder={t.workspace?.search_operator || "搜索算子..."}
          onChange={(event) => setSearch(event.target.value)}
          allowClear
        />
      </div>
      <Collapse className="operator-palette__groups" items={items} size="small" />
    </aside>
  );
}