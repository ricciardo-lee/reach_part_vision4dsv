<template>
  <div class="workbench home-workbench" :aria-busy="loading">
    <div class="workbench-split">
      <el-card class="pane photo-pane" shadow="never">
        <template #header>
          <div class="card-head">
            <span>零件照片</span>
            <div class="card-actions">
              <span class="count">已选 {{ files.length }} / 8 张</span>
              <button type="button" class="link-button" :disabled="!files.length" @click="clearFiles">清空</button>
            </div>
          </div>
        </template>
        <div class="photo-body">
          <button
            v-if="files.length || partImages.length"
            type="button"
            class="add-bar"
            :class="{ over: dragOver }"
            @click="openPicker"
            @dragenter.prevent="onDragEnter"
            @dragover.prevent="dragOver = true"
            @dragleave.prevent="onDragLeave"
            @drop.prevent="onDrop"
          >
            <strong>继续添加图片</strong>
            <span>拖拽、点击或粘贴，最多 8 张</span>
          </button>

          <div
            class="photo-main"
            :class="{ droppable: !files.length && !partImages.length, over: dragOver }"
            @dragenter.prevent="onDragEnter"
            @dragover.prevent="dragOver = true"
            @dragleave.prevent="onDragLeave"
            @drop.prevent="onDrop"
          >
            <button
              v-if="!files.length && !partImages.length"
              type="button"
              class="dropzone"
              tabindex="0"
              aria-label="上传零件照片，可拖拽、粘贴或按 Enter 选择文件"
              @click="openPicker"
              @keydown.enter.prevent="openPicker"
              @keydown.space.prevent="openPicker"
            >
              <strong>把图片拖到这里</strong>
              <span>点击选择，或在页面中直接粘贴。同一产品 1–8 张。</span>
            </button>
            <div v-else-if="currentFile" class="stage">
              <img :src="currentFile.url" :alt="currentFile.name || '当前零件照片'" />
            </div>
            <QueryImageGallery
              v-else
              workbench
              bare
              class="embedded-gallery"
              :images="partImages"
            />
          </div>

          <ul v-if="files.length" class="filmstrip" aria-label="已选图片">
            <li v-for="(item, index) in files" :key="item.id">
              <button
                type="button"
                class="thumb"
                :class="{ active: index === selectedIndex }"
                :aria-pressed="index === selectedIndex"
                @click="selectedIndex = index"
              >
                <img :src="item.url" :alt="item.name || `零件照片 ${index + 1}`" />
              </button>
              <button type="button" class="remove" @click="removeFile(item.id)">移除</button>
            </li>
          </ul>

          <p v-if="canAdjustExisting" class="hint">
            已有识别结果。修改车型或 OE 后可重新匹配；上传新照片会开始一次新的识别。
          </p>
        </div>
        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          accept="image/*"
          multiple
          aria-label="选择零件照片"
          @change="onPick"
        />
      </el-card>

      <el-card class="pane form-pane" shadow="never">
        <template #header>车型与 OE</template>
        <VehicleOeForm ref="filterForm" />
      </el-card>
    </div>

    <div class="workbench-footer">
      <el-checkbox v-model="optimizationConsent">
        我同意将图片用于识别优化（可选，原图默认 30 天清理）
      </el-checkbox>
      <p v-if="statusHint" class="status" role="status">{{ statusHint }}</p>
      <el-alert
        v-if="errorMessage"
        id="form-error"
        class="form-error"
        type="error"
        :title="errorMessage"
        :closable="false"
        show-icon
        tabindex="-1"
      />
      <div class="actions">
        <el-button v-if="canRetry" :disabled="loading" @click="start">重新识别</el-button>
        <el-button type="primary" :loading="loading" :disabled="loading" @click="start">
          {{ actionLabel }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'
import VehicleOeForm from '@/components/VehicleOeForm.vue'

const MAX_BYTES = 10 * 1024 * 1024
const IMAGE_EXT = /\.(jpe?g|png|gif|webp|bmp|heic|heif|avif)$/i

const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const optimizationConsent = ref(false)
const errorMessage = ref('')
const progressMessage = ref('')
const files = ref([])
const selectedIndex = ref(0)
const filterForm = ref(null)
const fileInput = ref(null)
const dragOver = ref(false)
let dragDepth = 0

const currentFile = computed(() => files.value[selectedIndex.value] || null)
const partImages = computed(() => (store.session?.images || []).filter((image) => image.purpose !== 'oe_label'))
const canAdjustExisting = computed(
  () => store.session?.status === 'done' && partImages.value.length > 0 && files.value.length === 0,
)
const actionLabel = computed(() => (canAdjustExisting.value ? '按车型/OE 重新匹配' : '开始识别'))
const statusHint = computed(() => progressMessage.value || '')
const canRetry = computed(() => Boolean(errorMessage.value))

watch(
  () => files.value.length,
  (length) => {
    if (selectedIndex.value >= length) selectedIndex.value = Math.max(0, length - 1)
  },
)

function isImage(file) {
  return file.type?.startsWith('image/') || IMAGE_EXT.test(file.name || '')
}

function addFiles(incoming) {
  const rejectedType = []
  const rejectedSize = []
  const accepted = []
  ;[...incoming].forEach((file) => {
    if (!isImage(file)) rejectedType.push(file)
    else if (file.size > MAX_BYTES) rejectedSize.push(file)
    else accepted.push(file)
  })
  const room = Math.max(0, 8 - files.value.length)
  const taken = accepted.slice(0, room)
  const overflow = accepted.length > room
  taken.forEach((file) => {
    files.value.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      file,
      name: file.name || 'image.jpg',
      url: URL.createObjectURL(file),
    })
  })
  if (taken.length) selectedIndex.value = files.value.length - 1
  const messages = []
  if (rejectedType.length) messages.push('只能上传图片')
  if (rejectedSize.length) messages.push('单张图片不能超过 10MB')
  if (overflow) messages.push('最多上传 8 张图片')
  if (messages.length) ElMessage.warning(messages.join('，'))
}

