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
      <template v-if="isAutoPart">
        <p v-if="result">
          {{ t('result.topCategoryValue') }}<strong>{{ displayCategory(result.mapped_category_name || result.part_name) }}</strong>
          {{ t('result.confidenceValue', { pct: Math.round((result.confidence || 0) * 100) }) }}
        </p>
        <p class="muted">{{ result?.reason || t('result.noReason') }}</p>
        <van-tag v-if="confidenceLevel === 'high'" type="success">{{ t('confidence.highEmoji') }}</van-tag>
        <van-tag v-else-if="confidenceLevel === 'mid'" type="warning">{{ t('confidence.midEmoji') }}</van-tag>
        <van-tag v-else type="danger">{{ t('confidence.lowEmoji') }}</van-tag>
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
      <van-field
        v-model="manualName"
        :label="t('result.manualEmoji')"
        :placeholder="t('result.manualPlaceholder')"
      />
    </section>

    <section v-if="isAutoPart" class="card">
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
      <van-button v-if="isAutoPart" type="primary" block round :loading="loading" @click="next">
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

const { t } = useI18n()
const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const selectedCode = ref('')
const selectedName = ref('')
const manualName = ref('')
const optimizationConsent = ref(Boolean(store.session?.optimization_consent))

const result = computed(() => store.session?.result)
const isAutoPart = computed(() => {
  if (store.session?.is_auto_part === false) return false
  if (store.session?.result?.is_auto_part === false) return false
  return true
})
const rejectReason = computed(() => {
  const msg = store.session?.error_message || result.value?.reason || t('result.notAutoPartReason')
  const key = knownErrorKey(msg)
  return key ? t(key) : msg
})
const candidates = computed(() => result.value?.candidates || [])
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
  manualName.value = selectedName.value
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
  const name = manualName.value || selectedName.value
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
  selectCandidate({
    category_code: result.value.mapped_category_code,
    category_name: result.value.mapped_category_name || result.value.part_name,
    name: result.value.part_name,
    confidence: result.value.confidence,
  })
})
</script>
