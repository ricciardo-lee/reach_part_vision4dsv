<template>
  <div class="page">
    <section class="card">
      <van-steps :active="3" active-color="#1f6feb">
        <van-step>拍照上传</van-step>
        <van-step>确认品类</van-step>
        <van-step>车型/OE</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
    </section>

    <QueryImageGallery :images="store.session?.images || []" />

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
        · OE：{{ store.session?.oe_number || '-' }}
      </p>
    </section>

    <section class="card" v-if="store.products.length">
      <div v-for="item in store.products" :key="item.sku" class="product-item">
        <div style="display: flex; justify-content: space-between; gap: 8px">
          <strong>{{ item.name }}</strong>
          <span>💰 {{ item.price != null ? `¥${item.price}` : '-' }}</span>
        </div>
        <div class="muted">SKU：{{ item.sku }}</div>
        <div class="muted">适配：{{ item.fitment || '-' }}</div>
        <div class="muted">库存：{{ item.stock_status || '-' }}</div>
        <van-tag plain type="primary">🔎 {{ item.match_reason || '匹配结果' }}</van-tag>
      </div>
    </section>

    <section class="card" v-else>
      <p class="title-row"><span class="emoji">📭</span> 暂无匹配产品</p>
      <p class="muted">可返回修改品类、车型或 OE 后再试。</p>
    </section>

    <section v-if="isSkuMatch || isCategoryMatch" class="card">
      <p class="muted" v-if="isSkuMatch">若不是该产品，可改用原识别方式（品类确认 → 车型/OE → MDM 查询）。</p>
      <p class="muted" v-else>若品类不对或候选不准，可改用原识别方式重新确认品类。</p>
      <van-button type="warning" block plain :loading="fallbackLoading" @click="forceFallback">
        ↩️ 不是这个，改用原方式查询
      </van-button>
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
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showLoadingToast, closeToast, showToast } from 'vant'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'

const store = useRecognitionStore()
const router = useRouter()
const fallbackLoading = ref(false)

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

async function feedback(correct) {
  await store.sendFeedback(correct)
  showToast(correct ? '感谢反馈 🎉' : '已记录，我们会优化')
}

function goBack() {
  if (isSkuMatch.value || isCategoryMatch.value) {
    router.push('/')
    return
  }
  router.push('/result')
}

async function forceFallback() {
  fallbackLoading.value = true
  showLoadingToast({ message: '改用原识别方式…', forbidClick: true, duration: 0 })
  try {
    await store.forceVisionFallback()
    if (store.session?.status === 'failed') {
      showToast(store.session.error_message || '识别失败')
      return
    }
    if (store.session?.status !== 'done') {
      showToast('识别超时，请重试')
      return
    }
    router.replace('/result')
  } catch (err) {
    showToast(err?.message || err?.response?.data?.message || '切换失败')
  } finally {
    closeToast()
    fallbackLoading.value = false
  }
}

onMounted(() => {
  if (!store.session) router.replace('/')
})
</script>
