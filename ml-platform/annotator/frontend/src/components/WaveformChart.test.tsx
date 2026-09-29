import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import WaveformChart from './WaveformChart'

describe('WaveformChart', () => {
  it('renders one trace per provided channel with min/max readout', () => {
    render(<WaveformChart waveforms={{ current: [10, 30, 20], power: [7, 9] }} />)
    expect(screen.getByRole('img', { name: '电流波形曲线，共 3 个采样点' })).toBeVisible()
    expect(screen.getByRole('img', { name: '功率波形曲线，共 2 个采样点' })).toBeVisible()
    expect(screen.getByText('min 10 / max 30')).toBeVisible()
    expect(screen.getByText('min 7 / max 9')).toBeVisible()
  })

  it('skips channels without data', () => {
    render(<WaveformChart waveforms={{ voltage: [1, 2] }} />)
    expect(screen.queryByRole('img', { name: '电流波形曲线，共 0 个采样点' })).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: '电压波形曲线，共 2 个采样点' })).toBeVisible()
  })

  it('renders nothing when no channel has data', () => {
    const { container } = render(<WaveformChart waveforms={{}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