function openPicker() {
  fileInput.value?.click()
}

function onPick(event) {
  addFiles(event.target.files || [])
  event.target.value = ''
}

function onDragEnter() {
  dragDepth += 1
  dragOver.value = true
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragOver.value = false
}

function onDrop(event) {
  dragDepth = 0
  dragOver.value = false
  addFiles(event.dataTransfer?.files || [])
}

function removeFile(id) {
  const index = files.value.findIndex((item) => item.id === id)
  if (index < 0) return
  URL.revokeObjectURL(files.value[index].url)
  files.value.splice(index, 1)
}

function clearFiles() {
  files.value.forEach((item) => URL.revokeObjectURL(item.url))
  files.value = []
  selectedIndex.value = 0
}

function collectFiles() {
  return files.value.map((item) => item.file).filter((file) => file instanceof Blob)
}

async function fail(message, toast = false) {
  errorMessage.value = message
  progressMessage.value = ''
  if (toast) ElMessage.error(message)
  await nextTick()
  document.getElementById('form-error')?.focus()
}

function isApiError(err) {
  return Boolean(err?.response || err?.isAxiosError || err?.success === false)
}

async function routeAfterRecognition() {
  if (store.session?.status === 'failed') {
    await fail(store.session.error_message || '识别失败，请稍后重试', true)
    return
  }
  if (store.session?.status !== 'done') {
    await fail('识别超时，请重试', true)
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
  if (loading.value) return
  errorMessage.value = ''
  progressMessage.value = ''
  const selected = collectFiles()
  if (!selected.length && !partImages.value.length) {
    ElMessage.warning('请至少上传一张零件照片')
    return
  }
  if (selected.length > 8) {
    ElMessage.warning('最多上传 8 张图片')
    return
  }
  if (!filterForm.value?.validateOe()) return

  loading.value = true
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
    if (selected.length) {
      progressMessage.value = '图片上传中…'
      await store.uploadImages(selected, 'part', 0)
    }
    if (optimizationConsent.value) await store.setConsent(true)
    const saved = await filterForm.value.submit()
    if (!saved) return
    progressMessage.value = '已提交识别，优先匹配图库…'
    await store.startRecognize((session) => {
      progressMessage.value = session?.progress_hint || '识别中…'
    })
    await routeAfterRecognition()
  } catch (err) {
    await fail(err?.message || err?.response?.data?.message || '识别请求失败，请确认后端已启动', !isApiError(err))
  } finally {
    loading.value = false
  }
}

