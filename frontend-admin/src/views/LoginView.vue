<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2>🛠️ 零件视觉识别管理后台</h2>
      <p class="hint">请使用管理员账号登录</p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item label="👤 用户名">
          <el-input v-model="username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="🔑 密码">
          <el-input v-model="password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-button type="primary" style="width: 100%" :loading="loading" @click="onSubmit">
          🚀 登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const router = useRouter()
const username = ref('admin')
const password = ref('Admin@123456')
const loading = ref(false)

async function onSubmit() {
  loading.value = true
  try {
    const res = await api.post('/api/v1/admin/auth/login', {
      username: username.value,
      password: password.value,
    })
    localStorage.setItem('admin_token', res.data.access_token)
    localStorage.setItem('admin_name', res.data.display_name)
    localStorage.setItem('admin_role', res.data.role)
    ElMessage.success('登录成功 🎉')
    router.push('/')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 16px;
  background: linear-gradient(135deg, #dbeafe, #f8fafc 50%, #e0e7ff);
}
.login-card {
  width: min(420px, 100%);
}
.hint {
  color: #6b7280;
  margin-top: -8px;
}
</style>
