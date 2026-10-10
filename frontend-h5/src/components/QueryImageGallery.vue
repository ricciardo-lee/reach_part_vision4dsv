<template>
  <section v-if="partImages.length" class="card">
    <h3 class="title-row"><span class="emoji" aria-hidden="true">🖼️</span> {{ t('gallery.title') }}</h3>
    <p class="muted">{{ t('gallery.hintShort') }}</p>
    <div v-for="(image, index) in partImages" :key="image.id || index" class="pair">
      <figure>
        <img v-if="srcOf(image.preview_url)" :src="srcOf(image.preview_url)" :alt="t('gallery.originalAlt')" />
        <div v-else class="empty">{{ placeholder(image.preview_url, t('gallery.noOriginal')) }}</div>
        <figcaption>{{ t('gallery.original', { n: index + 1 }) }}</figcaption>
      </figure>
      <figure>
        <img
          v-if="srcOf(image.foreground_preview_url)"
          :src="srcOf(image.foreground_preview_url)"
          :alt="t('gallery.foregroundAlt')"
        />
        <div v-else class="empty">
          {{ placeholder(image.foreground_preview_url, t('gallery.fallbackFull')) }}
        </div>
        <figcaption>{{ sourceLabel(image.foreground_source) }}</figcaption>
      </figure>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { foregroundSourceKey } from '@shared/locales/index.js'
import api from '@/api/client'

const { t } = useI18n()

const props = defineProps({
  images: { type: Array, default: () => [] },
})

const resolved = reactive({})
const failed = reactive({})
const objectUrls = []

const partImages = computed(() =>
  [...(props.images || [])]
    .filter((img) => img.purpose === 'part' || !img.purpose)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)),
)

function needsAuthFetch(url) {
  return typeof url === 'string' && url.startsWith('/api/')
}

function srcOf(url) {
  return url ? resolved[url] || '' : ''
}

function placeholder(url, emptyText) {
  if (!url) return emptyText
  if (failed[url]) return t('common.imageLoadFailed')
  return t('common.loading')
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
    const urls = []
    images.forEach((image) => {
      if (image.preview_url) urls.push(image.preview_url)
      if (image.foreground_preview_url) urls.push(image.foreground_preview_url)
    })
    urls.forEach((url) => {
      loadUrl(url)
    })
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  objectUrls.forEach((url) => URL.revokeObjectURL(url))
})

function sourceLabel(source) {
  return t(foregroundSourceKey(source))
}
</script>

<style scoped>
.pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 12px;
}

figure {
  margin: 0;
}

img,
.empty {
  width: 100%;
  aspect-ratio: 1;
  object-fit: contain;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  font-size: 12px;
  text-align: center;
  background: #e5e7eb;
  color: #4b5563;
}

figcaption {
  margin-top: 4px;
  font-size: 12px;
  color: var(--rv-muted);
  text-align: center;
}
</style>
