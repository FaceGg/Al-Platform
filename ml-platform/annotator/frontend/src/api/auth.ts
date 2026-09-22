import { request, setPortalViewer } from './client'

export type Credentials = { username: string; password: string }
export type PortalIdentity = {
  subject_id: string | null
  username: string
  kind?: 'annotator' | 'admin'
  user_id?: string | null
}
export const login = (credentials: Credentials) =>
  request<{ username: string; kind?: string }>('/portal/auth/login', {
    method: 'POST',
    body: new URLSearchParams(credentials),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  }).then((result) => {
    // Annotator and admin sessions live in separate cookies; remember which
    // one this tab just opened so every later request carries the right hint.
    setPortalViewer(result.kind === 'admin' ? 'admin' : 'annotator')
    return result
  })
export const register = (credentials: Credentials) => request<{ status: string }>('/portal/auth/register', { method: 'POST', body: new URLSearchParams(credentials), headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
export const logout = () => request<void>('/portal/auth/logout', { method: 'POST' })
export const me = () => request<PortalIdentity>('/portal/auth/me')