function onPaste(event) {
  const target = event.target
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
  const images = [...(event.clipboardData?.files || [])].filter((file) => isImage(file))
  if (!images.length) return
  event.preventDefault()
  addFiles(images)
}

function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    start()
  }
}

onMounted(() => {
  optimizationConsent.value = Boolean(store.session?.optimization_consent)
  window.addEventListener('paste', onPaste)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('paste', onPaste)
  window.removeEventListener('keydown', onKeydown)
  clearFiles()
})
</script>

<style scoped>
.home-workbench .workbench-split {
  grid-template-columns: minmax(0, 0.92fr) minmax(520px, 1.08fr);
}

.home-workbench .pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.home-workbench .pane :deep(.el-card__body) {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.photo-pane :deep(.el-card__body) {
  padding-bottom: 14px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-weight: 700;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.photo-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

.add-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: center;
  gap: 8px 12px;
  flex: 0 0 auto;
  width: 100%;
  margin: 0;
  padding: 10px 12px;
  border: 1px dashed #9db0c7;
  border-radius: 10px;
  background: #f8fafc;
  color: #344054;
  cursor: pointer;
  text-align: center;
}

.add-bar strong {
  font-size: 14px;
}

.add-bar span,
.count,
.hint,
.status {
  color: #5b6775;
  font-size: 13px;
}

.add-bar.over,
.add-bar:hover,
.photo-main.droppable.over,
.dropzone:hover {
  border-color: var(--el-color-primary);
  background: #eff6ff;
}

.photo-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 220px;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
}

.photo-main.droppable {
  border-style: dashed;
  border-color: #9db0c7;
  background: #f8fafc;
}

.dropzone {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 0;
  margin: 0;
  padding: 24px 20px;
  border: 0;
  background: transparent;
  color: #344054;
  cursor: pointer;
  text-align: center;
}

.dropzone span {
  max-width: 280px;
  color: #5b6775;
  font-size: 13px;
  line-height: 1.5;
}

.stage {
  display: grid;
  place-items: center;
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 12px;
  overflow: hidden;
}

.stage img {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}

.embedded-gallery {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: auto;
  padding: 10px;
}

.embedded-gallery :deep(.pair) {
  flex: 1;
  min-height: 0;
  margin-top: 0;
}

.embedded-gallery :deep(.frame),
.embedded-gallery :deep(img),
.embedded-gallery :deep(.empty) {
  height: auto;
  max-height: 100%;
  aspect-ratio: auto;
}

.embedded-gallery :deep(.frame) {
  height: 100%;
  min-height: 160px;
}

.embedded-gallery :deep(figure) {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.filmstrip {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
  margin: 0;
  padding: 2px 0 0;
  list-style: none;
  overflow-x: auto;
}

.filmstrip li {
  flex: 0 0 76px;
}

.thumb {
  display: block;
  width: 100%;
  padding: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  overflow: hidden;
}

.thumb.active {
  border-color: var(--el-color-primary);
  box-shadow: inset 0 0 0 1px var(--el-color-primary);
}

.thumb img {
  display: block;
  width: 100%;
  height: 64px;
  object-fit: contain;
  background: #f8fafc;
}

.remove {
  display: block;
  width: 100%;
  margin-top: 4px;
  border: 0;
  background: transparent;
  color: #b91c1c;
  cursor: pointer;
  font-size: 12px;
}

.count {
  margin: 0;
  font-weight: 500;
}

.hint {
  flex: 0 0 auto;
  margin: 0;
}

.form-error {
  flex: 1 1 240px;
  margin: 0;
}

@media (max-width: 1023px) {
  .home-workbench .workbench-split {
    grid-template-columns: 1fr;
  }

  .home-workbench .pane :deep(.el-card__body) {
    overflow: visible;
  }

  .photo-body {
    overflow: visible;
  }

  .photo-main {
    min-height: 280px;
  }
}
</style>
