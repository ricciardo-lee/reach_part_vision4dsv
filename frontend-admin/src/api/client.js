import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && body.success === false) {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      localStorage.removeItem('admin_token')
      if (!location.pathname.includes('/login')) location.href = '/login'
    }
    ElMessage.error(error?.response?.data?.message || error.message || '网络异常')
    return Promise.reject(error)
  },
)

export default api
