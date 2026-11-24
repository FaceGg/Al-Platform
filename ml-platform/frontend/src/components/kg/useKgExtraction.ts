import { useCallback, useEffect, useRef, useState } from "react";
import { message } from "antd";
import apiClient from "../../api/client";
import { useI18n } from "../../i18n";

/** 深度抽取任务的状态载荷（进度端点 / 摘要端点同一形态） */
export interface KgJobInfo {
  id: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  mode?: string;
  total_units: number;
  done_units: number;
  progress: number;
  entities_found: number;
  relations_found: number;
  llm_calls?: number;
  llm_errors?: number;
  error?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
}

/** 抽取状态摘要：当前图谱由哪种抽取生成、图谱规模、未完成分片数、深度抽取任务 */
export interface KgExtractSummary {
  chunks: number;
  /** 库内当前图谱由哪种抽取生成；mixed=两层并存时期留下的存量数据；null=未抽取 */
  current: "rules" | "llm" | "mixed" | null;
  /** 当前图谱规模（与画布标题栏同口径） */
  graph: { entities: number; relations: number };
  rules: { extracted: boolean; entities: number };
  llm: {
    extracted: boolean;
    pending_chunks: number;
    /** 抽过的分片数：改用深度抽取时直接恢复，不再调用大模型 */
    cached_chunks: number;
    /** 成本护栏：单个任务最多调大模型的分片数；待抽分片多于它时分多次完成 */
    max_chunks_per_job?: number;
    latest_job: KgJobInfo | null;
    active_job: KgJobInfo | null;
  };
}

const POLL_INTERVAL_MS = 2000;
// 图谱刷新节流：大库全图（数千实体、数十万关系）很重，抽取期间不必每片都拉
const GRAPH_REFRESH_THROTTLE_MS = 4000;
// 轮询连续失败这么多次才停（单次网络抖动 / 后端重启不应让进度显示中断）
const MAX_POLL_FAILURES = 5;
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

/**
 * 知识图谱抽取的状态与动作（快速抽取 / 深度抽取）。
 *
 * 只管数据与流程，不管界面：动作按钮与状态行两个组件共用同一个实例，
 * 「再次点击弹哪种确认框」的交互策略放在 ExtractionActions 里。
 * 快速抽取与深度抽取不并存、以最后一次抽取为主——图谱只有一份，摘要里的
 * current 说明它是谁生成的。
 * 对外回调通过 ref 转发——轮询定时器的闭包里始终拿到最新值。
 */
