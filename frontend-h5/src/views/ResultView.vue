<template>
  <div class="page">
    <section class="card">
      <van-steps :active="1" active-color="#2563eb">
        <van-step>{{ t('steps.upload') }}</van-step>
        <van-step>{{ t('steps.confirm') }}</van-step>
        <van-step>{{ t('steps.products') }}</van-step>
      </van-steps>
    </section>

    <QueryImageGallery :images="store.session?.images || []" />

    <section class="card">
      <h2 class="title-row"><span class="emoji" aria-hidden="true">🤖</span> {{ t('result.title') }}</h2>
      <p v-if="store.session?.recognition_mode === 'vision_fallback'" class="muted" style="margin-bottom: 8px">
        {{ t('result.visionFallbackHint') }}
      </p>
      <template v-if="isAutoPart && isSupported">
        <p v-if="result">
          {{ t('result.topCategoryValue') }}<strong>{{ displayCategory(result.mapped_category_name || result.part_name) }}</strong>
          {{ t('result.confidenceValue', { pct: Math.round((result.confidence || 0) * 100) }) }}
        </p>
        <p class="muted">{{ result?.reason || t('result.noReason') }}</p>
        <van-tag v-if="confidenceLevel === 'high'" type="success">{{ t('confidence.highEmoji') }}</van-tag>
        <van-tag v-else-if="confidenceLevel === 'mid'" type="warning">{{ t('confidence.midEmoji') }}</van-tag>
        <van-tag v-else type="danger">{{ t('confidence.lowEmoji') }}</van-tag>
      </template>
      <template v-else-if="isAutoPart && !isSupported">
        <p class="title-row" style="color: #b91c1c; margin-bottom: 8px">
          <span class="emoji" aria-hidden="true">🚫</span> {{ t('category.unsupportedTitle') }}
        </p>
        <p v-if="result">
          {{ t('result.recognizedAs') }}：<strong>{{ result.part_name || t('result.nonAutoContent') }}</strong>
        </p>
        <p class="muted">{{ t('category.unsupportedHint') }}</p>
      </template>
      <template v-else>
        <p class="title-row" style="color: #b91c1c; margin-bottom: 8px">
          <span class="emoji" aria-hidden="true">🚫</span> {{ t('result.notAutoPart') }}
        </p>
        <p v-if="result">
          {{ t('result.recognizedAs') }}：<strong>{{ result.part_name || t('result.nonAutoContent') }}</strong>
        </p>
        <p class="muted">{{ rejectReason }}</p>
        <p class="muted">{{ t('result.retakeHint') }}</p>
      </template>
    </section>

    <section v-if="isAutoPart" class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🧩</span> {{ t('result.candidates') }}</h3>
      <p class="muted" style="margin-bottom: 8px">{{ t('category.supportedList') }}</p>
      <div
        v-for="(item, index) in candidates"
        :key="index"
        class="candidate"
        :class="{ active: selectedName === (item.category_name || item.name) }"
        @click="selectCandidate(item)"
      >
        <div>
          <div>{{ displayCategory(item.category_name || item.name) }}</div>
          <div class="muted">{{ t('result.originalName', { name: item.name }) }}</div>
        </div>
        <strong>{{ Math.round((item.confidence || 0) * 100) }}%</strong>
      </div>
      <div v-if="!candidates.length" class="muted" style="margin-bottom: 8px">
        {{ t('category.unsupportedHint') }}
      </div>
      <div class="manual-row">
        <button
          v-for="opt in supportedOptions"
          :key="opt.id"
          type="button"
          class="manual-chip"
          :class="{ active: selectedCode === opt.code }"
          @click="selectSupported(opt)"
        >
          {{ t(opt.labelKey) }}
        </button>
      </div>
    </section>

    <section v-if="isAutoPart && isSupported" class="card">
      <van-checkbox v-model="optimizationConsent" shape="square" @change="onConsentChange">
        {{ t('result.consentEmoji') }}
      </van-checkbox>
      <van-button
        v-if="store.session?.optimization_consent"
        size="mini"
        plain
        type="warning"
        style="margin-top: 8px"
        @click="revokeConsent"
      >
        {{ t('result.revoke') }}
      </van-button>
    </section>

    <div class="bottom-bar">
      <van-button
        v-if="isAutoPart && canProceed"
        type="primary"
        block
        round
        :loading="loading"
        @click="next"
      >
        {{ t('result.queryProductsEmoji') }}
      </van-button>
      <van-button v-else type="primary" block round @click="retake">
        {{ t('result.retakeEmoji') }}
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { categoryLabelKey, knownErrorKey } from '@shared/locales/index.js'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'

