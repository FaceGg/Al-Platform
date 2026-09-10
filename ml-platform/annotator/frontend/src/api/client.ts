export type RequestOptions = RequestInit & { query?: Record<string, string | number | undefined> }

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { query, headers, ...init } = options
  const url = new URL(path, window.location.origin)
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value))
  })
  const response = await fetch(url, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const error = new Error(
      payload?.detail?.message ?? payload?.detail ?? `Request failed (${response.status})`,
    ) as Error & { response?: { status: number; data: unknown } }
    error.response = { status: response.status, data: payload }
    throw error
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
