import axios from 'axios'
import { showToast } from 'vant'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 180000,
})

export function clearAppAuth() {
  localStorage.removeItem('app_token')
  localStorage.removeItem('app_name')
  localStorage.removeItem('app_username')
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('app_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
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
    const url = error?.config?.url || ''
    let message = data?.message || error.message || '网络异常'
    if (status === 401 && !url.includes('/auth/login')) {
      clearAppAuth()
      if (!location.pathname.endsWith('/login')) {
        location.href = '/login'
      }
    }
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

export default api
