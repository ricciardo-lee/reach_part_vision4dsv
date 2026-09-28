<template>
  <div class="page">
    <section class="card hero">
      <h1 class="title-row"><span class="emoji" aria-hidden="true">📷</span> 零件识图找货</h1>
      <p class="muted">上传同一产品的多角度实拍图（最多 8 张），优先匹配公司 360 图库 SKU；未命中再走品类识别与产品查询。</p>
      <van-steps :active="stepActive" active-color="#1f6feb">
        <van-step>拍照上传</van-step>
        <van-step>确认品类</van-step>
        <van-step>车型/OE</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
      <p v-if="statusHint" class="muted" style="margin-top: 8px">{{ statusHint }}</p>
    </section>

    <section class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🧭</span> 多角度拍照</h3>
      <p class="muted">至少 1 张，最多 8 张；请确保全部属于同一产品的不同角度，光线充足，避免强反光。</p>
      <van-uploader
        v-model="fileList"
        multiple
        :max-count="8"
        accept="image/*"
        :max-size="10 * 1024 * 1024"
        @oversize="onOversize"
      />
      <p class="muted" style="margin-top: 8px">已选 {{ totalFiles }} / 8 张。识别时会直接对原图去背景，无需点选主体。</p>
    </section>

    <section class="card">
      <van-checkbox v-model="optimizationConsent" shape="square">
        ✅ 我同意将图片用于识别优化（可选，原图默认 30 天清理）
      </van-checkbox>
    </section>

    <section v-if="errorMessage" class="card" style="border: 1px solid #fecaca; background: #fef2f2">
      <p class="title-row" style="margin: 0; color: #b91c1c">
        <span class="emoji" aria-hidden="true">❌</span> {{ errorMessage }}
      </p>
      <van-button
        v-if="canRetry"
        size="small"
        type="danger"
        plain
        style="margin-top: 8px"
        :loading="loading"
        @click="start"
      >
        🔄 重新识别
      </van-button>
    </section>

    <div class="bottom-bar">
      <van-button type="primary" block round :loading="loading" :disabled="loading" @click="start">
        🚀 开始识别
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { useRecognitionStore } from '@/stores/recognition'

const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const optimizationConsent = ref(false)
const errorMessage = ref('')
const progressMessage = ref('')
const fileList = ref([])

const totalFiles = computed(() =>
  fileList.value.filter((f) => f?.file || f?.content).length,
)

const stepActive = computed(() => {
  const status = store.session?.status
  if (!status || status === 'created' || status === 'uploading') return 0
  if (status === 'processing') return 0
  if (status === 'done' || status === 'failed') return 0
  return 0
})

const statusHint = computed(() => progressMessage.value || store.session?.progress_hint || '')
const canRetry = computed(() => store.session?.status === 'failed' || Boolean(errorMessage.value))

function onOversize() {
  showToast({ message: '单张图片不能超过 10MB', position: 'top' })
}

function collectFiles() {
  return fileList.value
    .map((item) => item?.file || item?.content)
    .filter((file) => file instanceof Blob)
}

async function start() {
  errorMessage.value = ''
  progressMessage.value = ''
  const files = collectFiles()
  if (!files.length) {
    showToast({ message: '请至少上传一张零件照片', position: 'top' })
    return
  }
  if (files.length > 8) {
    showToast({ message: '最多上传 8 张图片', position: 'top' })
    return
  }

  loading.value = true
  showLoadingToast({ message: '上传图片中…', forbidClick: true, duration: 0 })
  try {
    await store.createSession()
    progressMessage.value = '图片上传中…'
    await store.uploadImages(files, 'part', 0)
    if (optimizationConsent.value) {
      await store.setConsent(true)
    }
    progressMessage.value = '已提交识别，优先匹配图库…'
    showLoadingToast({ message: progressMessage.value, forbidClick: true, duration: 0 })
    await store.startRecognize((session) => {
      progressMessage.value = session?.progress_hint || `状态：${session?.status || 'processing'}`
      showLoadingToast({ message: progressMessage.value, forbidClick: true, duration: 0 })
    })
    if (store.session?.status === 'failed') {
      const msg = store.session.error_message || '识别失败，请稍后重试'
      errorMessage.value = msg
      showToast({ message: msg, position: 'top' })
      return
    }
    if (store.session?.status !== 'done') {
      const msg = '识别超时，请点击重新识别或检查网络'
      errorMessage.value = msg
      showToast({ message: msg, position: 'top' })
      return
    }
    if (store.session?.is_auto_part === false) {
      const msg = store.session.error_message || '未识别到汽配零件，请重新拍摄'
      showToast({ message: msg, position: 'top' })
      router.push('/result')
      return
    }
    if (store.session?.recognition_mode === 'sku_match' || store.session?.recognition_mode === 'category_match') {
      await store.searchProducts()
      router.push('/products')
      return
    }
    router.push('/result')
  } catch (err) {
    const msg =
      err?.message ||
      err?.response?.data?.message ||
      (typeof err === 'object' && err?.message) ||
      '识别请求失败，请确认后端已启动'
    errorMessage.value = String(msg)
    showToast({ message: errorMessage.value, position: 'top' })
    console.error('recognize failed', err)
  } finally {
    closeToast()
    loading.value = false
  }
}
</script>