export function useKgExtraction({
  kbId,
  onExtracted,
}: {
  kbId: string | null;
  /** 图谱有变化（抽取产出落库 / 抽取结果被替换），页面据此重新拉图 */
  onExtracted: () => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [summary, setSummary] = useState<KgExtractSummary | null>(null);
  // 跟踪中的任务：进行中的那个，否则最近一次（用于状态标注）
  const [job, setJob] = useState<KgJobInfo | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [deepStarting, setDeepStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastDoneRef = useRef(-1);
  const lastRefreshRef = useRef(0);
  const jobRef = useRef<KgJobInfo | null>(null);
  const summaryRef = useRef<KgExtractSummary | null>(null);
  const cancellingRef = useRef(false);

  const kbRef = useRef(kbId);
  const onExtractedRef = useRef(onExtracted);
  const zhRef = useRef(zh);
  kbRef.current = kbId;
  onExtractedRef.current = onExtracted;
  zhRef.current = zh;
  jobRef.current = job;
  summaryRef.current = summary;
  cancellingRef.current = cancelling;

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refreshSummary = useCallback(async (kb: string): Promise<KgExtractSummary | null> => {
    try {
      const res = await apiClient.get(`/knowledge/bases/${kb}/graph/extract/summary`);
      // 切库后的过期响应不落地（否则摘要属于上一个库）
      if (kbRef.current !== kb) return null;
      const data = res.data as KgExtractSummary;
      setSummary(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  /** 确认框要读摘要：摘要还没到（或上次加载失败）就先补拉一次 */
  const ensureSummary = useCallback(async (): Promise<KgExtractSummary | null> => {
    const kb = kbRef.current;
    if (!kb) return null;
    return summaryRef.current ?? refreshSummary(kb);
  }, [refreshSummary]);

  const startPolling = useCallback((kb: string, jobId: string) => {
    stopPolling();
    lastDoneRef.current = -1;
    lastRefreshRef.current = 0;
    let failures = 0;
    pollRef.current = setInterval(async () => {
      if (kbRef.current !== kb) {
        stopPolling();
        return;
      }
      try {
        const res = await apiClient.get(
          `/knowledge/bases/${kb}/graph/extract/jobs/${jobId}`,
        );
        failures = 0;
        const data: KgJobInfo = res.data;
        const zhNow = zhRef.current;
        if (TERMINAL_STATUSES.has(data.status)) {
          stopPolling();
          setCancelling(false);
          // 先刷新摘要（当前图谱来源与规模落到终态），再落任务终态——
          // 状态标注不会先闪一下「未抽取」或上一轮的数字
          await refreshSummary(kb);
          if (kbRef.current !== kb) return;
          setJob(data);
          onExtractedRef.current?.();
          if (data.status === "succeeded") {
            if (data.total_units === 0) {
              message.info(
                zhNow
                  ? "没有需要抽取的分片：该知识库的深度抽取结果已是最新"
                  : "Nothing to extract: deep-extraction results are up to date",
              );
            } else {
              message.success(
                zhNow
                  ? `深度抽取完成：当前图谱实体 ${data.entities_found} 个、关系 ${data.relations_found} 条`
                  : `Deep extraction done: graph now has ${data.entities_found} entities and ${data.relations_found} relations`,
              );
            }
          } else if (data.status === "cancelled") {
            message.info(
              zhNow
                ? "深度抽取已取消，已抽出的部分保留在图谱里"
                : "Deep extraction cancelled; extracted chunks are kept",
            );
          } else {
            // 具体原因（大模型超时/卡住等）在状态行的标注里悬停可见
            message.error(
              zhNow
                ? `深度抽取未完成（已处理 ${data.done_units}/${data.total_units} 片），可点击状态行的「继续抽取」补抽剩余分片`
                : `Deep extraction did not finish (${data.done_units}/${data.total_units} chunks); use "Resume" in the status bar`,
            );
          }
          return;
        }
        setJob(data);
        // 分片完成数变化：刷新图（节流——大库全图很重）
        if (
          data.done_units !== lastDoneRef.current &&
          Date.now() - lastRefreshRef.current > GRAPH_REFRESH_THROTTLE_MS
        ) {
          lastDoneRef.current = data.done_units;
          lastRefreshRef.current = Date.now();
          onExtractedRef.current?.();
        }
      } catch {
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          stopPolling();
          void refreshSummary(kb);
        }
      }
    }, POLL_INTERVAL_MS);
  }, [stopPolling, refreshSummary]);

  // 切库 / 挂载：清状态并拉摘要；有进行中的任务则接续轮询（刷新页面不丢进度）
  useEffect(() => {
    stopPolling();
    setJob(null);
    setCancelling(false);
    setSummary(null);
    const kb = kbId;
    if (!kb) return undefined;
    let disposed = false;
    apiClient
      .get(`/knowledge/bases/${kb}/graph/extract/summary`)
      .then((res) => {
        if (disposed || kbRef.current !== kb) return;
        const data = res.data as KgExtractSummary;
        setSummary(data);
        const tracked = data.llm.active_job ?? data.llm.latest_job;
        if (tracked) setJob(tracked);
        if (data.llm.active_job) startPolling(kb, data.llm.active_job.id);
      })
      .catch(() => {});
    return () => {
      disposed = true;
      stopPolling();
    };
  }, [kbId, stopPolling, startPolling]);

  /** 快速抽取（规则引擎，同步执行）：替换库内上一轮抽取结果 */
  const startRules = useCallback(async () => {
    const kb = kbRef.current;
    if (!kb) return;
    setRulesLoading(true);
    try {
      await apiClient.post(`/knowledge/bases/${kb}/graph/extract`, { mode: "rules" });
      // 摘要先落地（当前图谱来源 + 规模），标注与提示里的数字才是本次抽取后的
      const fresh = await refreshSummary(kb);
      if (kbRef.current !== kb) return;
      const graph = fresh?.graph;
      const zhNow = zhRef.current;
      if (graph && graph.entities === 0) {
        message.info(
          zhNow
            ? "快速抽取完成：未发现满足阈值的实体（可检查文档内容）"
            : "Quick extraction found no entities above threshold",
        );
      } else if (graph) {
        message.success(
          zhNow
            ? `快速抽取完成：当前图谱实体 ${graph.entities} 个、关系 ${graph.relations} 条`
            : `Quick extraction done: graph now has ${graph.entities} entities and ${graph.relations} relations`,
        );
      }
      onExtractedRef.current?.();
    } catch (e: any) {
      message.error(
        e?.response?.data?.detail || (zhRef.current ? "快速抽取失败" : "Quick extraction failed"),
      );
    } finally {
      setRulesLoading(false);
    }
  }, [refreshSummary]);

  /**
   * 深度抽取（大模型，异步任务）。
   * force=false 续建：当前图谱已是深度抽取结果时只做未完成的分片（新增文档 /
   * 上次失败）；当前图谱是快速抽取结果时整体重建——抽过的分片按缓存恢复，
   * 没抽过的调用大模型。
   * force=true 全部重新抽取：作废缓存，重做全部分片。
   */
  const startDeep = useCallback(async (force: boolean) => {
    const kb = kbRef.current;
    if (!kb) return;
    setDeepStarting(true);
    try {
      const res = await apiClient.post(
        `/knowledge/bases/${kb}/graph/extract`,
        force ? { mode: "llm", force: true } : { mode: "llm" },
      );
      const jobId = res.data?.job_id as string | undefined;
      if (jobId) {
        message.info(
          zhRef.current
            ? "深度抽取已启动，图谱随抽取进度实时更新"
            : "Deep extraction started; the graph updates as chunks complete",
        );
        void refreshSummary(kb);
        startPolling(kb, jobId);
      }
    } catch (e: any) {
      if (e?.response?.status === 409) {
        // 防重入：同库已有进行中的任务——接手跟踪它，而不是给用户一条报错
        const fresh = await refreshSummary(kb);
        const active = fresh?.llm.active_job;
        if (active) {
          setJob(active);
          startPolling(kb, active.id);
          message.info(
            zhRef.current
              ? "该知识库已有进行中的抽取任务，已接续显示进度"
              : "An extraction is already running; now tracking its progress",
          );
          return;
        }
      }
      message.error(
        e?.response?.data?.detail
          || (zhRef.current ? "深度抽取启动失败" : "Failed to start deep extraction"),
      );
    } finally {
      setDeepStarting(false);
    }
  }, [refreshSummary, startPolling]);

  const cancel = useCallback(async () => {
    const kb = kbRef.current;
    const id = jobRef.current?.id;
    if (!kb || !id || cancellingRef.current) return;
    setCancelling(true);
    try {
      await apiClient.post(`/knowledge/bases/${kb}/graph/extract/jobs/${id}/cancel`);
      message.info(
        zhRef.current
          ? "已请求取消：当前分片完成后停止，已完成的分片保留"
          : "Cancel requested: stops after the current chunk finishes",
      );
    } catch {
      setCancelling(false);
      message.error(zhRef.current ? "取消请求失败，请重试" : "Cancel failed");
    }
  }, []);

  const running = !!job && (job.status === "pending" || job.status === "running") && !cancelling;
  const waitingCancel = !!job && cancelling;

  return {
    kbId,
    summary,
    ensureSummary,
    // 页面在手工增删实体/关系、融合审核、手动刷新之后调用：标注跟着图谱规模走
    refreshSummary,
    job,
    running,
    waitingCancel,
    rulesLoading,
    deepStarting,
    startRules,
    startDeep,
    cancel,
  };
}

export type KgExtractionApi = ReturnType<typeof useKgExtraction>;
