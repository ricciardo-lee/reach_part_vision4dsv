<template>
  <div class="page login-page">
    <section class="card">
      <h1>零件识图找货</h1>
      <p class="muted">请使用管理员分配的账号登录</p>
      <van-field v-model="username" label="用户名" placeholder="请输入用户名" autocomplete="username" />
      <van-field
        v-model="password"
        label="密码"
        type="password"
        placeholder="请输入密码"
        autocomplete="current-password"
        @keyup.enter="submit"
      />
      <van-button type="primary" block round :loading="loading" @click="submit">登录</van-button>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/client'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function submit() {
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/public/auth/login', {
      username: username.value.trim(),
      password: password.value,
    })
    localStorage.setItem('app_token', res.data.access_token)
    localStorage.setItem('app_name', res.data.display_name || res.data.username)
    localStorage.setItem('app_username', res.data.username)
    localStorage.removeItem('device_token')
    router.replace('/')
  } catch {
    // The API client already shows the error toast.
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  padding-top: 24px;
}

h1 {
  margin: 0 0 8px;
  font-size: 22px;
}

.van-button {
  margin-top: 16px;
}
</style>
