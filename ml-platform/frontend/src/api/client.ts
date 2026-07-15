import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('userId')
      localStorage.removeItem('role')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default apiClient

export function formatApiError(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail;
  if (detail && typeof detail === "object") {
    const code = detail.code ? String(detail.code) : "";
    const message = detail.message ? String(detail.message) : JSON.stringify(detail);
    return code ? `${code}: ${message}` : message;
  }
  return String(detail || error?.message || fallback);
}

export async function apiGet(url: string) {
  const res = await apiClient.get(url)
  return res.data
}

export async function apiPost(url: string, data?: any) {
  const res = await apiClient.post(url, data)
  return res.data
}

export async function apiPut(url: string, data?: any) {
  const res = await apiClient.put(url, data)
  return res.data
}

export async function apiDelete(url: string) {
  const res = await apiClient.delete(url)
  return res.data
}
