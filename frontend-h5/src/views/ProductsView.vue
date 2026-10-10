<template>
  <div class="page">
    <section class="card">
      <van-steps :active="2" active-color="#2563eb">
        <van-step>{{ t('steps.upload') }}</van-step>
        <van-step>{{ t('steps.confirm') }}</van-step>
        <van-step>{{ t('steps.products') }}</van-step>
      </van-steps>
    </section>

    <ImageCompare :images="partImages" :sku="activeProduct?.sku || ''" :preferred="preferredView" />

    <section class="card">
      <h2 class="title-row"><span class="emoji" aria-hidden="true">📦</span> {{ t('products.title') }}</h2>
      <p class="muted" v-if="isSkuMatch">
        <van-tag type="success">{{ t('mode.skuMatchEmoji') }}</van-tag>
        · {{ t('products.skuLine', { sku: matchedSku || '-' }) }}
        <span v-if="matchScore != null"> · {{ t('products.similarity', { score: matchScore }) }}</span>
      </p>
      <p class="muted" v-else-if="isCategoryMatch">
        <van-tag type="primary">{{ t('mode.categoryMatchEmoji') }}</van-tag>
        · {{ categoryName || '-' }}
        <span v-if="visionAssisted"> · {{ t('products.visionAssisted') }}</span>
        <br />
        {{ t('products.awaitingPick', { count: store.products.length }) }}
      </p>
      <p class="muted" v-else>
        {{ t('products.categoryLabel', { name: confirmedCategoryName || '-' }) }}
      </p>
      <p class="muted">
        {{ t('products.vehicleOeLine', { vehicle: vehicleText, oe: store.session?.oe_number || t('common.notFilled') }) }}
      </p>
      <p v-if="store.products.length > 1" class="muted">{{ t('products.switchHint') }}</p>
    </section>

    <section class="card" v-if="store.products.length">
      <div
        v-for="item in store.products"
        :key="`${item.sku}-${item.attributes?.material_code || ''}`"
        class="product-item"
        :class="{ active: item.sku === activeProduct?.sku }"
        @click="activeSku = item.sku"
      >
        <div style="display: flex; justify-content: space-between; gap: 8px">
          <strong>{{ item.name }}</strong>
          <span>💰 {{ item.price != null ? `¥${item.price}` : '-' }}</span>
        </div>
        <div class="muted">{{ t('products.skuLine', { sku: item.sku }) }}</div>
        <div class="muted">{{ t('products.fitment', { value: item.fitment || '-' }) }}</div>
        <div class="muted">{{ t('products.partNumbers', { value: partNumbers(item) }) }}</div>
        <van-tag plain type="primary">🔎 {{ item.match_reason || t('products.matchResult') }}</van-tag>
      </div>
    </section>

    <section class="card" v-else>
      <p class="title-row"><span class="emoji">📭</span> {{ t('products.emptyTitle') }}</p>
      <p class="muted">{{ t('products.emptyHint') }}</p>
    </section>

    <section class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🗣️</span> {{ t('products.feedbackTitle') }}</h3>
      <div style="display: flex; gap: 8px">
        <van-button type="success" block @click="feedback(true)">{{ t('products.accurateEmoji') }}</van-button>
        <van-button type="danger" block plain @click="feedback(false)">{{ t('products.inaccurateEmoji') }}</van-button>
      </div>
    </section>

    <div class="bottom-bar" style="display: flex; gap: 8px">
      <van-button block round @click="goBack">{{ t('products.backEmoji') }}</van-button>
      <van-button type="primary" block round @click="$router.push('/')">{{ t('products.againEmoji') }}</van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { categoryLabelKey } from '@shared/locales/index.js'
import { useRecognitionStore } from '@/stores/recognition'
import ImageCompare from '@/components/ImageCompare.vue'

const { t } = useI18n()
const store = useRecognitionStore()
const router = useRouter()
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
    store.session?.vehicle_series,
    store.session?.vehicle_model,
    store.session?.vehicle_year,
  ].filter(Boolean)
  return parts.length ? parts.join(' / ') : t('common.notSelected')
})

async function feedback(correct) {
  await store.sendFeedback(correct)
  showToast(correct ? t('products.thanksEmoji') : t('products.recorded'))
}

function partNumbers(item) {
  const refs = Array.isArray(item?.ref_nums) ? item.ref_nums.filter(Boolean) : []
  return refs[0] || '-'
}

function goBack() {
  if (isSkuMatch.value || isCategoryMatch.value) {
    router.push('/')
    return
  }
  router.push('/result')
}

onMounted(() => {
  if (!store.session) router.replace('/')
})

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
.product-item.active {
  margin: 0 -8px;
  padding-left: 8px;
  padding-right: 8px;
  border-radius: 12px;
  background: #eff6ff;
}
</style>
