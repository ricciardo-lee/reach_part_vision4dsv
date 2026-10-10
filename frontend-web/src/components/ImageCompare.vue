<template>
  <section v-if="userImages.length" class="compare-card" :class="{ panel: !embedded, embedded }">
    <p v-if="!embedded" class="muted">左边是你拍的照片，可用方向键切换。右边按住拖动、滚动滚轮或使用方向键，可旋转匹配产品的 360 图。点击图片可看大图。</p>
    <div class="compare">
      <div class="shot">
        <div
          class="frame"
          tabindex="0"
          role="group"
          aria-label="上传照片"
          @keydown="onUserKey"
          @click="preview(userSrc)"
        >
          <img v-if="userSrc" :src="userSrc" alt="你的照片" />
          <div v-else class="empty">{{ userPlaceholder }}</div>
          <template v-if="userImages.length > 1">
            <button type="button" class="nav prev" aria-label="上一张照片" @click.stop="stepUser(-1)">‹</button>
            <button type="button" class="nav next" aria-label="下一张照片" @click.stop="stepUser(1)">›</button>
          </template>
        </div>
      </div>
      <div class="shot">
        <div
          ref="spinFrame"
          class="frame spin"
          tabindex="0"
          role="slider"
          aria-label="360 图，左右方向键、滚轮或拖动旋转"
          :aria-valuemin="views.length ? 1 : 0"
          :aria-valuemax="views.length"
          :aria-valuenow="views.length ? galleryIndex + 1 : 0"
          :aria-valuetext="galleryCaption"
          @pointerdown="onSpinDown"
          @pointermove="onSpinMove"
          @pointerup="onSpinUp"
          @pointercancel="onSpinUp"
          @wheel.prevent="onWheel"
          @keydown="onSpinKey"
          @click="preview(galleryShown)"
        >
          <img v-if="galleryShown" :src="galleryShown" alt="360 图库" draggable="false" />
          <div v-else class="empty">{{ galleryPlaceholder }}</div>
          <p v-if="views.length > 1" class="spin-hint">拖动、滚轮或方向键旋转</p>
        </div>
        <p class="caption">{{ galleryCaption }}</p>
      </div>
    </div>
    <p class="sr-only" aria-live="polite">{{ userCaption }}。{{ galleryCaption }}</p>
    <ImageLightbox :url="previewUrl" @close="previewUrl = ''" />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import api from '@/api/client'
import ImageLightbox from '@/components/ImageLightbox.vue'

const props = defineProps({
  images: { type: Array, default: () => [] },
  sku: { type: String, default: '' },
  preferred: { type: String, default: '' },
  embedded: { type: Boolean, default: false },
})

const resolved = reactive({})
const failed = reactive({})
const objectUrls = []
const galleryObjectUrls = []
const loading = new Set()
const views = ref([])
const userIndex = ref(0)
const galleryIndex = ref(0)
const galleryShown = ref('')
const previewUrl = ref('')
const spinFrame = ref(null)
let swiped = false
let spinStartX = 0
let spinStartIndex = 0
let spinMoved = false
let spinning = false
let galleryToken = 0
const PRELOAD_RADIUS = 12

const userImages = computed(() =>
  [...(props.images || [])]
    .filter((image) => image.purpose === 'part' || !image.purpose)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)),
)
const currentUser = computed(() => userImages.value[userIndex.value] || null)
const currentView = computed(() => views.value[galleryIndex.value] || null)
const userSrc = computed(() => srcOf(currentUser.value?.preview_url))
const gallerySrc = computed(() => srcOf(currentView.value?.url))
const userPlaceholder = computed(() => placeholder(currentUser.value?.preview_url, '无原图'))
const galleryPlaceholder = computed(() => {
  if (!props.sku) return '暂无匹配产品'
  if (!views.value.length) return '暂无 360 图'
  return placeholder(currentView.value?.url, '暂无 360 图')
})
const userCaption = computed(() => `你的照片 ${userIndex.value + 1} / ${Math.max(userImages.value.length, 1)}`)
const galleryCaption = computed(() => {
  if (!views.value.length) return '暂无 360 图'
  return `${galleryIndex.value + 1} / ${views.value.length}`
})

function needsAuthFetch(url) {
  return typeof url === 'string' && url.startsWith('/api/')
}

function srcOf(url) {
  return url ? resolved[url] || '' : ''
}

function placeholder(url, emptyText) {
  if (!url) return emptyText
  if (failed[url]) return '图片加载失败'
  return '加载中'
}

async function loadUrl(url, token = null) {
  if (!url || resolved[url] || failed[url] || loading.has(url)) return
  if (!needsAuthFetch(url)) {
    resolved[url] = url
    return
  }
  loading.add(url)
  try {
    const blob = await api.get(url, { responseType: 'blob' })
    if (token !== null && token !== galleryToken) return
    if (!(blob instanceof Blob) || !blob.size) {
      failed[url] = true
      return
    }
    const objectUrl = URL.createObjectURL(blob)
    if (token !== null && token !== galleryToken) {
      URL.revokeObjectURL(objectUrl)
      return
    }
    if (token === null) objectUrls.push(objectUrl)
    else galleryObjectUrls.push(objectUrl)
    resolved[url] = objectUrl
  } catch {
    if (token === null || token === galleryToken) failed[url] = true
  } finally {
    loading.delete(url)
  }
}

function releaseGalleryImages() {
  galleryToken += 1
  const stale = galleryObjectUrls.splice(0, galleryObjectUrls.length)
  stale.forEach((url) => URL.revokeObjectURL(url))
  Object.keys(resolved).forEach((key) => {
    if (String(key).includes('/gallery/')) delete resolved[key]
  })
  Object.keys(failed).forEach((key) => {
    if (String(key).includes('/gallery/')) delete failed[key]
  })
}

