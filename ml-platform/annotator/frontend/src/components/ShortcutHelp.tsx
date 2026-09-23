const shortcuts: Array<{ keys: string; action: string }> = [
  { keys: '1 - 9', action: '勾选/取消对应顺序的标签选项（标签框内输入数字时除外）' },
  { keys: 'Enter', action: '保存并进入下一样本（标签框内同样有效）' },
  { keys: 'Space', action: '跳过当前样本（仅本地跳过，不保存）' },
  { keys: '← / →', action: '上一个 / 下一个样本（不保存）' },
  { keys: 'Ctrl+Z', action: '撤销最近一次标签修改（最多 20 步）' },
  { keys: 'F1 或 ?', action: '打开快捷键帮助' },
  { keys: 'Esc', action: '关闭帮助浮层；光标在标签框内时移出标签框' },
]

export default function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return (
    <div className="dialog" role="dialog" aria-label="快捷键帮助">
      <section>
        <h2>快捷键帮助</h2>
        <table className="shortcut-table">
          <tbody>
            {shortcuts.map(item => (
              <tr key={item.keys}>
                <th scope="row"><kbd>{item.keys}</kbd></th>
                <td>{item.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="dialog-actions">
          <button className="primary" type="button" onClick={onClose}>关闭</button>
        </div>
      </section>
    </div>
  )
}
