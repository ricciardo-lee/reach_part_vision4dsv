import axios from 'axios'
import { showToast } from 'vant'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 180000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('device_token')
  if (token) {
    config.headers['X-Device-Token'] = token
  }
  return config
})

api.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && body.success === false) {
      showToast(body.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (error) => {
    const status = error?.response?.status
    const data = error?.response?.data
    let message = data?.message || error.message || '网络异常'
    if (status === 502 || status === 503 || error.code === 'ERR_NETWORK') {
      message =
        data?.message ||
        '后端服务不可用，请先执行 ./scripts/start_dev.sh 启动 API 与 Celery'
    }
    if (data?.details) {
      message = `${message}（${data.details}）`
    }
    showToast({ message, position: 'top', duration: 3500 })
    return Promise.reject(error)
  },
)

function createUuid() {
  // crypto.randomUUID 仅在安全上下文（HTTPS / localhost）可用；
  // 用局域网 IP 的 http 访问时常见不可用，这里做兼容回退。
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return `fallback-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`
}

function getOrCreateDeviceId() {
  let id = localStorage.getItem('device_id')
  if (!id) {
    id = `web-${createUuid()}`
    localStorage.setItem('device_id', id)
  }
  return id
}

export async function ensureDeviceSession() {
  let token = localStorage.getItem('device_token')
  if (token) return token
  const res = await api.post('/api/v1/public/sessions/device', {
    device_id: getOrCreateDeviceId(),
  })
  token = res.data.session_token
  localStorage.setItem('device_token', token)
  return token
}

export async function resetDeviceSession() {
  localStorage.removeItem('device_token')
  return ensureDeviceSession()
}

export default api
