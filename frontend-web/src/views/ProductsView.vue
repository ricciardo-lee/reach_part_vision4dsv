<template>
  <div class="workbench products-workbench">
    <div class="summary" aria-label="本次识别摘要">
      <el-tag v-if="isSkuMatch" type="success">360 图库直匹配</el-tag>
      <el-tag v-else-if="isCategoryMatch" type="primary">已确认品类</el-tag>
      <el-tag v-else>品类查询</el-tag>
      <span v-if="isSkuMatch">SKU {{ matchedSku || '-' }}<template v-if="matchScore != null"> · 相似度 {{ matchScore }}</template></span>
      <span v-else>{{ categoryName || '-' }}<template v-if="visionAssisted"> · Vision 辅助</template></span>
      <span>候选 {{ store.products.length }}</span>
      <span>车型 {{ vehicleText }}</span>
      <span>OE {{ store.session?.oe_number || '未填写' }}</span>
    </div>

    <div class="workbench-split">
      <el-card class="pane list-pane" shadow="never">
        <template #header>候选产品</template>
        <div
          v-if="store.products.length"
          class="product-list"
          role="listbox"
          aria-label="匹配产品"
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
            <span class="muted">SKU {{ item.sku }}</span>
            <span class="muted">{{ item.fitment || '适配未填写' }}</span>
          </button>
        </div>
        <p v-else class="muted">暂无匹配产品。可返回修改品类、车型或 OE 后再试。</p>
      </el-card>

      <el-card class="pane detail-pane" shadow="never">
        <template #header>产品详情</template>
        <template v-if="activeProduct">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="名称">{{ activeProduct.name }}</el-descriptions-item>
            <el-descriptions-item label="价格">{{ activeProduct.price != null ? `¥${activeProduct.price}` : '-' }}</el-descriptions-item>
            <el-descriptions-item label="SKU">{{ activeProduct.sku }}</el-descriptions-item>
            <el-descriptions-item label="零件号">{{ partNumbers(activeProduct) }}</el-descriptions-item>
            <el-descriptions-item label="适配车型" :span="2">{{ activeProduct.fitment || '-' }}</el-descriptions-item>
            <el-descriptions-item label="匹配原因" :span="2">{{ activeProduct.match_reason || '匹配结果' }}</el-descriptions-item>
          </el-descriptions>
          <ImageCompare
            embedded
            :images="partImages"
            :sku="activeProduct.sku || ''"
            :preferred="preferredView"
          />
        </template>
        <p v-else class="muted">选择左侧候选后，这里显示详情和 360 图。</p>
        <div class="detail-actions">
          <el-button type="success" @click="feedback(true)">准确</el-button>
          <el-button type="danger" plain @click="feedback(false)">不准</el-button>
          <span class="spacer" />
          <el-button @click="goBack">返回调整</el-button>
          <el-button type="primary" @click="router.push('/')">再识一张</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useRecognitionStore } from '@/stores/recognition'
import ImageCompare from '@/components/ImageCompare.vue'

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
const categoryName = computed(
  () =>
    store.session?.retrieval?.selected_category_cn ||
    store.session?.confirmed_category_name ||
    store.products[0]?.category_name,
)
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
  return parts.length ? parts.join(' / ') : '未选择'
})

async function feedback(correct) {
  try {
    await store.sendFeedback(correct)
    ElMessage.success(correct ? '感谢反馈' : '已记录，我们会优化')
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
