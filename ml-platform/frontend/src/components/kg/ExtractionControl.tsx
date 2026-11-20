import { useEffect, useRef, useState } from "react";
import { Button, Progress, Space, Tooltip, message } from "antd";
import { ThunderboltOutlined, RobotOutlined, StopOutlined } from "@ant-design/icons";
import apiClient from "../../api/client";
import { useI18n } from "../../i18n";

interface JobStatus {
  id: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  total_units: number;
  done_units: number;
  progress: number;
  entities_found: number;
  relations_found: number;
  llm_errors: number;
  error?: string | null;
}

export default function ExtractionControl({
  kbId,
  onExtracted,
}: {
  kbId: string | null;
  onExtracted: () => void;
}) {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const [rulesLoading, setRulesLoading] = useState(false);
  const [job, setJob] = useState<JobStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);
  useEffect(() => {
    // 切库时终止旧轮询
    stopPolling();
    setJob(null);
  }, [kbId]);
  useEffect(() => {
    // 页面刷新后恢复跟踪：该库最近若仍有进行中任务则接续轮询
    if (!kbId) return;
    apiClient
      .get(`/knowledge/bases/${kbId}/graph/extract/jobs`, { params: { limit: 5 } })
      .then((res) => {
        const list = Array.isArray(res.data) ? res.data : [];
        const active = list.find((j: JobStatus) =>
          ["pending", "running"].includes(j.status),
        );
        if (active) {
          setJob(active);
          poll(kbId, active.id);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbId]);

  const poll = (kb: string, jobId: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await apiClient.get(
          `/knowledge/bases/${kb}/graph/extract/jobs/${jobId}`,
        );
        const data: JobStatus = res.data;
        setJob(data);
        if (["succeeded", "failed", "cancelled"].includes(data.status)) {
          stopPolling();
          if (data.status === "succeeded") {
            message.success(
              zh
                ? `深度抽取完成：实体 ${data.entities_found}、关系 ${data.relations_found}`
                : `Deep extraction done: ${data.entities_found} entities, ${data.relations_found} relations`,
            );
            onExtracted();
          } else if (data.status === "cancelled") {
            message.info(zh ? "深度抽取已取消（已完成部分保留）" : "Deep extraction cancelled");
            onExtracted();
          } else {
            message.error(data.error || (zh ? "深度抽取失败" : "Deep extraction failed"));
          }
          setTimeout(() => setJob(null), 4000);
        }
      } catch {
        stopPolling();
      }
    }, 2000);
  };

  const extract = async (mode: "rules" | "llm") => {
    if (!kbId || rulesLoading) return;
    setRulesLoading(true);
    try {
      const res = await apiClient.post(`/knowledge/bases/${kbId}/graph/extract`, {
        mode,
      });
      if (mode === "rules") {
        const report = res.data || {};
        if ((report.entities_created || 0) === 0 && (report.relations_created || 0) === 0) {
          message.info(
            zh
              ? "抽取完成：未发现满足阈值的实体（可检查文档内容或降低词频阈值）"
              : "Extracted nothing above threshold",
          );
        } else {
          message.success(
            zh
              ? `抽取完成：新增实体 ${report.entities_created} 个、关系 ${report.relations_created} 条`
              : `Extracted: ${report.entities_created} entities, ${report.relations_created} relations`,
          );
        }
        onExtracted();
      } else {
        const jobId = res.data?.job_id as string;
        if (jobId) {
          message.info(zh ? "深度抽取任务已启动（大模型逐片抽取，可取消）" : "Deep extraction started");
          poll(kbId, jobId);
        }
      }
    } catch (e: any) {
      message.error(e.response?.data?.detail || (zh ? "抽取失败" : "Extraction failed"));
    } finally {
      setRulesLoading(false);
    }
  };

  const cancel = async () => {
    if (!kbId || !job) return;
    try {
      await apiClient.post(
        `/knowledge/bases/${kbId}/graph/extract/jobs/${job.id}/cancel`,
      );
      message.info(zh ? "取消请求已发送" : "Cancel requested");
    } catch {
      /* 轮询会兜底收尾 */
    }
  };

  const running = job && ["pending", "running"].includes(job.status);

  return (
    <div data-testid="kg-extraction-control">
      <Space>
        <Tooltip title={zh ? "jieba 词性粗分 + 共现，秒级；类型为词性桶（概念/术语…）" : "Rules-based quick extraction"}>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={() => extract("rules")}
            disabled={!kbId}
            loading={rulesLoading}
          >
            {zh ? "快速抽取" : "Quick extract"}
          </Button>
        </Tooltip>
        <Tooltip
          title={
            zh
              ? "大模型按本体逐片深度抽取：领域类型/别名/属性/关系证据；耗时较长，可取消"
              : "LLM deep extraction with ontology: typed entities, aliases, attributes, evidence"
          }
        >
          <Button
            icon={<RobotOutlined />}
            onClick={() => extract("llm")}
            disabled={!kbId || !!running}
          >
            {zh ? "深度抽取" : "Deep extract"}
          </Button>
        </Tooltip>
        {running && (
          <Button icon={<StopOutlined />} onClick={cancel} danger>
            {zh ? "取消" : "Cancel"}
          </Button>
        )}
      </Space>
      {running && (
        <div style={{ marginTop: 4, width: 260 }}>
          <Progress
            percent={job!.progress}
            size="small"
            status="active"
            format={() =>
              zh
                ? `${job!.done_units}/${job!.total_units} 片 · 实体 ${job!.entities_found} · 关系 ${job!.relations_found}`
                : `${job!.done_units}/${job!.total_units} · ${job!.entities_found}E/${job!.relations_found}R`
            }
          />
        </div>
      )}
    </div>
  );
}
