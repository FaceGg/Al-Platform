import { afterEach, describe, expect, it, vi } from 'vitest'
import { bulkLabels, confirmTask, editForReturn, getTask, listSamples, returnTask, saveLabels } from './tasks'
import { createComment } from './comments'

afterEach(() => vi.unstubAllGlobals())

describe('assignment request scope', () => {
  it('sends the selected assignment on every workspace request', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    vi.stubGlobal('fetch', fetch)
    await getTask('task-1', 'assignment-2')
    await listSamples('task-1', 'sample-5', 'assignment-2')
    await saveLabels('task-1', 'sample-1', { label: 'a' }, 3, 'assignment-2')
    await bulkLabels('task-1', [{ sample_id: 'sample-1', values: { label: 'a' }, base_revision: 3 }], 'assignment-2')
    await confirmTask('task-1', 3, 'scope', 'assignment-2')
    await editForReturn('task-1', 3, 'scope', 'assignment-2')
    await returnTask('task-1', 3, 'scope', 'assignment-2')
    await createComment('task-1', 'note', 'sample-1', 'assignment-2')
    expect(fetch).toHaveBeenCalledTimes(8)
    for (const [url, options] of fetch.mock.calls) {
      expect((url as URL).searchParams.get('assignment_id')).toBe('assignment-2')
      expect(options.credentials).toBe('include')
    }
    expect((fetch.mock.calls[1][0] as URL).searchParams.get('cursor')).toBe('sample-5')
    expect(JSON.parse(fetch.mock.calls[5][1].body)).toEqual({ task_revision: 3, scope_hash: 'scope' })
  })
})
