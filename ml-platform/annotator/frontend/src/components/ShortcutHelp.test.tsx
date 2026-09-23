import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ShortcutHelp from './ShortcutHelp'

describe('ShortcutHelp', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<ShortcutHelp open={false} onClose={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('lists every shortcut and closes via the close button', () => {
    const onClose = vi.fn()
    render(<ShortcutHelp open onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: '快捷键帮助' })
    expect(dialog).toBeVisible()
    for (const text of ['1 - 9', 'Enter', 'Space', '← / →', 'Ctrl+Z', 'F1 或 ?', 'Esc']) {
      expect(screen.getByText(text)).toBeVisible()
    }
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
