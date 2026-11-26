import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert, App as AntApp, Button, Drawer, Empty, Space, Spin, Tag, Typography,
} from "antd";
import { DownloadOutlined, SaveOutlined } from "@ant-design/icons";
import {
  archiveEvidenceCheck, downloadEvidence, exportEvidence, getEvidenceOverview,
} from "../../api/evidenceChain";
import type { EvidenceOverview } from "../../api/evidenceChain";
import { apiErrorText } from "../../api/qualityAlerts";
import { CheckList, StageList } from "./EvidenceOverviewParts";
import { useI18n } from "../../i18n";

/** 闭环证据总览抽屉（补齐路线第一批 F2b，B1-12/E21，技术方案 §9.9）。
 *
 * 挂在模型库的版本列表上：一屏看清一个模型版本的 12 环节状态与上线检查五项，
 * 各步可下钻到源记录；可留档一次检查、可导出证据链 ZIP。
 *
 * 路由钩子只在抽屉打开且数据就绪后才被调用（见 EvidenceBody）：抽屉关闭时
 * 不触碰路由上下文，宿主页面在无路由环境里渲染也不会报错。
 */

export interface EvidenceOverviewDrawerProps {
  projectId?: string;
  versionId?: string;
  /** 版本标签，如 v3 */
  label?: string;
  /** 留档是配置类动作（后端要求 quality.manage）；由调用方按角色传入 */
  canManage?: boolean;
  onClose: () => void;
}

const STATUS_TEXT: Record<string, string> = {
  complete: "完成", pending: "待发生", missing: "缺失", not_supported: "未接入", not_applicable: "不适用",
};

function EvidenceBody({
  overview, lang, canManage, busy, onArchive, onExport,
}: {
  overview: EvidenceOverview;
  lang: "zh" | "en";
  canManage: boolean;
  busy: "archive" | "export" | undefined;
  onArchive: () => void;
  onExport: () => void;
}) {
  const navigate = useNavigate();
  const zh = lang === "zh";
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }} data-testid="evidence-overview">
      <Alert
        type={overview.checks_passed === overview.checks.length ? "success" : "warning"}
        showIcon
        data-testid="evidence-check-summary"
        message={zh
          ? `上线检查 ${overview.checks_passed}/${overview.checks.length} 项通过`
          : `Launch checks ${overview.checks_passed}/${overview.checks.length} passed`}
        description={overview.checksum_verified
          ? (zh ? "当前结果来自留档：已重新计算模型文件校验和并与登记值比对。" : "Archived result: model checksum recomputed and compared.")
          : (zh ? "总览不重算模型文件哈希；点「留档本次检查」会重算并比对。" : "The overview does not recompute the model hash; archiving does.")}
      />

      <section>
        <Typography.Title level={5} style={{ marginBottom: 4 }}>
          {zh ? "闭环 12 环节" : "Twelve closed-loop stages"}
        </Typography.Title>
        <Space wrap style={{ marginBottom: 8 }}>
          {(Object.keys(overview.summary) as (keyof typeof overview.summary)[]).map((status) => (
            <Tag key={status} data-testid={`stage-summary-${status}`}>
              {zh ? STATUS_TEXT[status] : status.replace("_", " ")} × {overview.summary[status]}
            </Tag>
          ))}
        </Space>
        <StageList stages={overview.stages} lang={lang} onOpenRef={(path) => navigate(path)} />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }} data-testid="evidence-stage-footnote">
          {zh
            ? "「未接入」指平台当前版本还不产出这类证据（切分与主动选样随第二批接入、现场验证随第四批接入），不代表该模型缺证据；「缺失」才是应当存在却找不到的记录。"
            : "\"Not supported yet\" means the platform does not produce this evidence yet; \"Missing\" means an expected record was not found."}
        </Typography.Paragraph>
      </section>

      <section>
        <Typography.Title level={5} style={{ marginBottom: 4 }}>
          {zh ? "上线检查五项" : "Five launch checks"}
        </Typography.Title>
        <CheckList checks={overview.checks} lang={lang} />
        {overview.archived_check && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {zh ? "最近留档：" : "Latest archive: "}{overview.archived_check.created_at}
            {zh ? `（${overview.archived_check.checks_passed}/5 通过）` : ` (${overview.archived_check.checks_passed}/5 passed)`}
          </Typography.Text>
        )}
      </section>

      <Space>
        {canManage && (
          <Button icon={<SaveOutlined />} loading={busy === "archive"} onClick={onArchive} data-testid="evidence-archive">
            {zh ? "留档本次检查" : "Archive this check"}
          </Button>
        )}
        <Button icon={<DownloadOutlined />} loading={busy === "export"} onClick={onExport} data-testid="evidence-export">
          {zh ? "导出证据包" : "Export evidence"}
        </Button>
      </Space>
    </Space>
  );
}

export default function EvidenceOverviewDrawer({
  projectId, versionId, label = "", canManage = false, onClose,
}: EvidenceOverviewDrawerProps) {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [overview, setOverview] = useState<EvidenceOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"archive" | "export" | undefined>(undefined);

  const load = useCallback(() => {
    if (!projectId || !versionId) { setOverview(null); return; }
    setLoading(true);
    getEvidenceOverview(projectId, versionId)
      .then(setOverview)
      .catch((e) => message.error(apiErrorText(e)))
      .finally(() => setLoading(false));
  }, [projectId, versionId, message]);

  useEffect(() => { load(); }, [load]);

  const archive = async () => {
    if (!projectId || !versionId) return;
    setBusy("archive");
    try {
      setOverview(await archiveEvidenceCheck(projectId, versionId));
      message.success(zh ? "已留档：重新计算了模型校验和，并保存了当时的 12 环节快照" : "Archived with a recomputed checksum");
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(undefined);
    }
  };

  const exportZip = async () => {
    if (!projectId || !versionId) return;
    setBusy("export");
    try {
      const created = await exportEvidence(projectId, "model_version", versionId);
      const blob = await downloadEvidence(projectId, created.artifact_id);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = created.name || "evidence.zip";
      link.click();
      URL.revokeObjectURL(href);
      message.success(zh ? `证据包已导出（${created.file_count} 个文件，附 MANIFEST.SHA256）` : `Evidence exported (${created.file_count} files)`);
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Drawer
      open={Boolean(versionId)}
      onClose={onClose}
      width={780}
      destroyOnClose
      title={(
        <Space wrap>
          <Typography.Text strong>{zh ? "闭环证据总览" : "Closed-loop evidence"} {label}</Typography.Text>
          {overview?.model_version.model_name && (
            <Typography.Text type="secondary">{overview.model_version.model_name}</Typography.Text>
          )}
        </Space>
      )}
    >
      {overview ? (
        <EvidenceBody
          overview={overview} lang={lang} canManage={canManage} busy={busy}
          onArchive={archive} onExport={exportZip}
        />
      ) : loading ? (
        <Spin style={{ display: "block", margin: "48px auto" }} />
      ) : (
        <Empty description={zh ? "没有可展示的证据总览" : "No overview"} />
      )}
    </Drawer>
  );
}
