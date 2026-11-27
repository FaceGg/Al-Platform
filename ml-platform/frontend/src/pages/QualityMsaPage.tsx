import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import { createMsaStudy, listMsaStudies } from "../api/qms";
import type { QmsMsaStudy } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / MSA 测量系统分析（B3-01）：均值极差法 %GRR / ndc /
 * 分级（<10% acceptable、10–30% conditional、>30% unacceptable；AIAG 通行口径
 * 待质量专家评审）。 */

const GRADE_COLOR: Record<string, string> = {
  acceptable: "green", conditional: "orange", unacceptable: "red",
};

export default function QualityMsaPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsMsaStudy[]>([]);
  const [detail, setDetail] = useState<QmsMsaStudy | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{
    name: string; part_count: number; operator_count: number;
    replicates: number; tolerance: number;
  }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listMsaStudies(projectId).then(setRows).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, message]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: zh ? "名称" : "Name", dataIndex: "name", key: "name" },
    { title: zh ? "零件×操作者×重复" : "P×O×R", key: "shape", width: 140,
      render: (_: unknown, row: QmsMsaStudy) => `${row.part_count}×${row.operator_count}×${row.replicates}` },
    {
      title: "%GRR", dataIndex: "grr_percent", key: "grr", width: 100,
      render: (value: number | null) => (value === null ? "-" : `${value}%`),
    },
    { title: "ndc", dataIndex: "ndc", key: "ndc", width: 80 },
    {
      title: zh ? "分级" : "Grade", dataIndex: "grade", key: "grade", width: 130,
      render: (value: string | null) => (value ? <Tag color={GRADE_COLOR[value]}>{value}</Tag> : "-"),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_msa" testId="v2-quality-msa">
        <PageHeading
          section="quality"
          navKey="quality_msa"
          desc={zh
            ? "测量系统分析：录入 零件×操作者×重复次数 读数矩阵，服务端按均值极差法计算 %GRR、ndc 并分级；%GRR<10% 可接受、10–30% 有条件接受、>30% 不可接受。"
            : "MSA: average-and-range %GRR / ndc with AIAG grading."}
          actions={
            <Space>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((item) => ({ value: item.id, label: item.name }))}
              />
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-msa"
                onClick={() => { form.resetFields(); setCreateOpen(true); }}>
                {zh ? "新研究" : "New study"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            onRow={(row) => ({ onClick: () => setDetail(row) })}
            locale={{ emptyText: zh ? "暂无 MSA 研究：点击「新研究」录入读数矩阵" : "No MSA studies yet" }}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            {zh ? "均值极差法（AIAG 通行口径）；与 Minitab 的逐项复核为质量专家评审项（持续登记）。" : "AIAG average-and-range method; Minitab cross-check pending expert review."}
          </Typography.Paragraph>
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "新 MSA 研究" : "New MSA study"}
          okText={zh ? "计算并保存" : "Compute"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="msa-form"
            onFinish={(values) => {
              setBusy(true);
              // 读数矩阵按 零件×操作者×重复 生成递增读数（最小骨架：录入辅助由详情页后续完善）
              const parts = values.part_count;
              const operators = values.operator_count;
              const reps = values.replicates;
              const base = 10;
              const readings = Array.from({ length: operators }, (_, o) =>
                Array.from({ length: parts }, (_, p) =>
                  Array.from({ length: reps }, (_, r) => base + p * 10 + o * 0.05 + r * 0.02)));
              createMsaStudy(projectId!, {
                name: values.name.trim(), part_count: parts, operator_count: operators,
                replicates: reps, tolerance: values.tolerance, data: { readings },
              }).then((result) => {
                message.info(zh ? `已保存：%GRR ${result.grr_percent}% · ${result.grade}` : `Saved: %GRR ${result.grr_percent}% · ${result.grade}`);
                setCreateOpen(false);
                load();
              }).catch((e) => message.error(apiErrorText(e)))
                .finally(() => setBusy(false));
            }}>
            <Form.Item name="name" label={zh ? "名称" : "Name"} rules={[{ required: true }]}>
              <Input maxLength={128} />
            </Form.Item>
            <Space size="large">
              <Form.Item name="part_count" label={zh ? "零件数" : "Parts"} rules={[{ required: true }]}>
                <InputNumber min={1} max={20} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="operator_count" label={zh ? "操作者数" : "Operators"} rules={[{ required: true }]}>
                <InputNumber min={1} max={10} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="replicates" label={zh ? "重复次数" : "Replicates"} rules={[{ required: true }]}>
                <InputNumber min={2} max={10} style={{ width: 120 }} />
              </Form.Item>
            </Space>
            <Form.Item name="tolerance" label={zh ? "公差 TV（总公差带宽度）" : "Tolerance TV"} rules={[{ required: true }]}>
              <InputNumber min={0} style={{ width: 200 }} />
            </Form.Item>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              {zh
                ? "最小骨架：服务端以均匀递增读数矩阵演示计算口径；真实读数批量导入随专家评审后的录入格式同批落地（not_run 如实登记）。"
                : "Skeleton input; real reading import lands with the expert-reviewed format."}
            </Typography.Paragraph>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail?.name ?? ""} width={560}>
          {detail && (
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="%GRR">{detail.grr_percent ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="ndc">{detail.ndc ?? "-"}</Descriptions.Item>
              <Descriptions.Item label={zh ? "分级" : "Grade"}>{detail.grade ?? "-"}</Descriptions.Item>
              <Descriptions.Item label={zh ? "形态" : "Shape"}>{`${detail.part_count}×${detail.operator_count}×${detail.replicates}`}</Descriptions.Item>
            </Descriptions>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
