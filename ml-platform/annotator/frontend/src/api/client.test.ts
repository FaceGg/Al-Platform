import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getPortalViewer, request, setPortalViewer } from './client'

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('portal api client', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    window.sessionStorage.clear()
    window.localStorage.clear()
  })

  it('keeps the viewer binding per tab (sessionStorage, not localStorage)', () => {
    // An admin login in one tab must not flip the viewer of another tab.
    setPortalViewer('admin')
    expect(getPortalViewer()).toBe('admin')
    expect(window.sessionStorage.getItem('portalViewer')).toBe('admin')
    expect(window.localStorage.getItem('portalViewer')).toBeNull()
  })

  it('defaults to the annotator viewer when nothing is stored', () => {
    expect(getPortalViewer()).toBe('annotator')
  })

  it('sends the X-Portal-Viewer header on every request', async () => {
    const fetchMock = mockFetch(200, {})
    setPortalViewer('admin')
    await request('/portal/tasks')
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({ 'X-Portal-Viewer': 'admin' })
  })

  it('never renders "[object Object]" for structured error details', async () => {
    // detail without a message (e.g. PORTAL_ANNOTATOR_REQUIRED) must surface
    // the code, not a stringified object.
    mockFetch(403, { detail: { code: 'PORTAL_ANNOTATOR_REQUIRED' } })
    let error: Error | undefined
    try { await request('/portal/tasks') } catch (e) { error = e as Error }
    expect(error?.message).toBe('PORTAL_ANNOTATOR_REQUIRED')
  })

  it('prefers the detail message over the code when present', async () => {
    mockFetch(422, { detail: { code: 'ANNOTATION_NOT_READY', message: 'labels changed after confirmation' } })
    let error: Error | undefined
    try { await request('/portal/tasks') } catch (e) { error = e as Error }
    expect(error?.message).toBe('labels changed after confirmation')
  })

  it('falls back to a generic message for string or missing details', async () => {
    mockFetch(400, { detail: 'plain reason' })
    await expect(request('/portal/tasks').catch((e: Error) => e.message)).resolves.toBe('plain reason')
    mockFetch(500, {})
    await expect(request('/portal/tasks').catch((e: Error) => e.message)).resolves.toBe('Request failed (500)')
  })
})
