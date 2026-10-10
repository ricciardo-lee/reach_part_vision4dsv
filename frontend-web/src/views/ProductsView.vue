<template>
  <div class="workbench products-workbench">
    <div class="summary" :aria-label="t('products.summaryAria')">
      <el-tag v-if="isSkuMatch" type="success">{{ t('mode.skuMatch') }}</el-tag>
      <el-tag v-else-if="isCategoryMatch" type="primary">{{ t('mode.categoryMatch') }}</el-tag>
      <el-tag v-else>{{ t('products.categoryQuery') }}</el-tag>
      <span v-if="isSkuMatch">
        {{ t('products.skuLine', { sku: matchedSku || '-' }) }}
        <template v-if="matchScore != null"> · {{ t('products.similarity', { score: matchScore }) }}</template>
      </span>
      <span v-else>
        {{ categoryName || '-' }}
        <template v-if="visionAssisted"> · {{ t('products.visionAssisted') }}</template>
      </span>
      <span>{{ t('products.candidatesCount', { count: store.products.length }) }}</span>
      <span>{{ t('products.vehicleLabel', { vehicle: vehicleText }) }}</span>
      <span>{{ t('products.oeLabel', { oe: store.session?.oe_number || t('common.notFilled') }) }}</span>
    </div>

    <div class="workbench-split">
      <el-card class="pane list-pane" shadow="never">
        <template #header>{{ t('products.candidatesHeader') }}</template>
        <div
          v-if="store.products.length"
          class="product-list"
          role="listbox"
          :aria-label="t('products.matchProductsAria')"
          tabindex="0"
          @keydown="onProductKey"
        >
          <button
            v-for="item in store.products"
            :id="`product-${item.sku}`"
            :key="`${item.sku}-${item.attributes?.material_code || ''}`"
            type="button"
            class="product-item"
            role="option"
            :aria-selected="item.sku === activeProduct?.sku"
            :class="{ active: item.sku === activeProduct?.sku }"
            @click="activeSku = item.sku"
          >
            <span class="product-title">
              <strong>{{ item.name }}</strong>
              <span>{{ item.price != null ? `¥${item.price}` : '-' }}</span>
            </span>
            <span class="muted">{{ t('products.skuLine', { sku: item.sku }) }}</span>
            <span class="muted">{{ item.fitment || t('products.fitmentMissing') }}</span>
          </button>
        </div>
        <p v-else class="muted">{{ t('products.empty') }}</p>
      </el-card>

      <el-card class="pane detail-pane" shadow="never">
        <template #header>{{ t('products.detailHeader') }}</template>
        <template v-if="activeProduct">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item :label="t('products.name')">{{ activeProduct.name }}</el-descriptions-item>
            <el-descriptions-item :label="t('products.price')">{{
              activeProduct.price != null ? `¥${activeProduct.price}` : '-'
            }}</el-descriptions-item>
            <el-descriptions-item :label="t('products.sku')">{{ activeProduct.sku }}</el-descriptions-item>
            <el-descriptions-item :label="t('products.partNumber')">{{ partNumbers(activeProduct) }}</el-descriptions-item>
            <el-descriptions-item :label="t('products.fitmentField')" :span="2">{{
              activeProduct.fitment || '-'
            }}</el-descriptions-item>
            <el-descriptions-item :label="t('products.matchReason')" :span="2">{{
              activeProduct.match_reason || t('products.matchResult')
            }}</el-descriptions-item>
          </el-descriptions>
          <ImageCompare
            embedded
            :images="partImages"
            :sku="activeProduct.sku || ''"
            :preferred="preferredView"
          />
        </template>
        <p v-else class="muted">{{ t('products.pickHint') }}</p>
        <div class="detail-actions">
          <el-button type="success" @click="feedback(true)">{{ t('products.accurate') }}</el-button>
          <el-button type="danger" plain @click="feedback(false)">{{ t('products.inaccurate') }}</el-button>
          <span class="spacer" />
          <el-button @click="goBack">{{ t('products.back') }}</el-button>
          <el-button type="primary" @click="router.push('/')">{{ t('products.again') }}</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
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
const categoryName = computed(() => {
  const raw =
    store.session?.retrieval?.selected_category_cn ||
    store.session?.confirmed_category_name ||
    store.products[0]?.category_name
  if (!raw) return ''
  const key = categoryLabelKey(raw)
  return key ? t(key) : raw
})
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
  try {
    await store.sendFeedback(correct)
    ElMessage.success(correct ? t('products.thanks') : t('products.recorded'))
  } catch {
    // The API client already shows the error.
  }
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

function onProductKey(event) {
  const items = store.products
  if (!items.length) return
  const index = Math.max(0, items.findIndex((item) => item.sku === activeSku.value))
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const nextIndex = event.key === 'ArrowDown'
      ? Math.min(items.length - 1, index + 1)
      : Math.max(0, index - 1)
    activeSku.value = items[nextIndex].sku
    document.getElementById(`product-${activeSku.value}`)?.scrollIntoView({ block: 'nearest' })
  }
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
.products-workbench .workbench-split {
  grid-template-columns: 1fr;
}

@media (min-width: 1024px) {
  .products-workbench .workbench-split {
    grid-template-columns: 320px minmax(0, 1fr);
  }
}

.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 10px 14px;
  border: 1px solid #e4e8ee;
  border-radius: 12px;
  background: #fff;
  color: #344054;
  font-size: 13px;
}

.product-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.product-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e4e8ee;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.product-item.active {
  border-color: #93c5fd;
  background: #eff6ff;
}

.product-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}

.spacer {
  flex: 1;
}
</style>
