<template>
  <div class="page">
    <section class="card hero">
      <h1>{{ t('common.appName') }}</h1>
      <van-steps :active="0" active-color="#2563eb">
        <van-step>{{ t('steps.upload') }}</van-step>
        <van-step>{{ t('steps.confirm') }}</van-step>
        <van-step>{{ t('steps.products') }}</van-step>
      </van-steps>
      <p v-if="statusHint" class="muted">{{ statusHint }}</p>
    </section>

    <section class="card">
      <h3>{{ t('home.partPhotos') }}</h3>
      <p class="muted">{{ t('home.tip') }}</p>
      <van-uploader
        v-model="fileList"
        multiple
        :max-count="8"
        accept="image/*"
        :max-size="10 * 1024 * 1024"
        @oversize="onOversize"
      />
      <p class="muted" style="margin-top: 8px">{{ t('home.selectedCount', { count: totalFiles }) }}</p>
      <QueryImageGallery v-if="!totalFiles && partImages.length" :images="partImages" />
    </section>

    <VehicleOeForm ref="filterForm" />

    <section class="card">
      <van-checkbox v-model="optimizationConsent" shape="square">
        {{ t('home.consent') }}
      </van-checkbox>
    </section>

    <section v-if="errorMessage" class="card error-card">
      <p>{{ errorMessage }}</p>
      <van-button v-if="canRetry" size="small" type="danger" plain :loading="loading" @click="start">
        {{ t('home.retry') }}
      </van-button>
    </section>

    <div class="bottom-bar">
      <van-button type="primary" block round :loading="loading" :disabled="loading" @click="start">
        {{ actionLabel }}
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { knownErrorKey, progressKey } from '@shared/locales/index.js'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'
import VehicleOeForm from '@/components/VehicleOeForm.vue'

const { t } = useI18n()
const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const optimizationConsent = ref(false)
const errorMessage = ref('')
const progressMessage = ref('')
const fileList = ref([])
const filterForm = ref(null)

const totalFiles = computed(() => fileList.value.filter((item) => item?.file || item?.content).length)
const partImages = computed(() => (store.session?.images || []).filter((image) => image.purpose !== 'oe_label'))
const canAdjustExisting = computed(
  () => store.session?.status === 'done' && partImages.value.length > 0 && totalFiles.value === 0,
)
const actionLabel = computed(() => (canAdjustExisting.value ? t('home.rematch') : t('home.start')))
const statusHint = computed(() => progressMessage.value || '')
const canRetry = computed(() => Boolean(errorMessage.value))

function translateMessage(message, fallbackKey) {
  const key = knownErrorKey(message)
  if (key) return t(key)
  if (message) return message
  return fallbackKey ? t(fallbackKey) : ''
}

function onOversize() {
  showToast({ message: t('home.maxSize'), position: 'top' })
}

function collectFiles() {
  return fileList.value.map((item) => item?.file || item?.content).filter((file) => file instanceof Blob)
}

function fail(message) {
  const text = translateMessage(message, 'home.failed')
  errorMessage.value = text
  showToast({ message: text, position: 'top' })
}

function progressText(session) {
  const key = progressKey(session)
  return t(key || 'home.recognizing')
}

async function routeAfterRecognition() {
  if (store.session?.status === 'failed') {
    fail(store.session.error_message || t('home.failed'))
    return
  }
  if (store.session?.status !== 'done') {
    fail(t('home.timeout'))
    return
  }
  if (store.session?.is_auto_part === false) {
    router.push('/result')
    return
  }
  if (['sku_match', 'category_match'].includes(store.session?.recognition_mode)) {
    await store.searchProducts()
    router.push('/products')
    return
  }
  router.push('/result')
}

async function start() {
  errorMessage.value = ''
  progressMessage.value = ''
  const files = collectFiles()
  if (!files.length && !partImages.value.length) {
    showToast({ message: t('home.needOnePhoto'), position: 'top' })
    return
  }
  if (files.length > 8) {
    showToast({ message: t('home.maxCount'), position: 'top' })
    return
  }
  if (!filterForm.value?.validateOe()) return

  loading.value = true
  showLoadingToast({ message: t('home.submitting'), forbidClick: true, duration: 0 })
  try {
    if (canAdjustExisting.value) {
      const saved = await filterForm.value.submit()
      if (!saved) return
      if (store.session?.is_auto_part === false) {
        router.push('/result')
        return
      }
      if (
        ['sku_match', 'category_match'].includes(store.session?.recognition_mode) ||
        store.session?.confirmed_category_name ||
        store.session?.oe_number
      ) {
        await store.searchProducts()
        router.push('/products')
        return
      }
      router.push('/result')
      return
    }

    const reusable = ['created', 'uploading'].includes(store.session?.status)
    if (!reusable) await store.createSession()
    if (files.length) {
      progressMessage.value = t('home.uploading')
      await store.uploadImages(files, 'part', 0)
    }
    if (optimizationConsent.value) await store.setConsent(true)
    const saved = await filterForm.value.submit()
    if (!saved) return
    progressMessage.value = t('home.submitted')
    showLoadingToast({ message: progressMessage.value, forbidClick: true, duration: 0 })
    await store.startRecognize((session) => {
      progressMessage.value = progressText(session)
      showLoadingToast({ message: progressMessage.value, forbidClick: true, duration: 0 })
    })
    await routeAfterRecognition()
  } catch (err) {
    fail(err?.message || err?.response?.data?.message || t('home.requestFailed'))
  } finally {
    closeToast()
    loading.value = false
  }
}

onMounted(() => {
  optimizationConsent.value = Boolean(store.session?.optimization_consent)
})
</script>

<style scoped>
h1,
h3 {
  margin: 0 0 8px;
  font-size: 18px;
}

h3 {
  font-size: 16px;
}

.error-card {
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.error-card p {
  margin: 0 0 8px;
}
</style>
