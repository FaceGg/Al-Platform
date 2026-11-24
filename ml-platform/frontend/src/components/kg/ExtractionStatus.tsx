import { Button, Progress, Space, Spin, Tag, Tooltip, Typography } from "antd";
import {
  CheckCircleOutlined, CloseCircleOutlined, RobotOutlined, StopOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import { useI18n } from "../../i18n";
import type { KgExtractionApi } from "./useKgExtraction";

const { Text } = Typography;

/**
 * 抽取状态行：当前图谱由哪种抽取生成、规模多大、深度抽取进行到哪。
 *
 * 快速抽取与深度抽取不并存、以最后一次抽取为主：两者至多一个标「当前图谱」，
 * 另一个显示「未抽取」。「实体 N · 关系 M」是库内图谱规模，与画布标题栏
 * 同口径；任务进行中用任务行计数（每片落地同步更新），结束后用摘要里的规模。
 */
export default function ExtractionStatus({ extraction }: { extraction: KgExtractionApi }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { kbId, summary, job, running, waitingCancel, rulesLoading } = extraction;
  if (!kbId) return null;

  const current = summary?.current ?? null;
  const scale = summary?.graph;
  // 深度抽取任务一启动就在重建图谱：进行中不让快速抽取继续标「当前图谱」
  const deepActive = running || waitingCancel;
  const pending = summary?.llm.pending_chunks ?? 0;
  // 没抽完的分片可以续抽；分片都抽过了但上次任务没成功结束（收尾的归并/同步
  // 失败、最后一刻取消）也可以重试——重试只重做收尾，不调用大模型
  const canResume = pending > 0 || job?.status === "failed" || job?.status === "cancelled";
  // 成本护栏：单个任务最多处理 maxChunks 片，待抽分片更多时每次续抽推进一批
  const maxChunks = Math.max(1, (summary?.llm.max_chunks_per_job ?? pending) || 1);
  const resumeLabel = job?.status === "succeeded"
    ? (pending > maxChunks
      ? (zh ? `补抽 ${maxChunks} 片（共 ${pending} 片未完成）`
        : `Extract ${maxChunks} of ${pending} pending chunk(s)`)
      : (zh ? `补抽 ${pending} 片未完成` : `Extract ${pending} pending chunk(s)`))
    : pending > 0
      ? (zh ? "继续抽取" : "Resume")
      : (zh ? "重试" : "Retry");
  // 千分位与画布标题栏一致
  const n = (value: number) => value.toLocaleString();

  const mixedTag = (
    <Tooltip
      title={zh
        ? "库内同时有快速抽取和深度抽取的结果。重新抽取任意一种后，只保留最后一次抽取的结果"
        : "This KB holds both quick- and deep-extracted results. Run either extraction again to keep only the latest"}
    >
      <Tag style={{ marginInlineEnd: 0 }} data-testid="kg-mixed">{zh ? "快速+深度混杂" : "Quick + deep mixed"}</Tag>
    </Tooltip>
  );
  const notExtracted = <Tag style={{ marginInlineEnd: 0 }}>{zh ? "未抽取" : "Not extracted"}</Tag>;

  let rulesStatus;
  if (!summary && !job) {
    rulesStatus = <Spin size="small" />;
  } else if (rulesLoading) {
    rulesStatus = <Spin size="small" />;
  } else if (current === "mixed") {
    rulesStatus = mixedTag;
  } else if (current === "rules" && !deepActive) {
    rulesStatus = (
      <Tag color="blue" style={{ marginInlineEnd: 0 }} data-testid="kg-quick-current">
        {zh
          ? `当前图谱 · 实体 ${n(scale?.entities ?? 0)} · 关系 ${n(scale?.relations ?? 0)}`
          : `Current graph · ${n(scale?.entities ?? 0)}E/${n(scale?.relations ?? 0)}R`}
      </Tag>
    );
  } else {
    rulesStatus = notExtracted;
  }

  let deepStatus;
  if (!summary && !job) {
    deepStatus = <Spin size="small" />;
  } else if (deepActive) {
    deepStatus = (
      <Space size={8} data-testid="kg-deep-progress">
        <Progress
          percent={job?.progress ?? 0}
          size="small"
          status={waitingCancel ? "normal" : "active"}
          style={{ width: 320, margin: 0 }}
          format={() =>
            zh
              ? `${job?.done_units ?? 0}/${job?.total_units ?? 0} 片 · 实体 ${n(job?.entities_found ?? 0)} · 关系 ${n(job?.relations_found ?? 0)}`
              : `${job?.done_units ?? 0}/${job?.total_units ?? 0} · ${n(job?.entities_found ?? 0)}E/${n(job?.relations_found ?? 0)}R`
          }
        />
        {running ? (
          <Button size="small" danger icon={<StopOutlined />} onClick={extraction.cancel}>
            {zh ? "取消" : "Cancel"}
          </Button>
        ) : (
          <Button size="small" danger disabled icon={<StopOutlined />}>
            {zh ? "取消中…" : "Cancelling…"}
          </Button>
        )}
      </Space>
    );
  } else if (current === "mixed") {
    deepStatus = mixedTag;
  } else if (current === "llm") {
    const entities = scale?.entities ?? job?.entities_found ?? 0;
    const relations = scale?.relations ?? job?.relations_found ?? 0;
    const resumeLink = canResume && (
      <Button
        type="link"
        size="small"
        onClick={() => extraction.startDeep(false)}
        data-testid="kg-deep-resume"
      >
        {resumeLabel}
      </Button>
    );
    if (!job || job.status === "succeeded") {
      deepStatus = (
        <Space size={4}>
          <Tag
            color="success"
            icon={<CheckCircleOutlined />}
            style={{ marginInlineEnd: 0 }}
            data-testid="kg-deep-current"
          >
            {zh
              ? `当前图谱 · 实体 ${n(entities)} · 关系 ${n(relations)}`
              : `Current graph · ${n(entities)}E/${n(relations)}R`}
          </Tag>
          {resumeLink}
        </Space>
      );
    } else if (job.status === "failed") {
      deepStatus = (
        <Space size={4}>
          <Tooltip title={job.error || undefined}>
            <Tag
              color="error"
              icon={<CloseCircleOutlined />}
              style={{ marginInlineEnd: 0 }}
              data-testid="kg-deep-incomplete"
            >
              {zh ? "未完成" : "Not finished"}
              {entities > 0 ? (zh ? ` · 已抽出实体 ${n(entities)}` : ` · ${n(entities)}E`) : ""}
            </Tag>
          </Tooltip>
          {resumeLink}
        </Space>
      );
    } else {
      deepStatus = (
        <Space size={4}>
          <Tag style={{ marginInlineEnd: 0 }}>
            {zh ? "已取消" : "Cancelled"}
            {entities > 0 ? (zh ? ` · 已抽出实体 ${n(entities)}` : ` · ${n(entities)}E`) : ""}
          </Tag>
          {resumeLink}
        </Space>
      );
    }
  } else {
    deepStatus = notExtracted;
  }

  return (
    <div
      data-testid="kg-extraction-status"
      style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "6px 24px" }}
    >
      <Space size={6}>
        <ThunderboltOutlined style={{ color: current === "rules" ? "#1677ff" : undefined }} />
        <Text type="secondary" style={{ fontSize: 13 }}>{zh ? "快速抽取" : "Quick extract"}</Text>
        {rulesStatus}
      </Space>
      <Space size={6}>
        <RobotOutlined style={{ color: current === "llm" ? "#52c41a" : undefined }} />
        <Text type="secondary" style={{ fontSize: 13 }}>{zh ? "深度抽取" : "Deep extract"}</Text>
        {deepStatus}
      </Space>
    </div>
  );
}
