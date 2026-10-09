<template>
  <div class="page">
    <section class="card">
      <van-steps :active="2" active-color="#2563eb">
        <van-step>上传找货</van-step>
        <van-step>确认品类</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
    </section>

    <ImageCompare :images="partImages" :sku="activeProduct?.sku || ''" :preferred="preferredView" />

    <section class="card">
      <h2 class="title-row"><span class="emoji" aria-hidden="true">📦</span> 匹配产品</h2>
      <p class="muted" v-if="isSkuMatch">
        <van-tag type="success">🎯 360 图库直匹配</van-tag>
        · SKU：{{ matchedSku || '-' }}
        <span v-if="matchScore != null"> · 相似度 {{ matchScore }}</span>
      </p>
      <p class="muted" v-else-if="isCategoryMatch">
        <van-tag type="primary">📁 已确认品类</van-tag>
        · {{ categoryName || '-' }}
        <span v-if="visionAssisted"> · Vision 辅助</span>
        <br />
        待选择具体产品（共 {{ store.products.length }} 个候选）
      </p>
      <p class="muted" v-else>
        品类：{{ store.session?.confirmed_category_name || '-' }}
      </p>
      <p class="muted">车型：{{ vehicleText }} · OE：{{ store.session?.oe_number || '未填写' }}</p>
      <p v-if="store.products.length > 1" class="muted">点下面的产品，可切换右侧对照的 360 图。</p>
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
        <div class="muted">SKU：{{ item.sku }}</div>
        <div class="muted">适配：{{ item.fitment || '-' }}</div>
        <div class="muted">零件号：{{ partNumbers(item) }}</div>
        <van-tag plain type="primary">🔎 {{ item.match_reason || '匹配结果' }}</van-tag>
      </div>
    </section>

    <section class="card" v-else>
      <p class="title-row"><span class="emoji">📭</span> 暂无匹配产品</p>
      <p class="muted">可返回修改品类、车型或 OE 后再试。</p>
    </section>

    <section class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🗣️</span> 本次识别准确吗？</h3>
      <div style="display: flex; gap: 8px">
        <van-button type="success" block @click="feedback(true)">👍 准确</van-button>
        <van-button type="danger" block plain @click="feedback(false)">👎 不准</van-button>
      </div>
    </section>

    <div class="bottom-bar" style="display: flex; gap: 8px">
      <van-button block round @click="goBack">↩️ 返回调整</van-button>
      <van-button type="primary" block round @click="$router.push('/')">📷 再识一张</van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
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
  await store.sendFeedback(correct)
  showToast(correct ? '感谢反馈 🎉' : '已记录，我们会优化')
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
