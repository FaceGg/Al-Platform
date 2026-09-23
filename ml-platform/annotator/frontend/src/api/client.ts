export type RequestOptions = RequestInit & { query?: Record<string, string | number | undefined> }

const VIEWER_STORAGE_KEY = 'portalViewer'
export type PortalViewer = 'annotator' | 'admin'

/** Which identity kind this tab operates as. The backend keeps annotator and
 * admin sessions in separate cookies; this hint tells it which one to use.
 * sessionStorage (per tab, not per origin): logging into the admin review
 * portal in one tab must never flip the annotator portal in another tab. */
export function getPortalViewer(): PortalViewer {
  try {
    return window.sessionStorage.getItem(VIEWER_STORAGE_KEY) === 'admin' ? 'admin' : 'annotator'
  } catch {
    return 'annotator'
  }
}

export function setPortalViewer(viewer: PortalViewer): void {
  try {
    window.sessionStorage.setItem(VIEWER_STORAGE_KEY, viewer)
  } catch { /* storage unavailable (private mode); the viewer stays default */ }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { query, headers, ...init } = options
  const url = new URL(path, window.location.origin)
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value))
  })
  const response = await fetch(url, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Portal-Viewer': getPortalViewer(),
      ...(headers ?? {}),
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    // detail may be a plain string, or {code, message}. Never stringify the
    // object itself or users see "[object Object]".
    const detail = (payload as { detail?: { message?: string; code?: string } | string })?.detail
    const message = typeof detail === 'string'
      ? detail
      : (typeof detail?.message === 'string' && detail.message)
        || (typeof detail?.code === 'string' && detail.code)
        || `Request failed (${response.status})`
    const error = new Error(message) as Error & { response?: { status: number; data: unknown } }
    error.response = { status: response.status, data: payload }
    throw error
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
