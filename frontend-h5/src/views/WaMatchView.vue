<template>
  <div class="page wa-match-page">
    <section v-if="!store.session" class="card">
      <p class="muted">{{ t('waEntry.failed') }}</p>
    </section>
    <template v-else>
    <ImageCompare :images="partImages" :sku="activeProduct?.sku || ''" :preferred="preferredView" />

    <section class="card">
      <h2 class="title-row">{{ t('waMatch.title') }}</h2>
      <p class="muted" v-if="isSkuMatch">
        <van-tag type="success">{{ t('mode.skuMatchEmoji') }}</van-tag>
        · {{ t('products.skuLine', { sku: matchedSku || '-' }) }}
        <span v-if="matchScore != null"> · {{ t('products.similarity', { score: matchScore }) }}</span>
      </p>
      <p class="muted" v-else-if="isCategoryMatch">
        <van-tag type="primary">{{ t('mode.categoryMatchEmoji') }}</van-tag>
        · {{ categoryName || '-' }}
        <span v-if="visionAssisted"> · {{ t('products.visionAssisted') }}</span>
      </p>
      <p class="muted" v-else>
        {{ t('products.categoryLabel', { name: confirmedCategoryName || '-' }) }}
      </p>
      <p class="muted">
        {{ t('products.vehicleOeLine', { vehicle: vehicleText, oe: store.session?.oe_number || t('common.notFilled') }) }}
      </p>
      <p v-if="store.products.length > 1" class="muted">{{ t('waMatch.switchHint') }}</p>
    </section>

    <section class="card" v-if="store.products.length">
      <div
        v-for="item in store.products"
        :key="`${item.sku}-${item.attributes?.material_code || ''}`"
        class="product-item"
        :class="{ active: item.sku === activeProduct?.sku }"
        @click="activeSku = item.sku"
      >
        <div class="product-head">
          <strong>{{ item.name }}</strong>
        </div>
        <div class="muted">{{ t('products.skuLine', { sku: item.sku }) }}</div>
        <div class="muted">{{ t('products.fitment', { value: item.fitment || '-' }) }}</div>
        <div class="muted">{{ t('products.partNumbers', { value: partNumbers(item) }) }}</div>
        <van-tag plain type="primary">{{ item.match_reason || t('products.matchResult') }}</van-tag>
      </div>
    </section>

    <section class="card" v-else>
      <p class="title-row">{{ t('waMatch.emptyTitle') }}</p>
      <p class="muted">{{ t('waMatch.emptyHint') }}</p>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { categoryLabelKey } from '@shared/locales/index.js'
import { useRecognitionStore } from '@/stores/recognition'
import ImageCompare from '@/components/ImageCompare.vue'

const { t } = useI18n()
const store = useRecognitionStore()
const activeSku = ref('')

const partImages = computed(() =>
  (store.session?.images || []).filter((image) => image.purpose !== 'oe_label'),
)
const activeProduct = computed(
  () => store.products.find((item) => item.sku === activeSku.value) || store.products[0] || null,
)
const preferredView = computed(() => {
  const sku = activeProduct.value?.sku
  const candidates = store.session?.retrieval?.candidates || []
  const hit = candidates.find((item) => item.sku === sku)
  return hit?.matched_views?.[0] || ''
})

const isSkuMatch = computed(() => store.session?.recognition_mode === 'sku_match')
const isCategoryMatch = computed(() => store.session?.recognition_mode === 'category_match')
const matchedSku = computed(() => store.session?.retrieval?.matched_sku || store.products[0]?.sku)

function displayCategory(idOrName) {
  const key = categoryLabelKey(idOrName)
  return key ? t(key) : idOrName || ''
}

const categoryName = computed(() => {
  const raw =
    store.session?.retrieval?.selected_category_cn ||
    store.session?.confirmed_category_name ||
    store.products[0]?.category_name
  return displayCategory(raw)
})
const confirmedCategoryName = computed(() => displayCategory(store.session?.confirmed_category_name))
const visionAssisted = computed(() => Boolean(store.session?.retrieval?.vision_assisted))
const matchScore = computed(() => {
  const score = store.session?.retrieval?.score
  if (score == null) return null
  return Number(score).toFixed(3)
})
const vehicleText = computed(() => {
  const parts = [
    store.session?.vehicle_brand,
    store.session?.vehicle_model,
    store.session?.vehicle_year,
  ].filter(Boolean)
  return parts.length ? parts.join(' / ') : t('common.notSelected')
})

function partNumbers(item) {
  const refs = Array.isArray(item?.ref_nums) ? item.ref_nums.filter(Boolean) : []
  return refs[0] || '-'
}

watch(
  () => store.products.map((item) => item.sku).join('\n'),
  () => {
    const skus = store.products.map((item) => item.sku)
    if (skus.includes(activeSku.value)) return
    const matched = store.session?.retrieval?.matched_sku
    activeSku.value = skus.includes(matched) ? matched : skus[0] || ''
  },
  { immediate: true },
)
</script>

<style scoped>
.wa-match-page {
  padding-bottom: 24px;
}
.product-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.product-item {
  padding: 10px 0;
  border-bottom: 1px solid #e8edf5;
}
.product-item:last-child {
  border-bottom: 0;
}
.product-item.active {
  margin: 0 -8px;
  padding-left: 8px;
  padding-right: 8px;
  border-radius: 12px;
  background: #eff6ff;
}
</style>
