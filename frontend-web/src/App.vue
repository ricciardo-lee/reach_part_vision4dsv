<template>
  <div class="app-shell">
    <a class="skip-link" href="#main">跳到主要内容</a>
    <header class="topbar">
      <div class="brand-block">
        <span class="brand">REACH</span>
        <span class="product">Part Finder</span>
      </div>
      <span class="spacer" />
      <template v-if="showUser">
        <span class="user" :title="displayName">{{ displayName }}</span>
        <button type="button" class="logout" @click="logout">退出登录</button>
      </template>
    </header>
    <div v-if="showUser" class="subbar">
      <el-steps :active="activeStep" finish-status="success" simple class="flow-steps">
        <el-step>
          <template #title>
            <button type="button" class="step-btn" :aria-current="route.path === '/' ? 'page' : undefined" @click="router.push('/')">
              上传找货
            </button>
          </template>
        </el-step>
        <el-step>
          <template #title>
            <button
              type="button"
              class="step-btn"
              :disabled="!canOpenResult"
              :title="canOpenResult ? '确认品类' : '完成识别后可进入'"
              :aria-current="route.path === '/result' ? 'page' : undefined"
              @click="go('/result', canOpenResult)"
            >
              确认品类
            </button>
          </template>
        </el-step>
        <el-step>
          <template #title>
            <button
              type="button"
              class="step-btn"
              :disabled="!canOpenProducts"
              :title="canOpenProducts ? '查看产品' : '查出产品后可进入'"
              :aria-current="route.path === '/products' ? 'page' : undefined"
              @click="go('/products', canOpenProducts)"
            >
              查看产品
            </button>
          </template>
        </el-step>
      </el-steps>
      <div v-if="store.session" class="session-summary" aria-label="当前识别会话">
        <el-tag v-if="modeLabel" size="small" :type="modeTagType">{{ modeLabel }}</el-tag>
        <span>图片 {{ partCount }} 张</span>
        <span>车型 {{ vehicleText }}</span>
        <span>OE {{ store.session.oe_number || '未填写' }}</span>
      </div>
    </div>
    <main id="main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearAppAuth } from '@/api/client'
import { useRecognitionStore } from '@/stores/recognition'

const route = useRoute()
const router = useRouter()
const store = useRecognitionStore()
const displayName = ref(localStorage.getItem('app_name') || localStorage.getItem('app_username') || '')
const showUser = computed(() => route.path !== '/login')
const activeStep = computed(() => {
  if (route.path === '/products') return 2
  if (route.path === '/result') return 1
  return 0
})
const canOpenResult = computed(() => {
  const session = store.session
  if (!session || session.status !== 'done') return false
  return session.is_auto_part === false || Boolean(session.result)
})
const canOpenProducts = computed(() => {
  const session = store.session
  if (!session || session.status !== 'done') return false
  if (store.products.length) return true
  if (['sku_match', 'category_match'].includes(session.recognition_mode)) return true
  return Boolean(session.confirmed_category_name)
})
const partCount = computed(
  () => (store.session?.images || []).filter((image) => image.purpose !== 'oe_label').length,
)
const vehicleText = computed(() => {
  const parts = [
    store.session?.vehicle_brand,
    store.session?.vehicle_series,
    store.session?.vehicle_model,
    store.session?.vehicle_year,
  ].filter(Boolean)
  return parts.length ? parts.join(' / ') : '未选择'
})
const modeLabel = computed(() => {
  const mode = store.session?.recognition_mode
  if (mode === 'sku_match') return '360 图库直匹配'
  if (mode === 'category_match') return '已确认品类'
  if (mode === 'vision_fallback') return '品类识别'
  if (store.session?.is_auto_part === false) return '非汽配'
  return ''
})
const modeTagType = computed(() => {
  if (store.session?.recognition_mode === 'sku_match') return 'success'
  if (store.session?.is_auto_part === false) return 'danger'
  return 'primary'
})

watch(
  () => route.path,
  () => {
    displayName.value = localStorage.getItem('app_name') || localStorage.getItem('app_username') || ''
  },
)

function go(path, allowed) {
  if (!allowed) return
  router.push(path)
}

function logout() {
  clearAppAuth()
  store.reset()
  displayName.value = ''
  router.push('/login')
}
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 56px;
  padding: 0 20px;
  background: #0b1b33;
  color: #fff;
}

.brand-block {
  display: flex;
  align-items: baseline;
  gap: 10px;
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
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.logout {
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  background: transparent;
  color: #fff;
  cursor: pointer;
  padding: 6px 12px;
}

.subbar {
  position: sticky;
  top: 56px;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 20px;
  border-bottom: 1px solid #e4e8ee;
  background: #fff;
}

.flow-steps {
  flex: 1 1 460px;
  max-width: 640px;
  padding: 6px 8px;
}

.step-btn {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-weight: 600;
  padding: 0;
}

.step-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.session-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px 12px;
  margin-left: auto;
  color: #5b6775;
  font-size: 13px;
}

@media (max-width: 900px) {
  .subbar {
    flex-direction: column;
    align-items: stretch;
  }

  .session-summary {
    justify-content: flex-start;
    margin-left: 0;
  }
}
</style>
