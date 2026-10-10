<template>
  <div class="app-shell">
    <header class="topbar">
      <span class="brand">{{ t('common.brand') }}</span>
      <span class="product">{{ t('common.product') }}</span>
      <span class="spacer" />
      <LocaleSwitcher />
      <template v-if="showUser">
        <span class="user">{{ displayName }}</span>
        <button type="button" class="logout" @click="logout">{{ t('common.signOutShort') }}</button>
      </template>
    </header>
    <router-view />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { clearAppAuth } from '@/api/client'
import LocaleSwitcher from '@/components/LocaleSwitcher.vue'
import { useRecognitionStore } from '@/stores/recognition'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useRecognitionStore()
const displayName = ref(localStorage.getItem('app_name') || '')
const showUser = computed(() => route.path !== '/login' && Boolean(displayName.value))

watch(
  () => route.path,
  () => {
    displayName.value = localStorage.getItem('app_name') || ''
  },
)

function logout() {
  clearAppAuth()
  store.reset()
  displayName.value = ''
  router.push('/login')
}
</script>

<style scoped>
.app-shell {
  min-height: 100dvh;
  background: #f3f5f8;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 56px;
  padding: 0 16px;
  background: #0b1b33;
  color: #fff;
}

.brand {
  font-weight: 800;
  letter-spacing: 0.08em;
  font-size: 18px;
}

.product {
  font-size: 14px;
  opacity: 0.86;
}

.spacer {
  flex: 1;
}

.user {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  opacity: 0.9;
}

.logout {
  border: 0;
  background: transparent;
  color: #fff;
  font-size: 13px;
  padding: 6px 0 6px 8px;
}
</style>
