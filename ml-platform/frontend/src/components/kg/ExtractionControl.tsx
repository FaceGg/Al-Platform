import { useEffect, useRef, useState } from "react";
import { Button, Popconfirm, Progress, Space, Tag, Tooltip, message } from "antd";
import { ThunderboltOutlined, RobotOutlined, StopOutlined, RedoOutlined } from "@ant-design/icons";
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
  created_at?: string | null;
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
  const [cancelling, setCancelling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastDoneRef = useRef(-1);
  const lastRefreshRef = useRef(0);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);
  useEffect(() => {
    // 切库时终止旧轮询并清空进度（进度条严格按库隔离）
    stopPolling();
    setJob(null);
    setCancelling(false);
  }, [kbId]);
  useEffect(() => {
    // 页面刷新后恢复跟踪：只接续「最近 30 分钟内创建」的进行中任务——
    // 更早的 running 多为异常残留（worker 重启/取消未落地），恢复它们只会
    // 让切库时永远看到进度条
    if (!kbId) return;
    apiClient
      .get(`/knowledge/bases/${kbId}/graph/extract/jobs`, { params: { limit: 5 } })
      .then((res) => {
        const list = Array.isArray(res.data) ? res.data : [];
        const fresh = (item: JobStatus) => {
          if (!item.created_at) return false;
          const age = Date.now() - new Date(item.created_at).getTime();
          return age < 30 * 60 * 1000;
        };
        const active = list.find(
          (j: JobStatus) => ["pending", "running"].includes(j.status) && fresh(j),
        );
        if (active) {
          setJob(active);
          poll(kbId, active.id);
          return;
        }
        // 无进行中任务：展示最近一次抽取的结果标注（已完成/失败持续可见）
        const [latest] = list;
        if (latest && ["succeeded", "failed"].includes(latest.status)) {
          setJob(latest);
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
        // 实时成长：分片完成数变化时刷新画布（后端流式落库，图随抽取生长）；
        // ≥4s 节流避免大库全量拉图过频
        if (
          data.done_units !== lastDoneRef.current &&
          Date.now() - lastRefreshRef.current > 4000
        ) {
          lastDoneRef.current = data.done_units;
          lastRefreshRef.current = Date.now();
          onExtracted();
        }
        if (["succeeded", "failed", "cancelled"].includes(data.status)) {
          stopPolling();
          setCancelling(false);
          if (data.status === "succeeded" && data.total_units === 0 && (lastDoneRef.current <= 0)) {
            // 全部缓存命中（空跑）：该库所有分片此前均已抽取完成
            message.info(
              zh
                ? "该知识库的所有分片均已抽取完成，本次无新增内容可抽取；如需重建图谱请先增补/修改文档后重试"
                : "All chunks are already extracted; add or update documents to re-extract",
            );
            onExtracted();
          } else if (data.status === "succeeded") {
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
          // 终态不清 job：状态标注（已完成/失败/取消）持续显示在工具条
        }
      } catch {
        stopPolling();
      }
    }, 2000);
  };

  const extract = async (mode: "rules" | "llm", force = false) => {
    if (!kbId || rulesLoading) return;
    setRulesLoading(true);
    try {
      const body: Record<string, unknown> = { mode };
      if (force) body.force = true;
      const res = await apiClient.post(`/knowledge/bases/${kbId}/graph/extract`, body);
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
      // 防重入 409：同库已有进行中任务——自动接手跟踪它（显示进度+可取消），
      // 而不是给用户一条裸错误
      if (e?.response?.status === 409) {
        try {
          const list = await apiClient.get(
            `/knowledge/bases/${kbId}/graph/extract/jobs`,
            { params: { limit: 5 } },
          );
          const jobs: JobStatus[] = Array.isArray(list.data) ? list.data : [];
          const active = jobs.find((j) => ["pending", "running"].includes(j.status));
          if (active) {
            setJob(active);
            poll(kbId, active.id);
            message.info(
              zh
                ? "该知识库已有进行中的抽取任务，已为您接续显示进度（可取消后重新抽取）"
                : "A job is already running; tracking it now (cancel it to re-extract)",
            );
            return;
          }
        } catch {
          /* 落到下面的通用错误提示 */
        }
      }
      message.error(e.response?.data?.detail || (zh ? "抽取失败" : "Extraction failed"));
    } finally {
      setRulesLoading(false);
    }
  };

  const cancel = async () => {
    if (!kbId || !job || cancelling) return;
    setCancelling(true);
    try {
      await apiClient.post(
        `/knowledge/bases/${kbId}/graph/extract/jobs/${job.id}/cancel`,
      );
      message.info(
        zh
          ? "已请求取消：当前分片完成后停止（长分片约需数分钟），已完成分片保留"
          : "Cancel requested: stops after the current chunk finishes",
      );
    } catch {
      setCancelling(false);
      message.error(zh ? "取消请求失败，请重试" : "Cancel failed");
    }
  };

  const running =
    !!job && ["pending", "running"].includes(job.status) && !cancelling;
  const waitingCancel = !!job && cancelling;

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
        <Popconfirm
          title={
            zh
              ? "重新提取将忽略已完成的分片缓存，用当前模型与词表重做全部文档分片，图谱 LLM 层将重建。确认？"
              : "Re-extract ignores the finished-chunk cache and rebuilds the LLM layer with the current model & ontology. Confirm?"
          }
          onConfirm={() => extract("llm", true)}
          okText={zh ? "重新提取" : "Re-extract"}
          cancelText={zh ? "取消" : "Cancel"}
          disabled={!kbId || !!running}
        >
          <Button
            icon={<RedoOutlined />}
            disabled={!kbId || !!running}
            data-testid="kg-reextract"
          >
            {zh ? "重新提取" : "Re-extract"}
          </Button>
        </Popconfirm>
        {running && (
          <Button icon={<StopOutlined />} onClick={cancel} danger>
            {zh ? "取消" : "Cancel"}
          </Button>
        )}
        {waitingCancel && (
          <Button icon={<StopOutlined />} danger disabled>
            {zh ? "取消中…" : "Cancelling…"}
          </Button>
        )}
      </Space>
      {(running || waitingCancel) && job && (
        <div style={{ marginTop: 4, width: 260 }}>
          <Progress
            percent={job.progress}
            size="small"
            status={waitingCancel ? "normal" : "active"}
            format={() =>
              zh
                ? `${job.done_units}/${job.total_units} 片 · 实体 ${job.entities_found} · 关系 ${job.relations_found}`
                : `${job.done_units}/${job.total_units} · ${job.entities_found}E/${job.relations_found}R`
            }
          />
        </div>
      )}
      {/* 终态标注（持续显示，直到下一次抽取）：已完成/失败/取消 */}
      {job && !running && !waitingCancel && (
        <div style={{ marginTop: 4 }}>
          {job.status === "succeeded" && (
            <Tag color="success" style={{ marginInlineEnd: 0 }} data-testid="kg-extract-done">
              {zh
                ? `✓ 已完成 · 实体 ${job.entities_found} · 关系 ${job.relations_found}${job.total_units === 0 ? "（无新增分片）" : ""}`
                : `✓ Done · ${job.entities_found}E/${job.relations_found}R${job.total_units === 0 ? " (nothing new)" : ""}`}
            </Tag>
          )}
          {job.status === "failed" && (
            <Space size={6}>
              <Tag color="error" style={{ marginInlineEnd: 0 }}>
                {zh ? `上次抽取失败${job.llm_errors ? `（${job.llm_errors} 片失败）` : ""}` : "Failed"}
              </Tag>
              <Button size="small" type="link" onClick={() => extract("llm")}>
                {zh ? "续抽失败分片" : "Retry failed"}
              </Button>
            </Space>
          )}
          {job.status === "cancelled" && (
            <Tag>{zh ? "上次抽取已取消（已完成分片保留）" : "Cancelled"}</Tag>
          )}
        </div>
      )}
    </div>
  );
}
