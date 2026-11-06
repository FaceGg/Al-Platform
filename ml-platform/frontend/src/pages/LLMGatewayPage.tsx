import { useEffect, useMemo, useState } from 'react'
import { AutoComplete, Button, Collapse, Dropdown, Form, Input, InputNumber, message, Modal, Select, Space, Switch } from 'antd'
import { ApiOutlined, CloudDownloadOutlined, DeleteOutlined, EditOutlined, MoreOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
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

const PURPOSE_OPTIONS = ['chat', 'agent', 'embedding']

// 供应商模板目录：选卡预填 Base URL/默认模型/API 格式，用户补 API Key 即可。
// URL 为「base + 协议后缀」的完整端点：anthropic → /v1/messages（base 已含
// /v1 则拼 /messages）、chat completions → /chat/completions、responses →
// /responses。默认配置对齐用户提供的官方文档（2026-11）；模型名以「获取」
// 按钮拉上游目录为准，模板里的默认值仅供起步。
interface ProviderTemplate {
  name: string
  short: string
  color: string
  api_url: string
  model_id: string
  provider: 'openai_compatible' | 'responses' | 'anthropic'
  group: 'domestic' | 'international'
  key_url?: string
}

const PROVIDER_TEMPLATES: ProviderTemplate[] = [
  // —— 国内（Base URL 填裸 base，协议路径调用时内部拼接；文档默认配置）——
  { name: 'DeepSeek', short: 'DS', color: '#4D6BFE', api_url: 'https://api.deepseek.com/anthropic', model_id: 'deepseek-chat', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.deepseek.com/api_keys' },
  { name: '智谱 GLM', short: '智', color: '#3859FF', api_url: 'https://open.bigmodel.cn/api/paas/v4', model_id: 'glm-4.6', provider: 'openai_compatible', group: 'domestic', key_url: 'https://open.bigmodel.cn/usercenter/apikeys' },
  { name: 'Kimi（月之暗面）', short: 'K', color: '#171D26', api_url: 'https://api.moonshot.cn/anthropic', model_id: 'kimi-k2-0905-preview', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.moonshot.cn/console/api-keys' },
  { name: '阿里云百炼', short: '百', color: '#FF6A00', api_url: 'https://dashscope.aliyuncs.com/apps/anthropic', model_id: '', provider: 'anthropic', group: 'domestic', key_url: 'https://bailian.console.aliyun.com/' },
  { name: '火山方舟（豆包）', short: '火', color: '#1664FF', api_url: 'https://ark.cn-beijing.volces.com/api/compatible', model_id: '', provider: 'anthropic', group: 'domestic', key_url: 'https://console.volcengine.com/ark/' },
  { name: '硅基流动', short: '硅', color: '#7C3AED', api_url: 'https://api.siliconflow.cn/v1', model_id: 'deepseek-ai/DeepSeek-V3', provider: 'openai_compatible', group: 'domestic', key_url: 'https://cloud.siliconflow.cn/account/ak' },
  { name: '腾讯 TokenHub', short: '腾', color: '#0052D9', api_url: 'https://tokenhub.tencentmaas.com/v1', model_id: '', provider: 'openai_compatible', group: 'domestic', key_url: 'https://cloud.tencent.com/login?s_url=https%3A%2F%2Fconsole.cloud.tencent.com%2Ftokenhub' },
  { name: 'MiniMax', short: 'M', color: '#F23F5D', api_url: 'https://api.minimaxi.com/anthropic', model_id: 'MiniMax-M2', provider: 'anthropic', group: 'domestic', key_url: 'https://platform.minimaxi.com/' },
  { name: 'Xiaomi MiMo', short: 'Mi', color: '#FF6900', api_url: 'https://api.xiaomimimo.com/v1', model_id: '', provider: 'openai_compatible', group: 'domestic', key_url: 'https://platform.xiaomimimo.com/token-plan' },
  // —— 国外（文档默认配置）——
  { name: 'OpenAI', short: 'AI', color: '#10A37F', api_url: 'https://api.openai.com/v1', model_id: 'gpt-4o', provider: 'responses', group: 'international', key_url: 'https://platform.openai.com/api-keys' },
  { name: 'OpenRouter', short: 'OR', color: '#8B5CF6', api_url: 'https://openrouter.ai/api/v1', model_id: '', provider: 'anthropic', group: 'international', key_url: 'https://openrouter.ai/settings/keys' },
  { name: 'xAI（Grok）', short: '𝕏', color: '#111111', api_url: 'https://api.x.ai/v1', model_id: 'grok-4', provider: 'responses', group: 'international', key_url: 'https://console.x.ai/' },
  { name: 'Anthropic', short: 'Cl', color: '#D97757', api_url: 'https://api.anthropic.com/v1', model_id: 'claude-sonnet-4-5', provider: 'anthropic', group: 'international', key_url: 'https://console.anthropic.com/settings/keys' },
]

const hostOf = (url: string): string => {
  try {
    return new URL(url).host
  } catch {
    return url
  }
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

  // 供应商分组（左栏）：已知模板按域名聚合，未匹配的按域名归入自定义
  const entries = useMemo<ProviderEntry[]>(() => {
    const usedHosts = new Set<string>()
    const known: ProviderEntry[] = PROVIDER_TEMPLATES.map((tpl) => {
      const host = hostOf(tpl.api_url)
      usedHosts.add(host)
      const own = profiles.filter((p) => hostOf(p.api_url) === host)
      const api_url = own[0]?.api_url ?? tpl.api_url
      const provider = (own[0]?.provider ?? tpl.provider) as LLMProfile['provider']
      return {
        key: `tpl:${tpl.name}`,
        title: tpl.name,
        short: tpl.short,
        color: tpl.color,
        keyUrl: tpl.key_url,
        template: tpl,
        custom: false,
        api_url,
        provider,
        profiles: own,
      }
    })
    const customMap = new Map<string, ProviderEntry>()
    for (const profile of profiles) {
      const host = hostOf(profile.api_url)
      if (usedHosts.has(host)) continue
      let entry = customMap.get(host)
      if (!entry) {
        entry = {
          key: `custom:${host}`,
          title: host,
          short: (profile.name || host).slice(0, 2).toUpperCase(),
          color: '#6b7280',
          custom: true,
          api_url: profile.api_url,
          provider: profile.provider as LLMProfile['provider'],
          profiles: [],
        }
        customMap.set(host, entry)
      }
      entry.profiles.push(profile)
    }
    const groupOf = (entry: ProviderEntry): 0 | 1 | 2 =>
      entry.custom ? 2 : entry.template?.group === 'international' ? 1 : 0
    const sorted: ProviderEntry[] = []
    for (const group of [0, 1, 2] as const) {
      const members = [...known, ...customMap.values()].filter((entry) => groupOf(entry) === group)
      if (!members.length) continue
      sorted.push(...members)
    }
    return sorted
  }, [profiles, zh])

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
    form.setFieldsValue({
      name: tpl?.name ?? '',
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

  // 「获取」：经后端代理拉上游模型目录（浏览器直连跨域且 Key 不落前端日志）。
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

  const setDefaultProfile = async (profile: LLMProfile, next: boolean) => {
    try {
      await updateLlmProfile(profile.id, payloadOf(profile, { is_default: next }))
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '设置失败' : 'Failed'))
    }
  }

  const toggleProviderEnabled = async (next: boolean) => {
    if (!selected) return
    const target = selected.profiles.find((p) => p.is_default) ?? selected.profiles[0]
    if (!target) {
      message.info(zh ? '该供应商暂无模型，先「添加模型」' : 'No models yet — add one first')
      return
    }
    await setDefaultProfile(target, next)
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

  // 模型级操作（…菜单）：重命名（改档案名）/ 删除（删该模型档案）
  const [renaming, setRenaming] = useState<LLMProfile | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [savingRename, setSavingRename] = useState(false)

  const submitRename = async () => {
    const name = renameValue.trim()
    if (!renaming || !name) return
    setSavingRename(true)
    try {
      await updateLlmProfile(renaming.id, payloadOf(renaming, { name }))
      message.success(zh ? '已重命名' : 'Renamed')
      setRenaming(null)
      load()
    } catch (error) {
      message.error(formatApiError(error, zh ? '重命名失败' : 'Rename failed'))
    } finally {
      setSavingRename(false)
    }
  }

  const removeModel = async (profile: LLMProfile) => {
    try {
      await deleteLlmProfile(profile.id)
      message.success(text.deleteOk)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.deleteFailed))
    }
  }

  const modelMenu = (profile: LLMProfile) => ({
    items: [
      {
        key: 'rename',
        icon: <EditOutlined />,
        label: zh ? '重命名' : 'Rename',
      },
      {
        key: 'delete',
        icon: <DeleteOutlined />,
        label: zh ? '删除' : 'Delete',
        danger: true,
      },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'rename') {
        setRenameValue(profile.name)
        setRenaming(profile)
      }
      if (key === 'delete') {
        Modal.confirm({
          title: zh ? '删除模型？' : 'Delete model?',
          content: zh
            ? `将删除档案「${profile.name}」（${profile.model_id}），不可恢复。`
            : `Profile "${profile.name}" (${profile.model_id}) will be removed.`,
          okText: zh ? '删除' : 'Delete',
          okButtonProps: { danger: true },
          cancelText: zh ? '取消' : 'Cancel',
          onOk: () => removeModel(profile),
        })
      }
    },
  })

  const providerMenu = selected && selected.profiles.length ? {
    items: [
      primaryProfile ? { key: 'probe', icon: <ApiOutlined />, label: zh ? '测试连接' : 'Test connection' } : null,
      { key: 'default', icon: <PlusOutlined />, label: zh ? '设为平台默认' : 'Set as platform default' },
      { type: 'divider' as const },
      { key: 'delete', icon: <DeleteOutlined />, label: zh ? '删除供应商' : 'Delete provider', danger: true },
    ].filter(Boolean),
    onClick: ({ key }: { key: string }) => {
      if (key === 'probe' && primaryProfile) void runProbe(primaryProfile)
      if (key === 'default' && primaryProfile) void setDefaultProfile(primaryProfile, true)
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

  const headerSwitchChecked = !!selected?.profiles.some((p) => p.is_default)

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
          <div style={{ flex: 1, padding: '16px 20px', overflowY: 'auto', maxHeight: 560 }}>
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
                      onClick={() => openCreateWith(selected.template)}
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
                          <span style={{ color: 'var(--v2-sub, #999)', fontSize: 12 }}>{profile.name}</span>
                          <span className="v2-badge v2-bgray">{FORMAT_SHORT[profile.provider] ?? profile.provider}</span>
                          {(profile.purpose_tags || []).map((tag) => (
                            <span key={tag} className="v2-badge v2-bgray">{tag}</span>
                          ))}
                          {profile.is_default ? <span className="v2-badge v2-bb">{text.defaultTag}</span> : null}
                          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
                            <Button
                              type="text" size="small"
                              icon={<ApiOutlined spin={testingId === profile.id} />}
                              title={text.probe} aria-label={text.probe}
                              onClick={() => void runProbe(profile)}
                            />
                            <Switch
                              size="small"
                              checked={profile.is_default}
                              onChange={(next) => void setDefaultProfile(profile, next)}
                            />
                            <Dropdown menu={modelMenu(profile)} trigger={['click']}>
                              <Button type="text" size="small" icon={<MoreOutlined />} aria-label={zh ? '更多操作' : 'More'} />
                            </Dropdown>
                          </span>
                        </div>
                      ))}
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
                  onClick={() => openCreateWith(tpl)}
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
        title={zh ? '重命名模型档案' : 'Rename profile'}
        open={renaming !== null}
        onOk={submitRename}
        onCancel={() => setRenaming(null)}
        confirmLoading={savingRename}
        okText={zh ? '保存' : 'Save'}
        cancelText={zh ? '取消' : 'Cancel'}
        width={420}
        destroyOnClose
      >
        <Input
          value={renameValue}
          placeholder={zh ? '档案名称' : 'Profile name'}
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={submitRename}
        />
      </Modal>
    </AppLayout>
  )
}
