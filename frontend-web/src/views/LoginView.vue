<template>
  <div class="login-page">
    <section class="panel login-card">
      <h1>{{ t('common.appName') }}</h1>
      <p class="muted">{{ t('login.subtitle') }}</p>
      <form @submit.prevent="submit">
        <label for="username">{{ t('login.username') }}</label>
        <el-input
          id="username"
          v-model="username"
          autocomplete="username"
          :placeholder="t('login.usernamePlaceholder')"
        />
        <label for="password">{{ t('login.password') }}</label>
        <el-input
          id="password"
          v-model="password"
          type="password"
          show-password
          autocomplete="current-password"
          :placeholder="t('login.passwordPlaceholder')"
        />
        <el-button type="primary" native-type="submit" :loading="loading">{{ t('login.submit') }}</el-button>
      </form>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const { t } = useI18n()
const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function submit() {
  if (loading.value) return
  if (!username.value.trim() || !password.value) {
    ElMessage.warning(t('login.needCredentials'))
    return
  }
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
    // The API client already shows the error.
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: grid;
  min-height: calc(100vh - 64px);
  place-items: center;
  padding: 32px 16px;
}

.login-card {
  width: min(420px, 100%);
}

h1 {
  margin: 0;
  font-size: 24px;
}

form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 20px;
}

label {
  margin-top: 8px;
  color: #344054;
  font-size: 13px;
}

.el-button {
  margin-top: 16px;
}
</style>
