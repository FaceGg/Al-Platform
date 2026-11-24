import { Button, Modal, Space, Tooltip, message } from "antd";
import { RobotOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useI18n } from "../../i18n";
import type { KgExtractionApi, KgExtractSummary } from "./useKgExtraction";

/**
 * 抽取动作按钮：快速抽取 / 深度抽取。
 *
 * 「重新抽取」不单独设按钮：库里已有抽取结果的，再次点击会先弹确认框，用户
 * 确认后才重新跑。快速抽取与深度抽取不并存、以最后一次抽取为主，所以确认框
 * 分两种：
 * - 点的是生成当前图谱的那一种 →「重新抽取」；
 * - 点的是另一种 →「改用××抽取」：提示会替换现有图谱。
 * 深度抽取另有续建语义：有未完成分片（新增文档/上次失败）时默认只补这些
 * 分片，全部重做作为对话框里的次要动作——重做要重花全部大模型调用。
 */
export default function ExtractionActions({ extraction }: { extraction: KgExtractionApi }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { kbId, summary, ensureSummary, running, waitingCancel, rulesLoading, deepStarting } =
    extraction;
  const cancelText = zh ? "取消" : "Cancel";
  const busy = running || waitingCancel;
  const rerunAllText = zh ? "全部重新抽取" : "Re-extract everything";

  const describe = (s: KgExtractSummary) => {
    // 千分位与画布标题栏一致
    const n = (v: number) => v.toLocaleString();
    const scale = s.graph
      ? (zh ? `（实体 ${n(s.graph.entities)}、关系 ${n(s.graph.relations)}）`
        : ` (${n(s.graph.entities)} entities, ${n(s.graph.relations)} relations)`)
      : "";
    const source = s.current === "llm"
      ? (zh ? "深度抽取" : "deep extraction")
      : s.current === "mixed"
        ? (zh ? "快速抽取和深度抽取" : "quick and deep extraction")
        : (zh ? "快速抽取" : "quick extraction");
    return { scale, source };
  };

  // 确认框读的是摘要：摘要还没到（或上次加载失败）就先补拉一次，拉不到就提示
  const ready = async (): Promise<KgExtractSummary | null> => {
    const s = summary ?? await ensureSummary();
    if (!s) {
      message.warning(zh ? "抽取状态加载失败，请重试" : "Failed to load extraction status");
    }
    return s;
  };

  const onQuick = async () => {
    if (!kbId || busy) return;
    const s = await ready();
    if (!s) return;
    // 从未抽取：直接开始
    if (s.current === null) {
      extraction.startRules();
      return;
    }
    const { scale, source } = describe(s);
    if (s.current === "rules") {
      Modal.confirm({
        title: zh ? "该知识库已快速抽取过" : "Quick extraction already done",
        content: zh
          ? `当前图谱由快速抽取生成${scale}。重新抽取会重建图谱（秒级完成），是否继续？`
          : `The current graph comes from quick extraction${scale}. Re-extraction rebuilds it (takes seconds). Continue?`,
        okText: zh ? "重新抽取" : "Re-extract",
        cancelText,
        onOk: () => extraction.startRules(),
      });
      return;
    }
    Modal.confirm({
      title: zh ? "改用快速抽取？" : "Switch to quick extraction?",
      width: 520,
      content: zh
        ? `当前图谱由${source}生成${scale}。快速抽取与深度抽取不并存，以最后一次抽取为主：本次快速抽取将替换现有图谱。是否继续？`
        : `The current graph comes from ${source}${scale}. Quick and deep extraction do not coexist — the latest one wins: this run replaces the current graph. Continue?`,
      okText: zh ? "改用快速抽取" : "Switch to quick",
      cancelText,
      onOk: () => extraction.startRules(),
    });
  };

  const onDeep = async () => {
    if (!kbId || busy || rulesLoading) return;
    const s = await ready();
    if (!s) return;
    const { scale, source } = describe(s);
    const chunks = s.chunks ?? 0;
    const pending = s.llm?.pending_chunks ?? 0;
    const cached = s.llm?.cached_chunks ?? 0;
    // 成本护栏：单个任务最多处理 maxChunks 片，待抽分片更多时分多次完成。
    // 摘要没带这个字段（旧后端）时按「一次能抽完」表述
    const maxChunks = Math.max(1, s.llm?.max_chunks_per_job ?? pending ?? 1);
    const batch = Math.min(pending, maxChunks);
    // 耗时提醒：要分多次时说明每次上限
    const effort = pending > maxChunks
      ? (zh ? `（每次最多 ${maxChunks} 片，分多次完成，耗时较长）`
        : ` (at most ${maxChunks} chunks per run, several runs, this takes a while)`)
      : (zh ? "（耗时较长）" : " (this takes a while)");

    // 从未抽取：直接开始（此前抽过的分片若有缓存会直接恢复）
    if (s.current === null) {
      extraction.startDeep(false);
      return;
    }

    if (s.current === "llm") {
      // 分片都抽过了、但上次任务没成功结束（收尾的归并/同步失败）：重试只重做
      // 收尾，不调用大模型；全部重做作为次要动作
      const lastStatus = s.llm?.latest_job?.status;
      if (pending === 0 && (lastStatus === "failed" || lastStatus === "cancelled")) {
        let dialog: { destroy: () => void } | undefined;
        dialog = Modal.confirm({
          title: zh ? "上次深度抽取没有完成" : "The last deep extraction did not finish",
          width: 520,
          content: (
            <div>
              <div>
                {zh
                  ? `当前图谱由深度抽取生成${scale}，全部 ${chunks} 个分片都已抽取。重试只重新归并并同步图谱，不调用大模型。`
                  : `The current graph comes from deep extraction${scale}; all ${chunks} chunks are extracted. Retrying only re-runs the merge and sync steps without calling the LLM.`}
              </div>
              <div style={{ marginTop: 8 }}>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => {
                    dialog?.destroy();
                    extraction.startDeep(true);
                  }}
                >
                  {rerunAllText}
                </Button>
              </div>
            </div>
          ),
          okText: zh ? "重试" : "Retry",
          cancelText,
          onOk: () => extraction.startDeep(false),
        });
        return;
      }
      if (pending > 0) {
        let dialog: { destroy: () => void } | undefined;
        dialog = Modal.confirm({
          title: zh ? "继续深度抽取？" : "Continue deep extraction?",
          width: 520,
          content: (
            <div>
              <div>
                {zh
                  ? (pending > maxChunks
                    ? `当前图谱由深度抽取生成${scale}。还有 ${pending} 个分片未完成抽取（新增文档或上次失败）。深度抽取每次最多处理 ${maxChunks} 片：本次抽取 ${batch} 片，其余 ${pending - batch} 片下次继续。`
                    : `当前图谱由深度抽取生成${scale}。还有 ${pending} 个分片未完成抽取（新增文档或上次失败），本次只抽取这些分片。`)
                  : (pending > maxChunks
                    ? `The current graph comes from deep extraction${scale}. ${pending} chunk(s) are not finished yet (new documents or previous failures). Deep extraction handles at most ${maxChunks} chunks per run: this run does ${batch}, the remaining ${pending - batch} continue next time.`
                    : `The current graph comes from deep extraction${scale}. ${pending} chunk(s) are not finished yet (new documents or previous failures); this run extracts only those.`)}
              </div>
              <div style={{ marginTop: 8 }}>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => {
                    dialog?.destroy();
                    extraction.startDeep(true);
                  }}
                >
                  {rerunAllText}
                </Button>
              </div>
            </div>
          ),
          okText: zh ? `抽取未完成的 ${batch} 片` : `Extract ${batch} pending chunk(s)`,
          cancelText,
          onOk: () => extraction.startDeep(false),
        });
        return;
      }
      Modal.confirm({
        title: zh ? "该知识库已深度抽取过" : "Deep extraction already done",
        width: 520,
        content: zh
          ? `当前图谱由深度抽取生成${scale}，全部 ${chunks} 个分片都已抽取。重新抽取会用当前模型与词表重做全部分片并重建图谱，是否继续？`
          : `The current graph comes from deep extraction${scale}; all ${chunks} chunks are extracted. Re-extraction redoes every chunk with the current model and ontology and rebuilds the graph. Continue?`,
        okText: zh ? "重新抽取" : "Re-extract",
        cancelText,
        onOk: () => extraction.startDeep(true),
      });
      return;
    }

    // 当前图谱是快速抽取结果（或两层并存时期留下的混杂数据）：改用深度抽取
    const plan = pending === 0
      ? (zh
        ? `此前抽取过的 ${cached} 个分片将直接恢复，不再调用大模型。`
        : `The ${cached} previously extracted chunk(s) are restored from cache without calling the LLM.`)
      : cached > 0
        ? (zh
          ? `此前抽取过的 ${cached} 个分片直接恢复，其余 ${pending} 个分片调用大模型抽取${effort}。`
          : `The ${cached} previously extracted chunk(s) are restored from cache; the remaining ${pending} chunk(s) call the LLM${effort}.`)
        : (zh
          ? `需调用大模型抽取 ${pending} 个分片${effort}。`
          : `The LLM extracts ${pending} chunk(s)${effort}.`);
    let dialog: { destroy: () => void } | undefined;
    dialog = Modal.confirm({
      title: zh ? "改用深度抽取？" : "Switch to deep extraction?",
      width: 520,
      content: (
        <div>
          <div>
            {zh
              ? `当前图谱由${source}生成${scale}。快速抽取与深度抽取不并存，以最后一次抽取为主：本次深度抽取将替换现有图谱。`
              : `The current graph comes from ${source}${scale}. Quick and deep extraction do not coexist — the latest one wins: this run replaces the current graph.`}
          </div>
          <div>{plan}</div>
          {cached > 0 && (
            <div style={{ marginTop: 8 }}>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => {
                  dialog?.destroy();
                  extraction.startDeep(true);
                }}
              >
                {rerunAllText}
              </Button>
            </div>
          )}
        </div>
      ),
      okText: zh ? "改用深度抽取" : "Switch to deep",
      cancelText,
      onOk: () => extraction.startDeep(false),
    });
  };

  return (
    <Space data-testid="kg-extraction-actions">
      <Tooltip
        title={zh
          ? "规则引擎按词频抽取，秒级完成；类型是词性粗分（概念/术语…）"
          : "Rule-based extraction by word frequency (seconds); types are coarse word classes"}
      >
        <Button
          icon={<ThunderboltOutlined />}
          onClick={onQuick}
          disabled={!kbId || busy || deepStarting}
          loading={rulesLoading}
          data-testid="kg-quick-extract"
        >
          {zh ? "快速抽取" : "Quick extract"}
        </Button>
      </Tooltip>
      <Tooltip
        title={zh
          ? "大模型按本体抽取：领域类型、别名、属性与关系证据。快速抽取与深度抽取不并存，以最后一次为主"
          : "LLM extraction with your ontology: typed entities, aliases, attributes and evidence. Quick and deep extraction do not coexist — the latest one wins"}
      >
        <Button
          type="primary"
          icon={<RobotOutlined />}
          onClick={onDeep}
          disabled={!kbId || busy || rulesLoading}
          loading={deepStarting}
          data-testid="kg-deep-extract"
        >
          {zh ? "深度抽取" : "Deep extract"}
        </Button>
      </Tooltip>
    </Space>
  );
}
