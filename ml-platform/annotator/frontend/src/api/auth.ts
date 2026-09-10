import { request } from './client'

export type Credentials = { username: string; password: string }
export const login = (credentials: Credentials) => request<{ username: string }>('/portal/auth/login', { method: 'POST', body: new URLSearchParams(credentials), headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
export const register = (credentials: Credentials) => request<{ status: string }>('/portal/auth/register', { method: 'POST', body: new URLSearchParams(credentials), headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
export const logout = () => request<void>('/portal/auth/logout', { method: 'POST' })
