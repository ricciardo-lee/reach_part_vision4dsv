<template>
  <div class="page login-page">
    <section class="card">
      <h1>{{ t('common.appName') }}</h1>
      <p class="muted">{{ t('login.subtitle') }}</p>
      <van-field
        v-model="username"
        :label="t('login.username')"
        :placeholder="t('login.usernamePlaceholder')"
        autocomplete="username"
      />
      <van-field
        v-model="password"
        :label="t('login.password')"
        type="password"
        :placeholder="t('login.passwordPlaceholder')"
        autocomplete="current-password"
        @keyup.enter="submit"
      />
      <van-button type="primary" block round :loading="loading" @click="submit">
        {{ t('login.submit') }}
      </van-button>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import api from '@/api/client'

const { t } = useI18n()
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
