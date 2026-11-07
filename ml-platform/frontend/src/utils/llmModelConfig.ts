// ZCode 风格模型配置的共享工具：大模型管理/AI对话/向导统一从「有效配置」读取
// （档案未做过「编辑模型配置」时回退推荐默认值，保证配置徽标/思考强度/容量
// 对所有模型可见可编辑）。

export interface EffectiveModelConfig {
  smart_config: boolean;
  context_window: number | null;
  max_output_tokens: number | null;
  input_types: string[];
  capabilities: string[];
  reasoning_levels: string[];
  reasoning_mapping: string;
}

export const DEFAULT_MODEL_CONFIG: EffectiveModelConfig = {
  smart_config: true,
  context_window: 131072,
  max_output_tokens: 32768,
  input_types: ["text", "image"],
  capabilities: ["system_message"],
  reasoning_levels: [],
  reasoning_mapping: "",
};

export function effectiveModelConfig(
  profile?: { model_config_json?: Record<string, unknown> | null } | null,
): EffectiveModelConfig {
  const cfg = (profile?.model_config_json ?? {}) as Record<string, unknown>;
  return { ...DEFAULT_MODEL_CONFIG, ...cfg };
}

export function fmtContextTokens(value: number | null | undefined): string | null {
  if (!value || value <= 0) return null;
  if (value >= 1_000_000) {
    const millions = value / 1_000_000;
    return `${Number.isInteger(millions) ? millions : millions.toFixed(1)}M`;
  }
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return String(value);
}

export const INPUT_TYPE_LABELS: Record<string, string> = {
  image: "视觉",
  video: "视频",
  pdf: "PDF",
};
