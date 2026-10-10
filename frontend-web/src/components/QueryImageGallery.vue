<template>
  <section v-if="partImages.length" class="gallery" :class="{ panel: !bare, workbench }">
    <div v-if="!workbench" class="section-head">
      <h3>本次检索图片</h3>
    </div>
    <p v-if="!workbench" class="muted">左侧是上传原图。右侧是去掉背景并补成白底后，实际用来检索匹配的图片。点击图片可放大。</p>

    <div v-if="workbench" class="thumbs" role="tablist" aria-label="检索图片">
      <button
        v-for="(image, index) in partImages"
        :key="image.id || index"
        type="button"
        role="tab"
        :aria-selected="index === activeIndex"
        :class="{ active: index === activeIndex }"
        @click="activeIndex = index"
      >
        <img v-if="srcOf(image.preview_url)" :src="srcOf(image.preview_url)" :alt="`原图 ${index + 1}`" />
        <span v-else>{{ index + 1 }}</span>
      </button>
    </div>

    <div v-for="(image, index) in visibleImages" :key="image.id || index" class="pair">
      <figure>
        <button type="button" class="frame" :disabled="!srcOf(image.preview_url)" @click="open(image.preview_url)">
          <img v-if="srcOf(image.preview_url)" :src="srcOf(image.preview_url)" alt="上传原图" />
          <span v-else class="empty">{{ placeholder(image.preview_url, '无原图') }}</span>
        </button>
        <figcaption>原图 {{ displayIndex(index) }}</figcaption>
      </figure>
      <figure>
        <button
          type="button"
          class="frame"
          :disabled="!srcOf(image.foreground_preview_url)"
          @click="open(image.foreground_preview_url)"
        >
          <img
            v-if="srcOf(image.foreground_preview_url)"
            :src="srcOf(image.foreground_preview_url)"
            alt="去背景检索图"
          />
          <span v-else class="empty">{{ placeholder(image.foreground_preview_url, '未能去掉背景，检索使用原图') }}</span>
        </button>
        <figcaption>{{ sourceLabel(image.foreground_source) }}</figcaption>
      </figure>
    </div>
    <ImageLightbox :url="previewUrl" :urls="previewUrls" @close="previewUrl = ''" />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import api from '@/api/client'
import ImageLightbox from '@/components/ImageLightbox.vue'

const props = defineProps({
  images: { type: Array, default: () => [] },
  bare: { type: Boolean, default: false },
  workbench: { type: Boolean, default: false },
})

const resolved = reactive({})
const failed = reactive({})
const objectUrls = []
const previewUrl = ref('')
const activeIndex = ref(0)

const partImages = computed(() =>
  [...(props.images || [])]
    .filter((img) => img.purpose === 'part' || !img.purpose)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)),
)
const visibleImages = computed(() => {
  if (!props.workbench) return partImages.value
  const image = partImages.value[activeIndex.value] || partImages.value[0]
  return image ? [image] : []
})

const previewUrls = computed(() =>
  partImages.value
    .flatMap((image) => [srcOf(image.preview_url), srcOf(image.foreground_preview_url)])
    .filter(Boolean),
)

watch(
  () => partImages.value.length,
  (length) => {
    if (activeIndex.value >= length) activeIndex.value = Math.max(0, length - 1)
  },
)

function displayIndex(index) {
  return props.workbench ? activeIndex.value + 1 : index + 1
}

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

function open(url) {
  const src = srcOf(url)
  if (src) previewUrl.value = src
}

async function loadUrl(url) {
  if (!url || resolved[url] || failed[url]) return
  if (!needsAuthFetch(url)) {
    resolved[url] = url
    return
  }
  try {
    const blob = await api.get(url, { responseType: 'blob' })
    if (!(blob instanceof Blob) || !blob.size) {
      failed[url] = true
      return
    }
    const objectUrl = URL.createObjectURL(blob)
    objectUrls.push(objectUrl)
    resolved[url] = objectUrl
  } catch {
    failed[url] = true
  }
}

watch(
  partImages,
  (images) => {
    images.forEach((image) => {
      if (image.preview_url) loadUrl(image.preview_url)
      if (image.foreground_preview_url) loadUrl(image.foreground_preview_url)
    })
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  objectUrls.forEach((url) => URL.revokeObjectURL(url))
})

function sourceLabel(source) {
  if (source === 'birefnet' || source === 'sam_guided') return '用于检索匹配'
  if (source === 'heuristic_fallback') return '未能去掉背景，检索使用原图裁剪'
  if (source === 'full_only') return '未能去掉背景，检索使用原图'
  return '用于检索匹配'
}
</script>

<style scoped>
.thumbs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  overflow-x: auto;
}

.thumbs button {
  flex: 0 0 72px;
  height: 72px;
  padding: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  overflow: hidden;
}

.thumbs button.active {
  border-color: var(--el-color-primary);
}

.thumbs img,
.thumbs span {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}

figure {
  margin: 0;
}

.frame {
  display: block;
  width: 100%;
  padding: 0;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: zoom-in;
}

.frame:disabled {
  cursor: default;
}

img,
.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  aspect-ratio: 1;
  object-fit: contain;
  background: #fff;
}

.workbench .pair {
  flex: 1;
  min-height: 0;
  margin-top: 0;
  align-items: stretch;
}

.workbench figure {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.workbench .frame {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.workbench img,
.workbench .empty {
  aspect-ratio: auto;
  width: 100%;
  height: 100%;
  max-height: 100%;
  min-height: 140px;
}

.empty {
  padding: 8px;
  font-size: 12px;
  text-align: center;
  background: #f3f4f6;
  color: #4b5563;
}

figcaption {
  margin-top: 6px;
  font-size: 12px;
  color: #5b6775;
  text-align: center;
}

.section-head h3 {
  margin: 0;
  font-size: 16px;
}
</style>
