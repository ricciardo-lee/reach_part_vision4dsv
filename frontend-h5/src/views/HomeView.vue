<template>
  <div class="page">
    <section class="card hero">
      <h1>零件识图找货</h1>
      <van-steps :active="0" active-color="#2563eb">
        <van-step>上传找货</van-step>
        <van-step>确认品类</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
      <p v-if="statusHint" class="muted">{{ statusHint }}</p>
    </section>

    <section class="card">
      <h3>零件照片</h3>
      <p class="muted">同一产品 1–8 张不同角度，光线充足，避免强反光。</p>
      <van-uploader
        v-model="fileList"
        multiple
        :max-count="8"
        accept="image/*"
        :max-size="10 * 1024 * 1024"
        @oversize="onOversize"
      />
      <p class="muted" style="margin-top: 8px">已选 {{ totalFiles }} / 8 张</p>
      <QueryImageGallery v-if="!totalFiles && partImages.length" :images="partImages" />
    </section>

    <VehicleOeForm ref="filterForm" />

    <section class="card">
      <van-checkbox v-model="optimizationConsent" shape="square">
        我同意将图片用于识别优化（可选，原图默认 30 天清理）
      </van-checkbox>
    </section>

    <section v-if="errorMessage" class="card error-card">
      <p>{{ errorMessage }}</p>
      <van-button v-if="canRetry" size="small" type="danger" plain :loading="loading" @click="start">
        重新识别
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
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'
import VehicleOeForm from '@/components/VehicleOeForm.vue'

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
const actionLabel = computed(() => (canAdjustExisting.value ? '按车型/OE 重新匹配' : '开始识别'))
const statusHint = computed(() => progressMessage.value || '')
const canRetry = computed(() => Boolean(errorMessage.value))

function onOversize() {
  showToast({ message: '单张图片不能超过 10MB', position: 'top' })
}

function collectFiles() {
  return fileList.value.map((item) => item?.file || item?.content).filter((file) => file instanceof Blob)
}

function fail(message) {
  errorMessage.value = message
  showToast({ message, position: 'top' })
}

async function routeAfterRecognition() {
  if (store.session?.status === 'failed') {
    fail(store.session.error_message || '识别失败，请稍后重试')
    return
  }
  if (store.session?.status !== 'done') {
    fail('识别超时，请重试')
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
    showToast({ message: '请至少上传一张零件照片', position: 'top' })
    return
  }
  if (files.length > 8) {
    showToast({ message: '最多上传 8 张图片', position: 'top' })
    return
  }
  if (!filterForm.value?.validateOe()) return

  loading.value = true
  showLoadingToast({ message: '正在提交…', forbidClick: true, duration: 0 })
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
      progressMessage.value = '图片上传中…'
      await store.uploadImages(files, 'part', 0)
    }
    if (optimizationConsent.value) await store.setConsent(true)
    const saved = await filterForm.value.submit()
    if (!saved) return
    progressMessage.value = '已提交识别，优先匹配图库…'
    showLoadingToast({ message: progressMessage.value, forbidClick: true, duration: 0 })
    await store.startRecognize((session) => {
      progressMessage.value = session?.progress_hint || '识别中…'
      showLoadingToast({ message: progressMessage.value, forbidClick: true, duration: 0 })
    })
    await routeAfterRecognition()
  } catch (err) {
    fail(err?.message || err?.response?.data?.message || '识别请求失败，请确认后端已启动')
  } finally {
    closeToast()
    loading.value = false
  }
}

onMounted(() => {
  optimizationConsent.value = Boolean(store.session?.optimization_consent)
  store.bootstrap()
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
