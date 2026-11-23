import { useEffect, useState } from "react";
import { Modal, Select, Space, Typography, message } from "antd";
import apiClient from "../../api/client";
import { useI18n } from "../../i18n";

const { Text } = Typography;

// 领域词表模板：填充到输入框后可再手动调整（只作填充辅助，保存仍走 PUT）
const TEMPLATES: Record<string, { entity_types: string[]; relation_types: string[] }> = {
  general: {
    entity_types: ["工艺", "缺陷", "设备", "材料", "指标", "标准", "部件", "组织", "人员", "概念"],
    relation_types: ["用于工艺", "导致缺陷", "属于设备", "包含部件", "依据标准", "参数为", "前置工序", "后置工序", "相关"],
  },
  tightening: {
    entity_types: ["拧紧工艺", "紧固件", "工具", "工件", "扭矩参数", "角度参数", "质量指标", "缺陷", "标准", "概念"],
    relation_types: ["用于工艺", "拧紧", "属于工件", "参数为", "依据标准", "导致缺陷", "前置工序", "后置工序", "相关"],
  },
  welding: {
    entity_types: ["焊接工艺", "焊缝", "缺陷", "设备", "材料", "指标", "标准", "部件", "概念"],
    relation_types: ["用于工艺", "导致缺陷", "属于设备", "包含部件", "依据标准", "参数为", "前置工序", "后置工序", "相关"],
  },
};

export default function OntologyModal({
  kbId,
  open,
  onClose,
  onSaved,
}: {
  kbId: string | null;
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [entityTypes, setEntityTypes] = useState<string[]>([]);
  const [relationTypes, setRelationTypes] = useState<string[]>([]);
  const [custom, setCustom] = useState(false);
  const [saving, setSaving] = useState(false);
  const [profiles, setProfiles] = useState<{ id: string; name: string; model_id: string }[]>([]);
  const [profileId, setProfileId] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!open || !kbId) return;
    apiClient
      .get(`/knowledge/bases/${kbId}/graph/ontology`)
      .then((res) => {
        setEntityTypes(res.data?.ontology?.entity_types || []);
        setRelationTypes(res.data?.ontology?.relation_types || []);
        setCustom(!!res.data?.custom);
        setProfileId(res.data?.kg_llm_profile_id || undefined);
      })
      .catch(() => message.error(zh ? "本体加载失败" : "Failed to load ontology"));
    apiClient
      .get(`/knowledge/bases/${kbId}/graph/llm-profiles`)
      .then((res) => setProfiles(Array.isArray(res.data) ? res.data : []))
      .catch(() => setProfiles([]));
  }, [open, kbId, zh]);

  const save = async () => {
    if (!kbId) return;
    setSaving(true);
    try {
      await apiClient.put(`/knowledge/bases/${kbId}/graph/ontology`, {
        entity_types: entityTypes,
        relation_types: relationTypes,
        kg_llm_profile_id: profileId || null,
      });
      message.success(
        zh ? "已保存，下一次深度抽取生效" : "Saved; applies to next deep extraction",
      );
      setCustom(true);
      onSaved?.();
      onClose();
    } catch (e: any) {
      message.error(e.response?.data?.detail || (zh ? "保存失败" : "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={zh ? "图谱本体设置（按库生效）" : "Graph ontology (per KB)"}
      open={open}
      onOk={save}
      onCancel={onClose}
      confirmLoading={saving}
      okText={zh ? "保存" : "Save"}
      cancelText={zh ? "取消" : "Cancel"}
      width={520}
    >
      <Space direction="vertical" style={{ width: "100%" }} size={12}>
        <Text type="secondary">
          {zh
            ? "深度抽取（LLM）按这套词表约束实体与关系类型；映射不到的类型自动落到兜底类。留空项回落默认工业本体。"
            : "LLM deep extraction maps entities/relations onto this vocabulary; unmapped ones fall back."}
          {custom ? (zh ? "（当前库：自定义）" : " (customized)") : zh ? "（当前库：默认）" : " (default)"}
        </Text>
        <div>
          <Text>{zh ? "按领域模板快速填充" : "Fill from domain template"}</Text>
          <Select
            style={{ width: "100%", marginTop: 4 }}
            value={undefined}
            onChange={(key: string) => {
              const tpl = TEMPLATES[key];
              if (tpl) {
                setEntityTypes([...tpl.entity_types]);
                setRelationTypes([...tpl.relation_types]);
              }
            }}
            placeholder={zh ? "选择领域后自动填充词表（可再手动调整）" : "Pick a template to fill"}
            data-testid="kg-ontology-template"
            options={[
              { value: "general", label: zh ? "通用工业（默认）" : "General industrial (default)" },
              { value: "tightening", label: zh ? "拧紧装配" : "Tightening assembly" },
              { value: "welding", label: zh ? "焊接工艺" : "Welding process" },
            ]}
          />
        </div>
        <div>
          <Text>{zh ? "实体类型" : "Entity types"}</Text>
          <Select
            mode="tags"
            style={{ width: "100%", marginTop: 4 }}
            value={entityTypes}
            onChange={setEntityTypes}
            tokenSeparators={[",", "、"]}
            placeholder={zh ? "输入后回车添加" : "Type and press enter"}
            open={false}
            data-testid="kg-ontology-entity-types"
          />
        </div>
        <div>
          <Text>{zh ? "关系类型" : "Relation types"}</Text>
          <Select
            mode="tags"
            style={{ width: "100%", marginTop: 4 }}
            value={relationTypes}
            onChange={setRelationTypes}
            tokenSeparators={[",", "、"]}
            placeholder={zh ? "输入后回车添加" : "Type and press enter"}
            open={false}
            data-testid="kg-ontology-relation-types"
          />
        </div>
        <div>
          <Text>{zh ? "抽取模型（深度抽取用；空 = 跟随平台默认档案）" : "Extraction model (blank = platform default)"}</Text>
          <Select
            style={{ width: "100%", marginTop: 4 }}
            allowClear
            value={profileId}
            onChange={(v) => setProfileId(v || undefined)}
            placeholder={zh ? "跟随平台默认档案" : "Follow platform default"}
            data-testid="kg-ontology-llm-profile"
            options={profiles.map((p) => ({
              value: p.id,
              label: `${p.name} · ${p.model_id}`,
            }))}
          />
        </div>
      </Space>
    </Modal>
  );
}
