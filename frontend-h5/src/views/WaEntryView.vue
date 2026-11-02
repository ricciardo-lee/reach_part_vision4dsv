<template>
  <div class="page wa-entry-page">
    <section class="card">
      <van-loading v-if="!failed" vertical>{{ t('waEntry.loading') }}</van-loading>
      <template v-else>
        <p class="muted">{{ t('waEntry.failed') }}</p>
        <p v-if="detail" class="muted detail">{{ detail }}</p>
      </template>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import api from '@/api/client'
import { useRecognitionStore } from '@/stores/recognition'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useRecognitionStore()
const failed = ref(false)
const detail = ref('')

function readLegacyToken() {
  const fromQuery = String(route.query.t || '').trim()
  if (fromQuery) return fromQuery
  const hash = (window.location.hash || '').replace(/^#/, '')
  if (!hash) return ''
  const params = new URLSearchParams(hash.includes('=') ? hash : `t=${hash}`)
  return (params.get('t') || '').trim()
}

async function ensureSharedAuth(sid) {
  // Preferred: backend exchanges sid → shared Lee JWT (no password in the link).
  try {
    const res = await api.post('/api/v1/public/auth/wa-open', { public_id: sid })
    localStorage.setItem('app_token', res.data.access_token)
    localStorage.setItem('app_username', res.data.username || 'Lee')
    localStorage.setItem('app_name', res.data.display_name || res.data.username || 'Lee')
    localStorage.removeItem('device_token')
    return
  } catch (err) {
    // Fallback for older links that still carry ?t= / #t=
    const legacy = readLegacyToken()
    if (!legacy) throw err
    localStorage.setItem('app_token', legacy)
    localStorage.setItem('app_username', 'Lee')
    localStorage.setItem('app_name', 'Lee')
    localStorage.removeItem('device_token')
  }
}

async function bootstrap() {
  const sid = String(route.query.sid || '').trim()
  if (!sid) {
    failed.value = true
    detail.value = 'missing sid'
    return
  }

  try {
    await ensureSharedAuth(sid)
    await store.loadSessionByPublicId(sid)
    await router.replace({ name: 'waMatch' })
  } catch (err) {
    failed.value = true
    const status = err?.response?.status
    const msg = err?.response?.data?.message || err?.message || ''
    detail.value = status ? `HTTP ${status}${msg ? `: ${msg}` : ''}` : String(msg || '')
    showToast(t('waEntry.failed'))
  }
}

onMounted(() => {
  bootstrap()
})
</script>

<style scoped>
.wa-entry-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
.card {
  width: 100%;
  max-width: 420px;
  text-align: center;
  padding: 24px 16px;
}
.detail {
  margin-top: 8px;
  font-size: 12px;
  word-break: break-all;
}
</style>
