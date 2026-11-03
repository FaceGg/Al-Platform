import { Empty, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { ReactNode } from "react";
import type { QualityRun } from "../../api/spotWeldQuality";

/**
 * 历史任务（spot-weld 质量运行）服务端分页表（P3 拆分首刀，
 * 自 DataAnnotationPage 原位抽出，渲染结构不变）。
 *
 * 分页状态由页面持有（列表 effect 依赖 runsPage/runsPageSize 发请求），
 * 本组件只负责呈现与回传翻页意图。
 */
export interface LegacyRunsTableProps {
  sectionTitle: ReactNode;
  emptyText: ReactNode;
  runs: QualityRun[];
  loading: boolean;
  columns: ColumnsType<QualityRun>;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number, pageSize: number) => void;
}

export default function LegacyRunsTable({
  sectionTitle,
  emptyText,
  runs,
  loading,
  columns,
  page,
  pageSize,
  total,
  onPageChange,
}: LegacyRunsTableProps) {
  return (
    <div className="data-annotation__legacy-tasks">
      <div className="data-annotation__section-head">
        <h3>{sectionTitle}</h3>
      </div>
      <Table<QualityRun>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={runs}
        columns={columns}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: onPageChange,
          showSizeChanger: true,
        }}
        scroll={{ x: 820 }}
        locale={{ emptyText: <Empty description={emptyText} /> }}
      />
    </div>
  );
}
