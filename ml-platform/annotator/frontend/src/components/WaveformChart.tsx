import { useState } from 'react'
import { SampleWaveforms } from '../api/tasks'

// 与管理端 spotWeld WaveformPanel 相同的通道语义与配色
const CHANNELS: Array<{ key: keyof SampleWaveforms; label: string; color: string }> = [
  { key: 'current', label: '电流', color: '#1677ff' },
  { key: 'voltage', label: '电压', color: '#13c2c2' },
  { key: 'resistance', label: '电阻', color: '#722ed1' },
  { key: 'power', label: '功率', color: '#fa8c16' },
]

const WIDTH = 600
const HEIGHT = 104
const PADDING = 6

type Hover = { index: number; x: number; y: number } | null

function ChannelTrace({ label, color, values }: { label: string; color: string; values: number[] }) {
  const [hover, setHover] = useState<Hover>(null)
  let min = values[0]
  let max = values[0]
  for (const value of values) {
    if (value < min) min = value
    if (value > max) max = value
  }
  const span = max - min || 1
  const innerWidth = WIDTH - PADDING * 2
  const innerHeight = HEIGHT - PADDING * 2
  const last = values.length - 1
  const toPoint = (index: number) => {
    const x = PADDING + (index / Math.max(last, 1)) * innerWidth
    const y = PADDING + innerHeight - ((values[index] - min) / span) * innerHeight
    return { x, y }
  }
  const points = values.map((_, index) => {
    const { x, y } = toPoint(index)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const locate = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1)
    const index = Math.round(ratio * last)
    const { x, y } = toPoint(index)
    setHover({ index, x, y })
  }
  return (
    <div className="waveform-channel" data-channel={label}>
      <div className="waveform-channel-head">
        <span className="waveform-channel-name" style={{ color }}>
          {label}
          <span className="waveform-channel-range">min {min} / max {max}</span>
        </span>
        <span className="waveform-channel-readout mono">
          {hover ? `#${hover.index + 1} · ${values[hover.index]}` : `${values.length} 点`}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${label}波形曲线，共 ${values.length} 个采样点`}
        onMouseMove={locate}
        onMouseLeave={() => setHover(null)}
      >
        <polyline points={points} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
        {hover && <circle cx={hover.x} cy={hover.y} r="3" fill={color} />}
      </svg>
    </div>
  )
}

export default function WaveformChart({ waveforms }: { waveforms: SampleWaveforms }) {
  const channels = CHANNELS.flatMap(channel => {
    const values = waveforms[channel.key]
    return Array.isArray(values) && values.length > 0 ? [{ ...channel, values }] : []
  })
  if (channels.length === 0) return null
  return (
    <div className="field-group highlight waveform-group" aria-label="波形数据">
      <h4>波形数据</h4>
      <div className="waveform-channels">
        {channels.map(channel => (
          <ChannelTrace key={channel.key} label={channel.label} color={channel.color} values={channel.values} />
        ))}
      </div>
    </div>
  )
}
