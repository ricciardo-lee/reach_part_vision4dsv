import axios from 'axios'
import { showToast } from 'vant'
import { getLocale, t } from '@/i18n'

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
  config.headers['Accept-Language'] = getLocale()
  return config
})

api.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && body.success === false) {
      showToast(body.message || t('errors.requestFailed'))
      return Promise.reject(body)
    }
    return body
  },
  (error) => {
    const status = error?.response?.status
    const data = error?.response?.data
    const url = error?.config?.url || ''
    let message = data?.message || error.message || t('errors.network')
    if (status === 401 && !url.includes('/auth/login')) {
      clearAppAuth()
      if (!location.pathname.endsWith('/login')) {
        location.href = '/login'
      }
    }
    if (status === 502 || status === 503 || error.code === 'ERR_NETWORK') {
      message = data?.message || t('errors.backendDown')
    }
    if (data?.details) {
      message = `${message}${t('common.detailsSuffix', { details: data.details })}`
    }
    showToast({ message, position: 'top', duration: 3500 })
    return Promise.reject(error)
  },
)

export default api