function preferredIndex(items) {
  const preferredName = String(props.preferred || '').split('/').pop()
  if (!preferredName) return 0
  const index = items.findIndex((item) => item.name === preferredName)
  return index > 0 ? index : 0
}

function pixelsPerFrame() {
  const count = views.value.length || 1
  return Math.max(4, 648 / count)
}

function preloadAround(index) {
  const items = views.value
  const count = items.length
  if (!count) return
  const token = galleryToken
  const center = items[wrapIndex(index, count)]
  if (center?.url) loadUrl(center.url, token)
  const radius = Math.min(PRELOAD_RADIUS, count - 1)
  for (let offset = 1; offset <= radius; offset += 1) {
    const next = items[wrapIndex(index + offset, count)]
    const prev = items[wrapIndex(index - offset, count)]
    if (next?.url) loadUrl(next.url, token)
    if (prev?.url) loadUrl(prev.url, token)
  }
}

function stepUser(delta) {
  const count = userImages.value.length
  if (count < 2) return
  userIndex.value = (userIndex.value + delta + count) % count
}

function wrapIndex(index, count) {
  if (!count) return 0
  return ((index % count) + count) % count
}

function onSpinDown(event) {
  if (views.value.length < 2) return
  spinning = true
  spinMoved = false
  spinStartX = event.clientX
  spinStartIndex = galleryIndex.value
  event.currentTarget?.setPointerCapture?.(event.pointerId)
}

function onSpinMove(event) {
  if (!spinning) return
  const delta = event.clientX - spinStartX
  if (Math.abs(delta) > 3) spinMoved = true
  const count = views.value.length
  const offset = Math.trunc(delta / pixelsPerFrame())
  galleryIndex.value = wrapIndex(spinStartIndex - offset, count)
  if (spinMoved && event.cancelable) event.preventDefault()
}

function onSpinUp() {
  spinning = false
  if (spinMoved) swiped = true
}

function onWheel(event) {
  if (views.value.length < 2) return
  event.preventDefault()
  const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX
  if (!delta) return
  galleryIndex.value = wrapIndex(galleryIndex.value + (delta > 0 ? 1 : -1), views.value.length)
}

function onUserKey(event) {
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    stepUser(-1)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    stepUser(1)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    preview(userSrc.value)
  }
}

function onSpinKey(event) {
  const count = views.value.length
  if (!count) return
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    galleryIndex.value = wrapIndex(galleryIndex.value - 1, count)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    galleryIndex.value = wrapIndex(galleryIndex.value + 1, count)
  } else if (event.key === 'Home') {
    event.preventDefault()
    galleryIndex.value = 0
  } else if (event.key === 'End') {
    event.preventDefault()
    galleryIndex.value = count - 1
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    preview(galleryShown.value)
  }
}

function preview(src) {
  if (swiped) {
    swiped = false
    return
  }
  if (!src) return
  previewUrl.value = src
}

watch(
  userImages,
  (images) => {
    if (userIndex.value >= images.length) userIndex.value = 0
    images.forEach((image) => {
      if (image.preview_url) loadUrl(image.preview_url)
    })
  },
  { immediate: true },
)

watch(galleryIndex, (index) => {
  preloadAround(index)
})

watch(
  () => [props.sku, props.preferred],
  async () => {
    releaseGalleryImages()
    views.value = []
    galleryIndex.value = 0
    galleryShown.value = ''
    const sku = String(props.sku || '').trim()
    if (!sku) return
    const token = galleryToken
    try {
      const res = await api.get(`/api/v1/public/gallery/${encodeURIComponent(sku)}/views`)
      if (token !== galleryToken) return
      const items = Array.isArray(res.data) ? res.data : []
      const start = preferredIndex(items)
      views.value = items
      if (galleryIndex.value === start) preloadAround(start)
      else galleryIndex.value = start
    } catch {
      if (token === galleryToken) views.value = []
    }
  },
  { immediate: true },
)

watch(gallerySrc, (src) => {
  if (src) galleryShown.value = src
})

onBeforeUnmount(() => {
  objectUrls.forEach((url) => URL.revokeObjectURL(url))
  galleryObjectUrls.forEach((url) => URL.revokeObjectURL(url))
})
</script>

<style scoped>
.compare-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  color: #5b6775;
  font-size: 13px;
}

.compare-toolbar strong {
  color: #122033;
}

.compare {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}

.embedded .compare {
  margin-top: 8px;
}

.embedded .frame {
  aspect-ratio: auto;
  height: min(42vh, 460px);
}

.frame {
  position: relative;
  aspect-ratio: 1;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  cursor: zoom-in;
}

img,
.empty {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  text-align: center;
  font-size: 13px;
  color: #4b5563;
  background: #f3f4f6;
}

.caption {
  margin: 8px 0 0;
  font-size: 12px;
  color: #5b6775;
  text-align: center;
}

.frame.spin {
  touch-action: none;
  cursor: ew-resize;
  user-select: none;
}

.frame.spin img {
  pointer-events: none;
}

.spin-hint {
  position: absolute;
  left: 50%;
  bottom: 8px;
  transform: translateX(-50%);
  margin: 0;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.55);
  color: #fff;
  font-size: 12px;
  line-height: 20px;
  white-space: nowrap;
  pointer-events: none;
}

.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.55);
  color: #fff;
  font-size: 22px;
  line-height: 32px;
  padding: 0;
  cursor: pointer;
}

.prev {
  left: 8px;
}

.next {
  right: 8px;
}

@media (max-width: 720px) {
  .compare {
    grid-template-columns: 1fr;
  }
}
</style>
