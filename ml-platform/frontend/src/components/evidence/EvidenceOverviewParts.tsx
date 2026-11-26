import { Button, List, Space, Tag, Typography } from "antd";
import {
  STAGE_STATUS_COLOR, STAGE_STATUS_LABELS, evidenceRefPath,
} from "../../api/evidenceChain";
import type { EvidenceStage, LaunchCheck } from "../../api/evidenceChain";

/** 闭环证据总览的纯展示部分（F2b，E21）：12 环节清单与上线检查清单。 */

type Lang = "zh" | "en";

export function StageList({
  stages, lang, onOpenRef,
}: {
  stages: EvidenceStage[];
  lang: Lang;
  onOpenRef: (path: string) => void;
}) {
  const zh = lang === "zh";
  return (
    <List
      size="small"
      dataSource={stages}
      data-testid="evidence-stages"
      locale={{ emptyText: zh ? "暂无环节数据" : "No stages" }}
      renderItem={(stage, index) => {
        // 有对应页面的依据才给下钻入口；其余只展示引用，不做死链
        const links = stage.evidence
          .map((ref) => ({ ref, path: evidenceRefPath(ref) }))
          .filter((item): item is { ref: EvidenceStage["evidence"][number]; path: string } => Boolean(item.path));
        return (
          <List.Item
            key={stage.key}
            actions={links.map(({ ref, path }) => (
              <Button
                key={`${ref.ref_type}-${ref.ref_id}`}
                type="link"
                size="small"
                onClick={() => onOpenRef(path)}
              >
                {zh ? `打开 ${ref.label}` : `Open ${ref.label}`}
              </Button>
            ))}
          >
            <Space direction="vertical" size={0} style={{ width: "100%" }}>
              <Space wrap>
                <Typography.Text type="secondary">{index + 1}.</Typography.Text>
                <Typography.Text strong>{zh ? stage.title : stage.title_en}</Typography.Text>
                <Tag color={STAGE_STATUS_COLOR[stage.status]} data-testid={`stage-status-${stage.key}`}>
                  {STAGE_STATUS_LABELS[lang][stage.status]}
                </Tag>
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{stage.note}</Typography.Text>
              {stage.evidence.length > 0 && (
                <Typography.Text type="secondary" style={{ fontSize: 12, wordBreak: "break-all" }}>
                  {stage.evidence.map((ref) => `${ref.label} · ${ref.ref_type} ${ref.ref_id}`).join("；")}
                </Typography.Text>
              )}
            </Space>
          </List.Item>
        );
      }}
    />
  );
}

export function CheckList({ checks, lang }: { checks: LaunchCheck[]; lang: Lang }) {
  const zh = lang === "zh";
  return (
    <List
      size="small"
      dataSource={checks}
      data-testid="evidence-checks"
      renderItem={(check) => (
        <List.Item key={check.key}>
          <Space direction="vertical" size={0} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={check.status === "pass" ? "green" : "red"} data-testid={`check-status-${check.key}`}>
                {check.status === "pass" ? (zh ? "通过" : "Pass") : (zh ? "未通过" : "Fail")}
              </Tag>
              <Typography.Text strong>{zh ? check.title : check.title_en}</Typography.Text>
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{check.detail}</Typography.Text>
          </Space>
        </List.Item>
      )}
    />
  );
}