const SUPPORTED_IDS = new Set(['compressor', 'condenser', 'radiator'])

const { t } = useI18n()
const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const selectedCode = ref('')
const selectedName = ref('')
const optimizationConsent = ref(Boolean(store.session?.optimization_consent))

const supportedOptions = [
  { id: 'compressor', code: 'COMPRESSOR', labelKey: 'category.compressor' },
  { id: 'condenser', code: 'CONDENSER', labelKey: 'category.condenser' },
  { id: 'radiator', code: 'RADIATOR', labelKey: 'category.radiator' },
]

const result = computed(() => store.session?.result)
const isAutoPart = computed(() => {
  if (store.session?.is_auto_part === false) return false
  if (store.session?.result?.is_auto_part === false) return false
  return true
})
const isSupported = computed(() => {
  if (store.session?.is_supported_category === false) return false
  if ((store.session?.error_message || '') === 'unsupported_category') return false
  return true
})
const rejectReason = computed(() => {
  const msg = store.session?.error_message || result.value?.reason || t('result.notAutoPartReason')
  const key = knownErrorKey(msg)
  return key ? t(key) : msg
})

function isSupportedCandidate(item) {
  const code = String(item?.category_code || '').toLowerCase()
  const name = String(item?.category_name || item?.name || '').toLowerCase()
  if (SUPPORTED_IDS.has(code)) return true
  if (['compressor', 'condenser', 'radiator'].some((id) => name.includes(id))) return true
  if (['压缩机', '冷凝器', '散热器'].some((cn) => String(item?.category_name || item?.name || '').includes(cn))) {
    return true
  }
  const key = categoryLabelKey(item?.category_code || item?.category_name || item?.name)
  return Boolean(key)
}

const candidates = computed(() => (result.value?.candidates || []).filter(isSupportedCandidate))
const canProceed = computed(() => {
  if (!isAutoPart.value) return false
  if (selectedCode.value || selectedName.value) return true
  return isSupported.value && candidates.value.length > 0
})
const confidenceLevel = computed(() => {
  const confidence = result.value?.confidence || 0
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'mid'
  return 'low'
})

function displayCategory(idOrName) {
  const key = categoryLabelKey(idOrName)
  return key ? t(key) : idOrName || ''
}

function selectCandidate(item) {
  selectedCode.value = item.category_code || ''
  selectedName.value = item.category_name || item.name
}

function selectSupported(opt) {
  selectedCode.value = opt.code
  selectedName.value = t(opt.labelKey)
}

async function onConsentChange(val) {
  try {
    await store.setConsent(val)
  } catch (err) {
    const msg = err?.message || t('result.consentFailed')
    const key = knownErrorKey(msg)
    showToast(key ? t(key) : msg)
  }
}

async function revokeConsent() {
  await store.revokeConsent()
  optimizationConsent.value = false
  showToast(t('result.revoked'))
}

async function next() {
  if (!isAutoPart.value) {
    showToast(t('result.notAutoPartToast'))
    return
  }
  const name = selectedName.value
  const oeNumber = store.session?.oe_number || ''
  if (!name && !oeNumber) {
    showToast(t('result.needCategory'))
    return
  }
  loading.value = true
  try {
    if (name) {
      await store.confirmCategory({
        category_code: selectedCode.value || null,
        category_name: name,
        optimization_consent: optimizationConsent.value,
      })
    } else if (optimizationConsent.value !== Boolean(store.session?.optimization_consent)) {
      await store.setConsent(optimizationConsent.value)
    }
    await store.searchProducts()
    router.push('/products')
  } catch (err) {
    const msg = err?.message || err?.response?.data?.message || t('result.queryFailed')
    const key = knownErrorKey(msg)
    showToast(key ? t(key) : msg)
  } finally {
    loading.value = false
  }
}

function retake() {
  router.replace('/')
}

onMounted(() => {
  if (!store.session) {
    router.replace('/')
    return
  }
  if (!isAutoPart.value || !result.value) return
  if (isSupportedCandidate({
    category_code: result.value.mapped_category_code,
    category_name: result.value.mapped_category_name || result.value.part_name,
    name: result.value.part_name,
  })) {
    selectCandidate({
      category_code: result.value.mapped_category_code,
      category_name: result.value.mapped_category_name || result.value.part_name,
      name: result.value.part_name,
      confidence: result.value.confidence,
    })
  } else if (candidates.value[0]) {
    selectCandidate(candidates.value[0])
  }
})
</script>

<style scoped>
.manual-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.manual-chip {
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
}
.manual-chip.active {
  border-color: #2563eb;
  color: #2563eb;
  background: #eff6ff;
}
</style>
