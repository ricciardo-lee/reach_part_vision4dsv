<template>
  <div class="page">
    <section class="card hero">
      <h1 class="title-row"><span class="emoji" aria-hidden="true">📷</span> 零件识图找货</h1>
      <p class="muted">按角度上传实拍图，AI 识别品类后可选择车型或输入 OE 号查询公司产品。</p>
      <van-steps :active="stepActive" active-color="#1f6feb">
        <van-step>拍照上传</van-step>
        <van-step>确认品类</van-step>
        <van-step>车型/OE</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
      <p v-if="statusHint" class="muted" style="margin-top: 8px">{{ statusHint }}</p>
    </section>

    <section class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🧭</span> 多角度拍摄</h3>
      <p class="muted">至少上传 1 张；建议补齐整体、接口、铭牌，光线充足，避免强反光。</p>
      <div v-for="slot in angleSlots" :key="slot.purpose" class="slot">
        <div class="title-row" style="margin-bottom: 6px">
          <span class="emoji" aria-hidden="true">{{ slot.emoji }}</span>
          {{ slot.label }}
          <span class="muted" v-if="slot.required">（建议）</span>
        </div>
        <van-uploader
          v-model="slot.fileList"
          :max-count="1"
          accept="image/*"
          :max-size="10 * 1024 * 1024"
          @oversize="onOversize"
        />
      </div>
      <p class="muted" style="margin-top: 8px">已选 {{ totalFiles }} / 4 张</p>
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
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { useRecognitionStore } from '@/stores/recognition'

const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const optimizationConsent = ref(false)
const errorMessage = ref('')
const progressMessage = ref('')

const angleSlots = reactive([
  { purpose: 'part_overall', emoji: '🖼️', label: '整体外观', required: true, sortOrder: 0, fileList: [] },
  { purpose: 'part_connector', emoji: '🔌', label: '接口特写', required: false, sortOrder: 1, fileList: [] },
  { purpose: 'part_label', emoji: '🏷️', label: '铭牌/标签', required: false, sortOrder: 2, fileList: [] },
  { purpose: 'part_other', emoji: '➕', label: '其他角度', required: false, sortOrder: 3, fileList: [] },
])

const totalFiles = computed(() =>
  angleSlots.reduce((sum, slot) => sum + slot.fileList.filter((f) => f?.file || f?.content).length, 0),
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

function collectSlotFiles() {
  return angleSlots
    .map((slot) => {
      const item = slot.fileList[0]
      const file = item?.file || item?.content
      if (!(file instanceof Blob)) return null
      return { purpose: slot.purpose, sortOrder: slot.sortOrder, file }
    })
    .filter(Boolean)
}

async function start() {
  errorMessage.value = ''
  progressMessage.value = ''
  const slots = collectSlotFiles()
  if (!slots.length) {
    showToast({ message: '请至少上传一张零件照片', position: 'top' })
    return
  }

  loading.value = true
  showLoadingToast({ message: '上传图片中…', forbidClick: true, duration: 0 })
  try {
    await store.createSession()
    progressMessage.value = '图片上传中…'
    for (const slot of slots) {
      await store.uploadImages([slot.file], slot.purpose, slot.sortOrder)
    }
    if (optimizationConsent.value) {
      await store.setConsent(true)
    }
    progressMessage.value = '已提交识别，排队/处理中…'
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

<style scoped>
.slot {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}
.slot:first-of-type {
  border-top: none;
  padding-top: 0;
}
</style>
