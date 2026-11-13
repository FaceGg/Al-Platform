import { useEffect, useMemo, useState } from 'react'
import { AutoComplete, Button, Checkbox, Collapse, Dropdown, Form, Input, InputNumber, message, Modal, Select, Space, Switch, Tooltip } from 'antd'
import { ApiOutlined, CloudDownloadOutlined, DeleteOutlined, EditOutlined, MinusCircleOutlined, MoreOutlined, PlusOutlined, QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n'
import AppLayout from '../components/AppLayout'
import PageHeading from '../components/PageHeading'
import {
  LLMProfile,
  LLMProfilePayload,
  createLlmProfile,
  deleteLlmProfile,
  listLlmProfiles,
  testLlmProfile,
  updateLlmProfile,
} from '../api/llmProfiles'
import { formatApiError } from '../api/client'
import apiClient from '../api/client'
import { effectiveModelConfig, fmtContextTokens } from '../utils/llmModelConfig'

const PURPOSE_OPTIONS = ['chat', 'agent', 'embedding']

// 供应商模板目录：选卡预填 Base URL/API 格式与**全部默认模型**（含上下文
// 窗口/最大输出/输入类型/能力/推理等级/映射），用户补 API Key 即用。
// URL 为裸 base（协议路径调用时内部拼接）。默认配置对齐用户提供的
// 《模型默认配置》（2026-11-09）；模型名仍可用「获取」按钮拉上游目录覆盖。
interface ProviderTemplateModel {
  model_id: string
  context_window?: number
  max_output_tokens?: number
  input_types?: string[]
  capabilities?: string[]
  reasoning_levels?: string[]
  reasoning_mapping?: string
}

interface ProviderTemplate {
  name: string
  short: string
  color: string
  api_url: string
  model_id: string
  provider: 'openai_compatible' | 'responses' | 'anthropic'
  group: 'domestic' | 'international'
  key_url?: string
  models?: ProviderTemplateModel[]
}

// 推理参数映射（供应商文档原样；网关递归下降求值器直接支持）
const MAP_DEEPSEEK = `reasoningLevel == "disabled"
  ? {
      "thinking": {
        "type": "disabled"
      }
    }
  : {
      "thinking": {
        "type": "enabled"
      },
      "output_config": {
        "effort": reasoningLevel
      }
    }`
const MAP_ZHIPU = `{
  "thinking": {
    "type": reasoningLevel == "disabled" || reasoningLevel == "none" ? "disabled" : "enabled"
  },
  "enable_thinking": reasoningLevel != "disabled" && reasoningLevel != "none",
  "reasoning_effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel,
  "reasoning": {
    "effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel
  }
}`
const MAP_KIMI_EFFORT = `{
  "output_config": {
    "effort": reasoningLevel
  }
}`
const MAP_KIMI_TOGGLE = `{
  "thinking": {
    "type": reasoningLevel == "enabled" ? "enabled" : "disabled"
  }
}`
const MAP_QWEN = `{
  "thinking": {
    "type": "enabled"
  },
  "output_config": {
    "effort": reasoningLevel
  }
}`
const MAP_DOUBAO = `reasoningLevel == "none"
  ? {
      "thinking": {
        "type": "disabled"
      }
    }
  : {
      "output_config": {
        "effort": reasoningLevel
      }
    }`
const MAP_MINIMAX_FLASH = `{
  "thinking": {
    "type": "adaptive"
  },
  "output_config": {
    "effort": reasoningLevel
  }
}`
const MAP_MINIMAX_M3 = `reasoningLevel == "disabled"
  ? {
      "thinking": {
        "type": "disabled"
      }
    }
  : {
      "thinking": {
        "type": "adaptive"
      },
      "output_config": {
        "effort": reasoningLevel == "enabled" ? "high" : reasoningLevel
      }
    }`
const MAP_SILICON_DS = `reasoningLevel == "disabled" ? {"enable_thinking": false} : {"enable_thinking": true, "reasoning_effort": reasoningLevel}`
const MAP_EFFORT = `{"reasoning_effort": reasoningLevel}`
const MAP_OPENAI = `{
  "reasoning": {
    "effort": reasoningLevel
  }
}`
const MAP_GROK_TOGGLE = `{
  "reasoning": {
    "effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel
  }
}`
const MAP_CLAUDE = `{
  "thinking": {
    "type": "adaptive"
  },
  "output_config": {
    "effort": reasoningLevel
  }
}`

const PROVIDER_TEMPLATES: ProviderTemplate[] = [
  // —— 国内（Base URL 填裸 base，协议路径调用时内部拼接；《模型默认配置》2026-11-09）——
  {
    name: 'DeepSeek', short: 'DS', color: '#4D6BFE', api_url: 'https://api.deepseek.com/anthropic', model_id: 'deepseek-flash', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.deepseek.com/api_keys',
    models: [
      { model_id: 'deepseek-flash', context_window: 1000000, max_output_tokens: 384000, input_types: ['text', 'image'], capabilities: ['web_search', 'system_message'], reasoning_levels: ['disabled', 'low', 'high', 'max'], reasoning_mapping: MAP_DEEPSEEK },
      { model_id: 'deepseek-v4-pro', context_window: 1000000, max_output_tokens: 384000, input_types: ['text'], capabilities: ['web_search', 'system_message'], reasoning_levels: ['disabled', 'low', 'high', 'max'], reasoning_mapping: MAP_DEEPSEEK },
    ],
  },
  {
    name: '智谱 GLM', short: '智', color: '#3859FF', api_url: 'https://open.bigmodel.cn/api/paas/v4', model_id: 'GLM-5.3', provider: 'openai_compatible', group: 'domestic', key_url: 'https://open.bigmodel.cn/usercenter/apikeys',
    models: [
      { model_id: 'GLM-5.3', context_window: 1000000, max_output_tokens: 128000, input_types: ['text'], capabilities: [], reasoning_levels: ['low', 'high', 'max'], reasoning_mapping: MAP_ZHIPU },
      { model_id: 'GLM-5.3-Flash', context_window: 1000000, max_output_tokens: 128000, input_types: ['text', 'image', 'video', 'pdf'], capabilities: [], reasoning_levels: ['low', 'high', 'max'], reasoning_mapping: MAP_ZHIPU },
    ],
  },
  {
    name: 'Kimi（月之暗面）', short: 'K', color: '#171D26', api_url: 'https://api.moonshot.cn/anthropic', model_id: 'kimi-k3.1-pro', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.moonshot.cn/console/api-keys',
    models: [
      { model_id: 'kimi-k3.1-pro', context_window: 1048576, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['low', 'high', 'max'], reasoning_mapping: MAP_KIMI_EFFORT },
      { model_id: 'kimi-k3.1-pro-highspeed', context_window: 1048576, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['low', 'high', 'max'], reasoning_mapping: MAP_KIMI_EFFORT },
      { model_id: 'kimi-k3', context_window: 1048576, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['low', 'high', 'max'], reasoning_mapping: MAP_KIMI_EFFORT },
      { model_id: 'kimi-k2.7-code', context_window: 262144, max_output_tokens: 98304, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['enabled'], reasoning_mapping: MAP_KIMI_TOGGLE },
      { model_id: 'kimi-k2.6', context_window: 262144, max_output_tokens: 98304, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['disabled', 'enabled'], reasoning_mapping: MAP_KIMI_TOGGLE },
    ],
  },
  {
    name: '阿里云百炼', short: '百', color: '#FF6A00', api_url: 'https://dashscope.aliyuncs.com/apps/anthropic', model_id: 'qwen3.8-max', provider: 'anthropic', group: 'domestic', key_url: 'https://bailian.console.aliyun.com/',
    models: [
      { model_id: 'qwen3.8-max', context_window: 1000000, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'xhigh'], reasoning_mapping: MAP_QWEN },
      { model_id: 'qwen3.8-flash', context_window: 1000000, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'xhigh'], reasoning_mapping: MAP_QWEN },
    ],
  },
  {
    name: '火山方舟（豆包）', short: '火', color: '#1664FF', api_url: 'https://ark.cn-beijing.volces.com/api/compatible', model_id: 'doubao-seed-evolving', provider: 'anthropic', group: 'domestic', key_url: 'https://console.volcengine.com/ark/',
    models: [
      { model_id: 'doubao-seed-evolving', context_window: 1024000, max_output_tokens: 256000, input_types: ['text', 'image'], capabilities: [], reasoning_levels: ['none', 'low', 'medium', 'high'], reasoning_mapping: MAP_DOUBAO },
      { model_id: 'doubao-seed-2-1-pro-260915', context_window: 1024000, max_output_tokens: 256000, input_types: ['text', 'image'], capabilities: [], reasoning_levels: ['none', 'low', 'medium', 'high'], reasoning_mapping: MAP_DOUBAO },
      { model_id: 'doubao-seed-2-1-lite-260915', context_window: 1024000, max_output_tokens: 256000, input_types: ['text', 'image'], capabilities: [], reasoning_levels: ['none', 'low', 'medium', 'high'], reasoning_mapping: MAP_DOUBAO },
      { model_id: 'doubao-seed-2-1-turbo-260628', context_window: 256000, max_output_tokens: 256000, input_types: ['text', 'image'], capabilities: [], reasoning_levels: ['none', 'low', 'medium', 'high'], reasoning_mapping: MAP_DOUBAO },
    ],
  },
  {
    name: '硅基流动', short: '硅', color: '#7C3AED', api_url: 'https://api.siliconflow.cn/v1', model_id: 'zai-org/GLM-5.3', provider: 'openai_compatible', group: 'domestic', key_url: 'https://cloud.siliconflow.cn/account/ak',
    models: [
      { model_id: 'zai-org/GLM-5.3', context_window: 1048576, max_output_tokens: 128000, input_types: ['text'], capabilities: [], reasoning_levels: ['enabled'], reasoning_mapping: '{"enable_thinking": true}' },
      { model_id: 'deepseek-ai/DeepSeek-V4-Flash', context_window: 1048576, max_output_tokens: 393216, input_types: ['text'], capabilities: [], reasoning_levels: ['disabled', 'high', 'max'], reasoning_mapping: MAP_SILICON_DS },
      { model_id: 'moonshotai/Kimi-K2.7-Code', context_window: 262144, max_output_tokens: 98304, input_types: ['text', 'image'], capabilities: [], reasoning_levels: ['enabled'], reasoning_mapping: '{"enable_thinking": true}' },
    ],
  },
  {
    name: '腾讯 TokenHub', short: '腾', color: '#0052D9', api_url: 'https://tokenhub.tencentmaas.com/v1', model_id: 'hy3', provider: 'openai_compatible', group: 'domestic', key_url: 'https://cloud.tencent.com/login?s_url=https%3A%2F%2Fconsole.cloud.tencent.com%2Ftokenhub',
    models: [
      { model_id: 'hy3', context_window: 256000, max_output_tokens: 128000, input_types: ['text'], capabilities: [], reasoning_levels: ['none', 'high'], reasoning_mapping: MAP_EFFORT },
      { model_id: 'hy4-preview', context_window: 1024000, max_output_tokens: 64000, input_types: ['text'], capabilities: [], reasoning_levels: ['none', 'high'], reasoning_mapping: MAP_EFFORT },
    ],
  },
  {
    name: 'MiniMax', short: 'M', color: '#F23F5D', api_url: 'https://api.minimaxi.com/anthropic', model_id: 'MiniMax-M3.1-Flash', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.minimaxi.com/',
    models: [
      { model_id: 'MiniMax-M3.1-Flash', context_window: 1000000, max_output_tokens: 524288, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_MINIMAX_FLASH },
      { model_id: 'MiniMax-M3', context_window: 1000000, max_output_tokens: 32000, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['disabled', 'enabled'], reasoning_mapping: MAP_MINIMAX_M3 },
    ],
  },
  {
    name: 'Xiaomi MiMo', short: 'Mi', color: '#FF6900', api_url: 'https://api.xiaomimimo.com/anthropic', model_id: 'mimo-v2.6-pro', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.xiaomimimo.com/token-plan',
    models: [
      { model_id: 'mimo-v2.6-pro', context_window: 1000000, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['disabled', 'enabled'], reasoning_mapping: MAP_KIMI_TOGGLE },
      { model_id: 'mimo-v2.6-flash', context_window: 1000000, max_output_tokens: 131072, input_types: ['text', 'image', 'video'], capabilities: [], reasoning_levels: ['disabled', 'enabled'], reasoning_mapping: MAP_KIMI_TOGGLE },
    ],
  },
  // —— 国外（《模型默认配置》2026-11-09）——
  {
    name: 'OpenAI', short: 'AI', color: '#10A37F', api_url: 'https://api.openai.com/v1', model_id: 'gpt-6-astra', provider: 'responses', group: 'international', key_url: 'https://platform.openai.com/api-keys',
    models: [
      { model_id: 'gpt-6-astra', context_window: 1050000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_OPENAI },
      { model_id: 'gpt-5.6-terra', context_window: 1050000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output'], reasoning_levels: ['none', 'low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_OPENAI },
      { model_id: 'gpt-6.1-sol', context_window: 1050000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_OPENAI },
      { model_id: 'gpt-6-luna', context_window: 1050000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output'], reasoning_levels: ['none', 'low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_OPENAI },
    ],
  },
  { name: 'OpenRouter', short: 'OR', color: '#8B5CF6', api_url: 'https://openrouter.ai/api/v1', model_id: '', provider: 'anthropic', group: 'international', key_url: 'https://openrouter.ai/settings/keys' },
  {
    name: 'xAI（Grok）', short: '𝕏', color: '#111111', api_url: 'https://api.x.ai/v1', model_id: 'grok-build-0.1', provider: 'responses', group: 'international', key_url: 'https://console.x.ai/',
    models: [
      { model_id: 'grok-build-0.1', context_window: 256000, max_output_tokens: 128000, input_types: ['text', 'image'], capabilities: ['structured_output'], reasoning_levels: ['disabled', 'enabled'], reasoning_mapping: MAP_GROK_TOGGLE },
      { model_id: 'grok-4.7', context_window: 500000, max_output_tokens: 128000, input_types: ['text', 'image'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'high', 'xhigh'], reasoning_mapping: MAP_OPENAI },
    ],
  },
  {
    name: 'Anthropic', short: 'Cl', color: '#D97757', api_url: 'https://api.anthropic.com/v1', model_id: 'claude-fable-5-1', provider: 'anthropic', group: 'international', key_url: 'https://console.anthropic.com/settings/keys',
    models: [
      { model_id: 'claude-fable-5-1', context_window: 1000000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output', 'web_search', 'system_message'], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_CLAUDE },
      { model_id: 'claude-opus-5-5', context_window: 1000000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output', 'system_message'], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_CLAUDE },
      { model_id: 'claude-sonnet-5-5', context_window: 1000000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_CLAUDE },
      { model_id: 'claude-haiku-5-5', context_window: 1000000, max_output_tokens: 128000, input_types: ['text', 'image', 'pdf'], capabilities: ['structured_output'], reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'], reasoning_mapping: MAP_CLAUDE },
    ],
  },
]

const hostOf = (url: string): string => {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

// 推理参数映射模板：按配置的推理等级生成三元链（对齐 ZCode 的映射表达式
// 形态：reasoningLevel == "<level>" ? { "thinking": { "type": ... } } : ...）
export function buildReasoningMapping(levels: string[]): string {
  const clean = (levels ?? []).map((level) => String(level).trim()).filter(Boolean)
  if (!clean.length) return ''
  const lines: string[] = []
  clean.forEach((level, index) => {
    // thinking.type 的合法值各供应商不同（deepseek 只认 adaptive/enabled/
    // disabled，anthropic 用 enabled+budget_tokens）——档位名（low/high 等）
    // 不能直接当 type，否则上游 422、对话整体哑掉（实测踩坑）。模板只产
    // 出普适合法形态：关闭档 → disabled，其余档 → enabled；梯度参数按
    // 供应商文档手调。
    const typeValue = level === 'off' || level === 'disabled' ? 'disabled' : 'enabled'
    lines.push(`${index === 0 ? '' : ': '}reasoningLevel == "${level}"`)
    lines.push('  ? {')
    lines.push('      "thinking": {')
    lines.push(`        "type": "${typeValue}"`)
    lines.push('      }')
    lines.push('    }')
  })
  lines.push(': {}')
  return lines.join('\n')
}

// 供应商条目：已知供应商按域名聚合（多个档案 = 该供应商的多个模型）；
// 未匹配模板的按域名归入「自定义供应商」。
interface ProviderEntry {
  key: string
  title: string
  short: string
  color: string
  keyUrl?: string
  template?: ProviderTemplate
  custom: boolean
  api_url: string
  provider: LLMProfile['provider']
  profiles: LLMProfile[]
}

const FORMAT_SHORT: Record<string, string> = {
  openai_compatible: 'Chat',
  responses: 'Responses',
  anthropic: 'Anthropic',
  custom: 'Chat',
}

function dotColor(entry: ProviderEntry): string {
  if (entry.profiles.some((p) => p.is_default)) return '#52c41a'
  if (entry.profiles.some((p) => p.api_key_masked)) return '#faad14'
  return entry.profiles.length ? '#faad14' : '#d9d9d9'
}

export default function LLMGatewayPage() {
  const { t, lang } = useI18n()
  const text = t.llm
  const zh = lang === 'zh'
  const [profiles, setProfiles] = useState<LLMProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [modelOptions, setModelOptions] = useState<string[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)
  const [editing, setEditing] = useState<LLMProfile | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [manualKey, setManualKey] = useState('')
  const [keyDraft, setKeyDraft] = useState('')
  const [form] = Form.useForm()

  const load = () => {
    setLoading(true)
    listLlmProfiles()
      .then(setProfiles)
      .catch((error) => message.error(formatApiError(error, text.loadFailed)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // 供应商分组（左栏）：按 provider_group（供应商组）聚合——同一供应商下的
  // 多个模型共享组；重复添加同名模板生成新组（DeepSeek2 独立条目不并入）。
  // 无组档案（迁移 95 前存量）按域名兜底聚合。
  const entries = useMemo<ProviderEntry[]>(() => {
    const entriesByKey = new Map<string, ProviderEntry>()
    const ordered: ProviderEntry[] = []
    for (const profile of profiles) {
      const tpl = PROVIDER_TEMPLATES.find((item) => hostOf(item.api_url) === hostOf(profile.api_url))
      const groupKey = profile.provider_group
        ? `grp:${profile.provider_group}`
        : (tpl ? `tpl:${tpl.name}` : `host:${hostOf(profile.api_url)}`)
      let entry = entriesByKey.get(groupKey)
      if (!entry) {
        entry = {
          key: groupKey,
          title: profile.name,
          short: (tpl?.short ?? profile.name.slice(0, 2).toUpperCase()),
          color: tpl?.color ?? '#6b7280',
          keyUrl: tpl?.key_url,
          template: tpl,
          custom: !tpl,
          api_url: profile.api_url,
          provider: profile.provider as LLMProfile['provider'],
          profiles: [],
        }
        entriesByKey.set(groupKey, entry)
        ordered.push(entry)
      }
      entry.profiles.push(profile)
    }
    // 分组标题 = 组内默认档案名，否则组内第一个档案名
    for (const entry of ordered) {
      const named = entry.profiles.find((p) => p.is_default) ?? entry.profiles[0]
      if (named) entry.title = named.name
    }
    const groupOf = (entry: ProviderEntry): 0 | 1 | 2 =>
      entry.custom ? 2 : entry.template?.group === 'international' ? 1 : 0
    // 左栏只显示已添加（有档案）的供应商；未添加的模板项经「添加供应商」加入后出现
    const sorted: ProviderEntry[] = []
    for (const group of [0, 1, 2] as const) {
      const members = ordered.filter((entry) => groupOf(entry) === group)
      if (!members.length) continue
      sorted.push(...members)
    }
    return sorted
  }, [profiles])

  const groups = useMemo(() => {
    const groupOf = (entry: ProviderEntry): 0 | 1 | 2 =>
      entry.custom ? 2 : entry.template?.group === 'international' ? 1 : 0
    const list: Array<{ title: string; entries: ProviderEntry[] }> = []
    for (const group of [0, 1, 2] as const) {
      const members = entries.filter((entry) => groupOf(entry) === group)
      if (!members.length) continue
      list.push({
        title: group === 0 ? (zh ? '常用供应商' : 'Providers') : group === 1 ? (zh ? '国际供应商' : 'International') : (zh ? '自定义供应商' : 'Custom'),
        entries: members,
      })
    }
    return list
  }, [entries, zh])

  // 选中 = 手动点选优先；否则跟随含平台默认档案的供应商（异步载入后自动跟随，
  // 此前一次性 effect 守卫导致档案载入后仍停留在空模板项——测试抓到）
  const autoKey = useMemo(() => {
    const withDefault = entries.find((entry) => entry.profiles.some((p) => p.is_default))
    if (withDefault) return withDefault.key
    if (manualKey && entries.some((entry) => entry.key === manualKey)) return manualKey
    return entries[0]?.key ?? ''
  }, [entries, manualKey])
  const activeKey = manualKey && entries.some((entry) => entry.key === manualKey) ? manualKey : autoKey
  const selected = entries.find((entry) => entry.key === activeKey) ?? null
  const primaryProfile = selected?.profiles.find((p) => p.is_default) ?? selected?.profiles[0] ?? null

  // 添加供应商两段式：先选模板卡片（预填 URL/模型），再进创建表单补 Key。
  const openCreate = () => {
    setPickerOpen(true)
  }

  const openCreateWith = (tpl?: ProviderTemplate) => {
    setEditing(null)
    form.resetFields()
    setModelOptions([])
    // 预填名与既有档案去重（重名会触发唯一约束 409）
    let name = tpl?.name ?? ''
    const taken = new Set(profiles.map((p) => p.name))
    if (name && taken.has(name)) {
      let serial = 2
      while (taken.has(`${name} ${serial}`)) serial += 1
      name = `${name} ${serial}`
    }
    form.setFieldsValue({
      name,
      provider: tpl?.provider ?? 'openai_compatible',
      api_url: tpl?.api_url ?? '',
      model_id: tpl?.model_id ?? '',
      deployment: 'cloud',
      timeout_seconds: 60,
      temperature: 0.7,
      max_tokens: 2000,
      purpose_tags: ['chat', 'agent'],
    })
    setPickerOpen(false)
    setModalOpen(true)
  }

  // 添加供应商（模板卡）：自动创建并出现在左栏，提示填写 API Key（不走表单）。
  // 模板带 models 清单时一键创建整组模型档案（首模型主档案，其余同组克隆，
  // 各自带上下文窗口/推理等级/映射等默认参数——对齐《模型默认配置》）。
  const quickAddProvider = async (tpl: ProviderTemplate) => {
    const taken = new Set(profiles.map((p) => p.name))
    let name = tpl.name
    let serial = 2
    while (taken.has(name)) {
      name = `${tpl.name} ${serial}`
      serial += 1
    }
    try {
      const models: ProviderTemplateModel[] = tpl.models?.length
        ? tpl.models
        : [{ model_id: tpl.model_id }]
      const baseName = name
      let groupId: string | undefined
      for (let index = 0; index < models.length; index += 1) {
        const model = models[index]
        const created = await createLlmProfile({
          name: index === 0 ? baseName : `${baseName}·${model.model_id}`,
          provider: tpl.provider,
          api_url: tpl.api_url,
          model_id: model.model_id,
          deployment: 'cloud',
          timeout_seconds: 60,
          temperature: 0.7,
          max_tokens: model.max_output_tokens || 2000,
          purpose_tags: ['chat', 'agent'],
          is_default: profiles.length === 0 && index === 0, // 第一个供应商自动设为平台默认
          provider_group: groupId,
          model_config_json: model.context_window
            ? {
                context_window: model.context_window,
                max_output_tokens: model.max_output_tokens ?? null,
                input_types: model.input_types ?? ['text'],
                capabilities: model.capabilities ?? ['system_message'],
                reasoning_levels: model.reasoning_levels ?? [],
                reasoning_mapping: model.reasoning_mapping ?? '',
              }
            : undefined,
        })
        groupId = groupId || (created as { provider_group?: string }).provider_group
      }
      setPickerOpen(false)
      setManualKey(`tpl:${tpl.name}`) // 新供应商出现在左栏并自动选中
      load()
      message.info(
        models.length > 1
          ? (zh ? `供应商已添加（${models.length} 个模型），请填写 API Key` : `Provider added with ${models.length} models — fill the API Key`)
          : (zh ? '供应商已添加，请在右侧填写 API Key' : 'Provider added — fill the API Key'),
        6,
      )
    } catch (error) {
      message.error(formatApiError(error, zh ? '添加失败' : 'Failed to add'))
    }
  }

  // 「获取」：经后端代理拉上游模型目录（浏览器直连跨域且 Key 不落前端日志）。。
  // 表单里 Base URL 与 API Key 齐备后 blur 自动触发，无需手动点按钮。
  const fetchModels = async () => {
    const api_url = form.getFieldValue('api_url')
    const provider = form.getFieldValue('provider')
    const api_key = form.getFieldValue('api_key')
    if (!api_url) {
      message.warning(zh ? '请先填写 Base URL' : 'Fill the Base URL first')
      return
    }
    if (fetchingModels) return
    setFetchingModels(true)
    try {
      const res = await apiClient.post('/llm-profiles/list-models', {
        api_url,
        api_key: api_key || undefined,
        provider: provider === 'custom' ? 'openai_compatible' : provider,
        profile_id: editing?.id,
      })
      const models: string[] = res.data?.models ?? []
      setModelOptions(models)
      if (models.length === 0) {
        message.info(zh ? '上游未返回模型' : 'No models returned')
      } else if (!models.includes(form.getFieldValue('model_id'))) {
        form.setFieldValue('model_id', undefined)
      }
      message.success(zh ? `已获取 ${models.length} 个模型` : `${models.length} models loaded`)
    } catch (error) {
      message.error(formatApiError(error, zh ? '获取失败' : 'Failed to fetch models'))
    } finally {
      setFetchingModels(false)
    }
  }

  // Base URL / API Key 填写完成（blur）且两者齐备时自动拉取模型目录
  const maybeAutoFetch = (field: 'api_url' | 'api_key') => (event: React.FocusEvent<HTMLInputElement>) => {
    const value = event.target.value?.trim()
    const other = form.getFieldValue(field === 'api_url' ? 'api_key' : 'api_url')
    if (value && other) void fetchModels()
  }

  const openEdit = (profile: LLMProfile) => {
    setEditing(profile)
    form.resetFields()
    setModelOptions(profile.model_id ? [profile.model_id] : [])
    form.setFieldsValue({
      name: profile.name,
      provider: profile.provider,
      api_url: profile.api_url,
      model_id: profile.model_id,
      temperature: profile.temperature,
      max_tokens: profile.max_tokens,
      timeout_seconds: profile.timeout_seconds,
      purpose_tags: profile.purpose_tags,
      deployment: profile.deployment,
      is_default: profile.is_default,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const payload: LLMProfilePayload = {
        name: values.name,
        provider: values.provider,
        api_url: values.api_url,
        model_id: values.model_id,
        temperature: values.temperature ?? null,
        max_tokens: values.max_tokens ?? null,
        timeout_seconds: values.timeout_seconds,
        purpose_tags: values.purpose_tags || [],
        deployment: values.deployment,
        is_default: !!values.is_default,
      }
      if (values.api_key) payload.api_key = values.api_key
      if (editing) {
        await updateLlmProfile(editing.id, payload)
        message.success(text.updateOk)
      } else {
        await createLlmProfile(payload)
        message.success(text.createOk)
      }
      setModalOpen(false)
      load()
    } catch (error) {
      message.error(formatApiError(error, editing ? text.updateFailed : text.createFailed))
    } finally {
      setSaving(false)
    }
  }

  const runProbe = async (profile: LLMProfile) => {
    setTestingId(profile.id)
    try {
      const result = await testLlmProfile(profile.id)
      if (result.ok) {
        message.success(`${text.probeOk} (${result.latency_ms ?? '?'} ms)`)
      } else {
        message.warning(`${text.probeFailed}: ${result.error || result.status_code || ''}`)
      }
    } catch (error) {
      message.error(formatApiError(error, text.probeFailed))
    } finally {
      setTestingId(null)
    }
  }

  const remove = async (profile: LLMProfile) => {
    try {
      await deleteLlmProfile(profile.id)
      message.success(text.deleteOk)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.deleteFailed))
    }
  }

  // 供应商内共享字段的保存：Base URL / API 格式 / API Key 对组内全部档案生效
  const payloadOf = (profile: LLMProfile, patch: Partial<LLMProfilePayload>): LLMProfilePayload => ({
    name: profile.name,
    provider: profile.provider,
    api_url: profile.api_url,
    model_id: profile.model_id,
    temperature: profile.temperature,
    max_tokens: profile.max_tokens,
    timeout_seconds: profile.timeout_seconds,
    purpose_tags: profile.purpose_tags,
    deployment: profile.deployment,
    is_default: profile.is_default,
    enabled: profile.enabled !== false,
    ...patch,
  })

  const saveGroupField = async (patch: Partial<LLMProfilePayload>, okText: string) => {
    if (!selected) return
    try {
      for (const profile of selected.profiles) {
        await updateLlmProfile(profile.id, payloadOf(profile, patch))
      }
      message.success(okText)
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '保存失败' : 'Save failed'))
    }
  }

  const setEnabledProfile = async (profile: LLMProfile, next: boolean) => {
    try {
      await updateLlmProfile(profile.id, payloadOf(profile, { enabled: next }))
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '设置失败' : 'Failed'))
    }
  }

  const toggleProviderEnabled = async (next: boolean) => {
    if (!selected) return
    if (!selected.profiles.length) {
      message.info(zh ? '该供应商暂无模型，先「添加模型」' : 'No models yet — add one first')
      return
    }
    // 供应商开关 = 组内全部模型档案统一启用/停用
    try {
      for (const profile of selected.profiles) {
        await updateLlmProfile(profile.id, payloadOf(profile, { enabled: next }))
      }
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '设置失败' : 'Failed'))
    }
  }

  const removeProvider = async () => {
    if (!selected) return
    for (const profile of selected.profiles) {
      try {
        await deleteLlmProfile(profile.id)
      } catch (error) {
        message.error(formatApiError(error, text.deleteFailed))
        load()
        return
      }
    }
    setManualKey('')
    load()
  }

  // 模型级操作：恢复原样式（测试/编辑/删除独立按钮+开关），见模型行渲染
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [savingRename, setSavingRename] = useState(false)
  // 自动获取的模型目录（供应商 Base URL+Key 可用时拉取；未配置的模型显示为可添加候选行）
  const [catalog, setCatalog] = useState<string[]>([])
  const [catalogLoading, setCatalogLoading] = useState(false)

  const submitRenameProvider = async () => {
    const name = renameValue.trim()
    if (!selected || !name) return
    setSavingRename(true)
    try {
      for (const profile of selected.profiles) {
        await updateLlmProfile(profile.id, payloadOf(profile, { name }))
      }
      message.success(zh ? '已重命名' : 'Renamed')
      setRenaming(false)
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '重命名失败' : 'Rename failed'))
    } finally {
      setSavingRename(false)
    }
  }

  // 自动拉取该供应商的模型目录（有已配置档案即可复用其 Key）
  useEffect(() => {
    if (!selected || !selected.profiles.length) { setCatalog([]); return }
    const primary = selected.profiles.find((p) => p.is_default) ?? selected.profiles[0]
    let cancelled = false
    setCatalogLoading(true)
    apiClient.post('/llm-profiles/list-models', {
      api_url: selected.api_url,
      provider: selected.provider === 'custom' ? 'openai_compatible' : selected.provider,
      profile_id: primary.id,
    }).then((res: { data?: { models?: string[] } }) => {
      if (!cancelled) setCatalog(res.data?.models ?? [])
    }).catch(() => {
      if (!cancelled) setCatalog([])
    }).finally(() => {
      if (!cancelled) setCatalogLoading(false)
    })
    return () => { cancelled = true }
  }, [selected])

  const addCatalogModel = async (modelId: string) => {
    if (!selected?.profiles.length) return
    const source = selected.profiles.find((p) => p.is_default) ?? selected.profiles[0]
    try {
      await apiClient.post(`/llm-profiles/${source.id}/clone`, { model_id: modelId })
      message.success(zh ? `已添加 ${modelId}` : `Added ${modelId}`)
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '添加失败' : 'Failed to add'))
    }
  }

  // —— 模型配置弹窗（添加模型 / 编辑模型配置，对齐 ZCode 模型设置）——
  const [modelCfgOpen, setModelCfgOpen] = useState(false)
  const [modelCfgMode, setModelCfgMode] = useState<'add' | 'edit'>('add')
  const [modelCfgTarget, setModelCfgTarget] = useState<LLMProfile | null>(null)
  const [modelCfgSaving, setModelCfgSaving] = useState(false)
  const [modelForm] = Form.useForm()
  // 等级变化且映射为空（未手写）时自动生成映射模板（竖排逐行编辑共用）
  const syncMappingFromLevels = () => {
    const levels: string[] = (modelForm.getFieldValue('reasoning_levels') ?? [])
      .map((v: unknown) => String(v ?? '').trim())
      .filter(Boolean)
    if (!String(modelForm.getFieldValue('reasoning_mapping') || '').trim()) {
      modelForm.setFieldValue('reasoning_mapping', buildReasoningMapping(levels))
    }
  }

  const openAddModel = () => {
    if (!selected) return
    modelForm.resetFields()
    modelForm.setFieldsValue({
      input_types: ['text'],
      capabilities: [],
      reasoning_levels: [],
      reasoning_mapping: '',
    })
    setModelCfgTarget(null)
    setModelCfgMode('add')
    setModelCfgOpen(true)
  }

  const openModelCfgEdit = (profile: LLMProfile) => {
    modelForm.resetFields()
    // 有效配置：未编辑过配置的模型回退推荐默认值（保存后落库）
    const cfg = effectiveModelConfig(profile)
    modelForm.setFieldsValue({
      model_id: profile.model_id,
      context_window: cfg.context_window ?? undefined,
      max_output_tokens: cfg.max_output_tokens ?? undefined,
      input_types: cfg.input_types?.length ? cfg.input_types : ['text'],
      capabilities: cfg.capabilities ?? [],
      reasoning_levels: cfg.reasoning_levels ?? [],
      reasoning_mapping: String(cfg.reasoning_mapping ?? ''),
    })
    // 已配推理等级但映射为空：自动生成映射模板（不覆盖已保存的手写映射）
    const savedLevels = cfg.reasoning_levels ?? []
    if (savedLevels.length && !String(cfg.reasoning_mapping ?? '').trim()) {
      modelForm.setFieldValue('reasoning_mapping', buildReasoningMapping(savedLevels))
    }
    setModelCfgTarget(profile)
    setModelCfgMode('edit')
    setModelCfgOpen(true)
  }

  const saveModelCfg = async () => {
    const values = await modelForm.validateFields()
    const configJson = {
      context_window: values.context_window ?? null,
      max_output_tokens: values.max_output_tokens ?? null,
      input_types: values.input_types?.length ? values.input_types : ['text'],
      capabilities: values.capabilities ?? [],
      reasoning_levels: values.reasoning_levels ?? [],
      reasoning_mapping: values.reasoning_mapping ?? '',
    }
    setModelCfgSaving(true)
    try {
      // 最大输出 Token 同步到 profile.max_tokens（网关 max_tokens 实际取该值，配置「起作用」）
      const maxTokensPatch = values.max_output_tokens ? { max_tokens: values.max_output_tokens } : {}
      if (modelCfgMode === 'add' && selected?.profiles.length) {
        // 添加：走克隆端点复制供应商 URL/Key（前端无需明文 Key），带模型配置
        const source = selected.profiles.find((p) => p.is_default) ?? selected.profiles[0]
        await apiClient.post(`/llm-profiles/${source.id}/clone`, {
          model_id: values.model_id,
          name: values.model_id,
          model_config_json: configJson,
        })
        if (values.max_output_tokens) {
          const created = await apiClient.get(`/llm-profiles`)
          const added = (created.data || []).find((p: { model_id?: string; name?: string }) => p.model_id === values.model_id && p.name === values.model_id)
          if (added) await updateLlmProfile(added.id, { name: added.name, provider: added.provider, api_url: added.api_url, model_id: added.model_id, deployment: added.deployment, is_default: added.is_default, max_tokens: values.max_output_tokens })
        }
        message.success(zh ? `已添加 ${values.model_id}` : `Added ${values.model_id}`)
      } else if (modelCfgMode === 'edit' && modelCfgTarget) {
        // 编辑：更新 model_id、模型配置与最大输出 Token（网关实际消费）
        await updateLlmProfile(
          modelCfgTarget.id,
          payloadOf(modelCfgTarget, { model_id: values.model_id, model_config_json: configJson, ...maxTokensPatch }),
        )
        message.success(zh ? '模型配置已更新' : 'Model config updated')
      }
      setModelCfgOpen(false)
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '保存失败' : 'Save failed'))
    } finally {
      setModelCfgSaving(false)
    }
  }

  const providerMenu = selected && selected.profiles.length ? {
    items: [
      { key: 'rename', icon: <EditOutlined />, label: zh ? '重命名' : 'Rename' },
      { type: 'divider' as const },
      { key: 'delete', icon: <DeleteOutlined />, label: zh ? '删除供应商' : 'Delete provider', danger: true },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'rename') {
        setRenameValue(selected.title)
        setRenaming(true)
      }
      if (key === 'delete') {
        Modal.confirm({
          title: zh ? '删除供应商？' : 'Delete provider?',
          content: zh
            ? `将删除「${selected.title}」下全部 ${selected.profiles.length} 个模型档案，不可恢复。`
            : `All ${selected.profiles.length} profiles under "${selected.title}" will be removed.`,
          okText: zh ? '删除' : 'Delete',
          okButtonProps: { danger: true },
          cancelText: zh ? '取消' : 'Cancel',
          onOk: () => removeProvider(),
        })
      }
    },
  } : null

  // 供应商头开关显示状态 = 组内存在启用模型（any 语义）：关掉单个模型
  // 不影响供应商开关，只有全部模型关闭才自动显示关；手动切换供应商开关
  // = 组内全部模型统一启停（停用后调用被后端守卫拒绝，整组不可用）。
  // 此前曾错绑 is_default（非默认供应商永远显示关）与 every（关单个模型
  // 头部跟着关——两轮用户实测反馈的根因）。
  const headerSwitchChecked = !!selected?.profiles
    .some((p) => p.enabled !== false)

  return (
    <AppLayout>
      <PageHeading
        section="admin"
        navKey="llm_gateway"
        desc={lang === 'zh'
          ? '集中配置平台可用的大模型供应商：AI 对话、智能体分析/写码/评审与知识库向量化各自选用；密钥只写不读。'
          : 'Central registry of LLM providers for chat, agent analysis/codegen/review and embeddings; keys are write-only.'}
      />

      <div className="v2-panel" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '10px 14px 0' }}>
          <Button icon={<ReloadOutlined spin={loading} />} onClick={load}>
            {text.refresh}
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {zh ? '添加供应商' : 'Add provider'}
          </Button>
        </div>
        <div style={{ display: 'flex', minHeight: 520 }}>
          {/* 左栏：供应商分组列表 */}
          <div style={{ width: 280, flex: '0 0 280px', borderRight: '1px solid var(--v2-line, #e5e7eb)', padding: '12px 8px', overflowY: 'auto', maxHeight: 560 }}>
            {groups.map((group) => (
              <div key={group.title} style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, color: 'var(--v2-dim, #999)', padding: '4px 10px' }}>{group.title}</div>
                {group.entries.map((entry) => {
                  const active = entry.key === activeKey
                  return (
                    <button
                      key={entry.key}
                      type="button"
                      onClick={() => { setManualKey(entry.key); setKeyDraft('') }}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                        padding: '8px 10px', border: 'none', borderRadius: 8, cursor: 'pointer',
                        background: active ? 'var(--v2-hover, rgba(47,155,245,.12))' : 'transparent',
                        color: 'var(--v2-txt, inherit)', textAlign: 'left', fontSize: 13,
                      }}
                    >
                      <span
                        aria-hidden="true"
                        style={{ background: entry.color, borderRadius: 6, width: 24, height: 24, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 11, flex: '0 0 auto' }}
                      >
                        {entry.short}
                      </span>
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.title}</span>
                      <span
                        aria-hidden="true"
                        title={dotColor(entry) === '#52c41a' ? (zh ? '默认在用' : 'default in use') : dotColor(entry) === '#faad14' ? (zh ? '已配置' : 'configured') : (zh ? '未配置' : 'not configured')}
                        style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor(entry), flex: '0 0 auto' }}
                      />
                    </button>
                  )
                })}
              </div>
            ))}
            {!entries.length && !loading ? (
              <div className="v2-empty" style={{ padding: 16 }}>{zh ? '暂无供应商' : 'No providers'}</div>
            ) : null}
          </div>

          {/* 右栏：选中供应商设置 */}
          <div data-testid="provider-detail" style={{ flex: 1, padding: '16px 20px', overflowY: 'auto', maxHeight: 560 }}>
            {!selected ? (
              <div className="v2-empty" style={{ padding: 40 }}>
                {zh ? '从左侧选择供应商，或点击「添加供应商」' : 'Pick a provider or add one'}
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                  <span
                    aria-hidden="true"
                    style={{ background: selected.color, borderRadius: 8, width: 34, height: 34, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 14, flex: '0 0 auto' }}
                  >
                    {selected.short}
                  </span>
                  <b style={{ fontSize: 17 }}>{selected.title}</b>
                  <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Switch
                      checked={headerSwitchChecked}
                      onChange={(next) => void toggleProviderEnabled(next)}
                      disabled={!selected.profiles.length}
                    />
                    {providerMenu ? (
                      <Dropdown menu={providerMenu} trigger={['click']}>
                        <Button type="text" icon={<MoreOutlined />} aria-label={zh ? '更多操作' : 'More'} />
                      </Dropdown>
                    ) : null}
                  </span>
                </div>

                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12.5, marginBottom: 6 }}>Base URL</div>
                  <Input
                    key={`url:${selected.key}:${primaryProfile?.updated_at ?? ''}`}
                    defaultValue={selected.api_url}
                    placeholder="https://api.example.com/v1/chat/completions"
                    disabled={!selected.profiles.length}
                    onBlur={(e) => {
                      const value = e.target.value.trim()
                      if (value && value !== selected.api_url) {
                        void saveGroupField({ api_url: value }, zh ? 'Base URL 已更新' : 'Base URL saved')
                      }
                    }}
                  />
                </div>

                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12.5, marginBottom: 6 }}>{zh ? 'API 格式' : 'API format'}</div>
                  <Select
                    style={{ width: '100%' }}
                    value={selected.provider}
                    disabled={!selected.profiles.length}
                    onChange={(value) => void saveGroupField({ provider: value }, zh ? 'API 格式已更新' : 'API format saved')}
                    options={[
                      { value: 'openai_compatible', label: zh ? 'Chat Completions（/chat/completions）' : 'Chat Completions (/chat/completions)' },
                      { value: 'responses', label: zh ? 'Responses（/responses）' : 'Responses (/responses)' },
                      { value: 'anthropic', label: zh ? 'Anthropic Messages（/v1/messages）' : 'Anthropic Messages (/v1/messages)' },
                    ]}
                  />
                </div>

                <div style={{ marginBottom: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 12.5 }}>{text.colKey}</span>
                    {selected.keyUrl ? (
                      <a href={selected.keyUrl} target="_blank" rel="noreferrer" style={{ marginLeft: 'auto', fontSize: 12.5 }}>
                        {zh ? '获取 API Key' : 'Get API Key'}
                      </a>
                    ) : null}
                  </div>
                  <Input.Password
                    autoComplete="new-password"
                    placeholder={primaryProfile?.api_key_masked || (zh ? '输入 API Key（对供应商下全部模型生效）' : 'API Key (applies to all models)')}
                    value={keyDraft}
                    disabled={!selected.profiles.length}
                    onChange={(e) => setKeyDraft(e.target.value)}
                    onBlur={() => {
                      if (keyDraft.trim()) {
                        void saveGroupField({ api_key: keyDraft.trim() }, zh ? 'API Key 已更新' : 'API Key saved')
                        setKeyDraft('')
                      }
                    }}
                  />
                </div>

                <div>
                  <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 12.5 }}>{zh ? '模型列表' : 'Models'}</span>
                    <Button
                      size="small"
                      icon={<PlusOutlined />}
                      style={{ marginLeft: 'auto' }}
                      onClick={() => openAddModel()}
                    >
                      {zh ? '添加模型' : 'Add model'}
                    </Button>
                  </div>
                  {selected.profiles.length === 0 ? (
                    <div className="v2-empty" style={{ padding: 18 }}>
                      {zh ? '暂无模型 —— 点「添加模型」，Base URL 与格式将自动带入' : 'No models yet — add one; URL and format are prefilled'}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {selected.profiles.map((profile) => (
                        <div
                          key={profile.id}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 10,
                            border: '1px solid var(--v2-line, #e5e7eb)', borderRadius: 8, padding: '8px 12px',
                          }}
                        >
                          <span className="tt" style={{ fontSize: 13 }}>{profile.model_id}</span>
                          {/* ZCode 式配置徽标：上下文容量 + 输入类型（无配置回退推荐默认值） */}
                          {(() => {
                            const cfg = effectiveModelConfig(profile)
                            const contextBadge = fmtContextTokens(cfg.context_window ?? null)
                            const typeLabels: Record<string, string> = { image: zh ? '视觉' : 'vision', video: zh ? '视频' : 'video', pdf: 'PDF' }
                            const extraTypes = (cfg.input_types ?? []).filter((t) => t !== 'text').map((t) => typeLabels[t] ?? t)
                            return (
                              <>
                                {contextBadge ? <span className="v2-badge v2-bgray">{contextBadge}</span> : null}
                                {extraTypes.map((label) => <span key={label} className="v2-badge v2-bgray">{label}</span>)}
                              </>
                            )
                          })()}
                          {/* 档案名/格式/默认徽标/用途标签已去掉：模型行只保留模型 ID + 配置徽标（上下文/输入类型） */}
                          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
                            <Button
                              type="text" size="small"
                              icon={<ApiOutlined spin={testingId === profile.id} />}
                              title={text.probe} aria-label={text.probe}
                              onClick={() => void runProbe(profile)}
                            />
                            <Button
                              type="text" size="small"
                              icon={<EditOutlined />}
                              title={text.edit} aria-label={text.edit}
                              onClick={() => openModelCfgEdit(profile)}
                            />
                            <Switch
                              size="small"
                              checked={profile.enabled !== false}
                              onChange={(next) => void setEnabledProfile(profile, next)}
                            />
                          </span>
                        </div>
                      ))}
                      {/* 自动获取的模型目录：未配置的模型显示为候选行，一键克隆添加 */}
                      {(catalogLoading || catalog.length) && selected.profiles.length ? (
                        <div style={{ marginTop: 2 }}>
                          {catalog.filter((modelId) => !selected.profiles.some((p) => p.model_id === modelId)).map((modelId) => (
                            <div
                              key={modelId}
                              style={{
                                display: 'flex', alignItems: 'center', gap: 10,
                                border: '1px dashed var(--v2-line, #e5e7eb)', borderRadius: 8,
                                padding: '6px 12px', marginBottom: 6, color: 'var(--v2-sub, #999)',
                              }}
                            >
                              <span className="tt">{modelId}</span>
                              <Button
                                type="link" size="small" icon={<PlusOutlined />}
                                style={{ marginLeft: 'auto' }}
                                onClick={() => void addCatalogModel(modelId)}
                              >
                                {zh ? '添加' : 'Add'}
                              </Button>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <Modal
        title={zh ? '选择供应商模板' : 'Choose provider'}
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        footer={null}
        width={720}
        destroyOnClose
      >
        <div data-testid="provider-picker">
        <div style={{ color: 'var(--v2-dim, #999)', fontSize: 12.5, marginBottom: 12 }}>
          {zh ? '选卡自动填入 Base URL、默认模型与 API 格式，保存时补 API Key 即可；模型名可在表单里点「获取」从上游拉取。' : 'Pick a card to prefill the base URL, model and API format; add your API key on save. Use "Fetch" in the form to list upstream models.'}
        </div>
        {([
          [zh ? '国内服务商' : 'Domestic', 'domestic'],
          [zh ? '国际服务商' : 'International', 'international'],
        ] as const).map(([groupLabel, groupKey]) => (
          <div key={groupKey} style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, color: 'var(--v2-dim, #999)', margin: '4px 0 8px' }}>{groupLabel}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {PROVIDER_TEMPLATES.filter((tpl) => tpl.group === groupKey).map((tpl) => (
                <button
                  key={tpl.name}
                  type="button"
                  onClick={() => void quickAddProvider(tpl)}
                  className="llm-tpl-card"
                >
                  <span
                    aria-hidden="true"
                    style={{ background: tpl.color, borderRadius: 8, width: 34, height: 34, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 14, flex: '0 0 auto' }}
                  >
                    {tpl.short}
                  </span>
                  <span style={{ flex: 1, textAlign: 'left' }}>{tpl.name}</span>
                  <span style={{ color: 'var(--v2-dim, #999)' }}>›</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        <div style={{ fontSize: 12, color: 'var(--v2-dim, #999)', margin: '4px 0 8px' }}>{zh ? '自定义' : 'Custom'}</div>
        <button type="button" className="llm-tpl-card" onClick={() => openCreateWith()} style={{ width: '100%' }}>
          <span aria-hidden="true" style={{ borderRadius: 8, width: 34, height: 34, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', border: '1px dashed var(--v2-line, #ccc)', color: 'var(--v2-dim, #999)', fontSize: 18, flex: '0 0 auto' }}>+</span>
          <span style={{ flex: 1, textAlign: 'left' }}>{zh ? '创建自定义供应商' : 'Create custom provider'}</span>
          <span style={{ color: 'var(--v2-dim, #999)' }}>›</span>
        </button>
        </div>
      </Modal>
      <Modal
        title={editing ? text.editTitle : text.createTitle}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={zh ? '保存' : 'Save'}
        cancelText={zh ? '取消' : 'Cancel'}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={text.colName} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="provider" label={zh ? 'API 格式' : 'API format'} rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'openai_compatible', label: zh ? 'Chat Completions（/chat/completions）' : 'Chat Completions (/chat/completions)' },
                { value: 'responses', label: zh ? 'Responses（/responses）' : 'Responses (/responses)' },
                { value: 'anthropic', label: zh ? 'Anthropic Messages（/v1/messages）' : 'Anthropic Messages (/v1/messages)' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="api_url"
            label="Base URL"
            rules={[{ required: true }, { pattern: /^https:\/\//, message: text.httpsOnly }]}
          >
            <Input placeholder="https://api.example.com/v1" onBlur={maybeAutoFetch('api_url')} />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={text.colKey}
            extra={editing ? text.keyKeepBlank : text.keyWriteOnly}
          >
            <Input.Password autoComplete="new-password" placeholder={zh ? '输入 API Key' : 'API Key'} onBlur={maybeAutoFetch('api_key')} />
          </Form.Item>
          <Form.Item label={zh ? '模型' : 'Model'} required style={{ marginBottom: 12 }}>
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="model_id" noStyle rules={[{ required: true, message: zh ? '请选择或输入模型' : 'Pick or type a model' }]}>
                <AutoComplete
                  options={modelOptions.map((m) => ({ value: m }))}
                  placeholder={zh ? '点击「获取」拉取，或直接输入模型名' : 'Fetch or type a model id'}
                  filterOption={(input, option) => String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())}
                />
              </Form.Item>
              <Button icon={<CloudDownloadOutlined />} onClick={fetchModels} loading={fetchingModels}>
                {zh ? '获取' : 'Fetch'}
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item name="deployment" label={text.colDeployment} rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'cloud', label: text.deploymentCloud },
                { value: 'private', label: text.deploymentPrivate },
              ]}
            />
          </Form.Item>
          {/* 高级配置默认收起：参数项低频，参考对话式模型配置的分层结构 */}
          <Collapse
            ghost
            items={[{
              key: 'advanced',
              label: zh ? '高级配置' : 'Advanced',
              children: (
                <>
                  <Form.Item name="purpose_tags" label={text.colPurposes}>
                    <Select mode="multiple" options={PURPOSE_OPTIONS.map((value) => ({ value, label: value }))} />
                  </Form.Item>
                  <Space size="large" wrap>
                    <Form.Item name="timeout_seconds" label={text.colTimeout}>
                      <InputNumber min={1} max={600} />
                    </Form.Item>
                    <Form.Item name="temperature" label="temperature">
                      <InputNumber min={0} max={2} step={0.1} />
                    </Form.Item>
                    <Form.Item name="max_tokens" label="max_tokens">
                      <InputNumber min={1} />
                    </Form.Item>
                  </Space>
                  <Form.Item name="is_default" label={text.setDefault} valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </Form>
      </Modal>
      <Modal
        title={zh ? '重命名供应商' : 'Rename provider'}
        open={renaming}
        onOk={submitRenameProvider}
        onCancel={() => setRenaming(false)}
        confirmLoading={savingRename}
        okText={zh ? '保存' : 'Save'}
        cancelText={zh ? '取消' : 'Cancel'}
        width={420}
        destroyOnClose
      >
        <Input
          value={renameValue}
          placeholder={zh ? '供应商名称（供应商下全部模型档案统一改名）' : 'Provider name (applies to all profiles)'}
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={submitRenameProvider}
        />
      </Modal>
      <Modal
        title={modelCfgMode === 'add' ? (zh ? '添加模型' : 'Add model') : (zh ? '编辑模型配置' : 'Edit model config')}
        open={modelCfgOpen}
        onCancel={() => setModelCfgOpen(false)}
        width={680}
        destroyOnClose
        footer={(
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Button type="link" onClick={() => modelForm.resetFields()}>{zh ? '重置表单' : 'Reset form'}</Button>
            <Space>
              <Button onClick={() => setModelCfgOpen(false)}>{zh ? '取消' : 'Cancel'}</Button>
              <Button type="primary" loading={modelCfgSaving} onClick={() => void saveModelCfg()}>{zh ? '保存' : 'Save'}</Button>
            </Space>
          </div>
        )}
      >
        <Form form={modelForm} layout="vertical">
          <Form.Item name="model_id" label={zh ? '模型 ID' : 'Model ID'} rules={[{ required: true, message: zh ? '请输入模型 ID' : 'Model ID required' }]}>
            <Input placeholder="deepseek-chat" />
          </Form.Item>
          <Form.Item name="context_window" label={zh ? '上下文窗口' : 'Context window'} tooltip={zh ? '模型支持的上下文 Token 上限' : 'Max context tokens'}>
            <InputNumber min={1} style={{ width: '100%' }} placeholder="1000000" />
          </Form.Item>
          <Form.Item name="max_output_tokens" label={zh ? '最大输出 Token' : 'Max output tokens'}>
            <InputNumber min={1} style={{ width: '100%' }} placeholder="384000" />
          </Form.Item>
          <Collapse
            ghost
            items={[{
              key: 'advanced',
              label: zh ? '高级配置' : 'Advanced',
              children: (
                <>
                  <Form.Item label={<span>{zh ? '输入类型' : 'Input types'} <Tooltip title={zh ? '模型支持的输入模态；文本固定开启' : 'Text is always on'}><QuestionCircleOutlined style={{ color: 'var(--v2-dim, #999)' }} /></Tooltip></span>} name="input_types">
                    <Checkbox.Group
                      options={[
                        { label: zh ? '文本' : 'Text', value: 'text', disabled: true },
                        { label: zh ? '图片' : 'Image', value: 'image' },
                        { label: zh ? '视频' : 'Video', value: 'video' },
                        { label: 'PDF', value: 'pdf' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label={zh ? '模型能力' : 'Capabilities'} name="capabilities">
                    <Checkbox.Group
                      options={[
                        { label: zh ? '结构化输出' : 'Structured output', value: 'structured_output' },
                        { label: zh ? '原生联网搜索' : 'Web search', value: 'web_search' },
                        { label: zh ? '对话中系统消息' : 'System message', value: 'system_message' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item
                    label={(
                      <span>
                        {zh ? '推理等级（从低到高）' : 'Reasoning levels (low to high)'}
                        <Tooltip title={zh ? '每个等级单独一行，按从低到高排序；等级变化且映射为空时自动生成映射模板' : 'One level per row, ascending; mapping template auto-generated when empty'}>
                          <QuestionCircleOutlined style={{ color: 'var(--v2-dim, #999)' }} />
                        </Tooltip>
                      </span>
                    )}
                  >
                    {/* ZCode 式竖排：每个等级单独一行（输入框 + 行尾删除），添加按钮在底部 */}
                    <Form.List name="reasoning_levels">
                      {(fields, { add, remove }) => (
                        <div style={{ width: 200, display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {fields.map((field) => (
                            <div key={field.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <Form.Item name={field.name} noStyle>
                                <Input
                                  placeholder={zh ? '等级名，如 low' : 'level, e.g. low'}
                                  onChange={() => syncMappingFromLevels()}
                                />
                              </Form.Item>
                              <Button
                                type="text"
                                size="small"
                                icon={<MinusCircleOutlined style={{ color: 'var(--v2-dim, #999)', fontSize: 14 }} />}
                                onClick={() => { remove(field.name); setTimeout(syncMappingFromLevels, 0) }}
                                aria-label={zh ? '删除等级' : 'Remove level'}
                                style={{ width: 24, height: 24, minWidth: 24, flex: '0 0 auto' }}
                              />
                            </div>
                          ))}
                          <Button
                            type="dashed"
                            icon={<PlusOutlined />}
                            onClick={() => add()}
                            style={{ width: '100%' }}
                          >
                            {zh ? '添加等级' : 'Add level'}
                          </Button>
                        </div>
                      )}
                    </Form.List>
                  </Form.Item>
                  <Form.Item label={<span>{zh ? '推理参数映射' : 'Reasoning param mapping'} <Tooltip title={zh ? '推理等级到请求参数的映射表达式（三元链）；可手写，等级变化且为空时自动生成模板' : 'Ternary chain mapping levels to request params'}><QuestionCircleOutlined style={{ color: 'var(--v2-dim, #999)' }} /></Tooltip></span>} name="reasoning_mapping">
                    <Input.TextArea
                      rows={9}
                      className="codebox"
                      style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 12.5 }}
                      placeholder={'reasoningLevel == "disabled"\n  ? {\n      "thinking": {\n        "type": "disabled"\n      }\n    }\n  : {}'}
                    />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </Form>
      </Modal>
    </AppLayout>
  )
}
