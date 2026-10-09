<template>
  <div class="page">
    <section class="card">
      <van-steps :active="1" active-color="#2563eb">
        <van-step>上传找货</van-step>
        <van-step>确认品类</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
    </section>

    <QueryImageGallery :images="store.session?.images || []" />

    <section class="card">
      <h2 class="title-row"><span class="emoji" aria-hidden="true">🤖</span> 识别结果</h2>
      <p v-if="store.session?.recognition_mode === 'vision_fallback'" class="muted" style="margin-bottom: 8px">
        图库未直接命中产品，已改用品类识别；请确认品类后查询公司产品。
      </p>
      <template v-if="isAutoPart">
        <p v-if="result">
          最可能品类：<strong>{{ result.mapped_category_name || result.part_name }}</strong>
          （置信度 {{ Math.round((result.confidence || 0) * 100) }}%）
        </p>
        <p class="muted">{{ result?.reason || '暂无判断依据' }}</p>
        <van-tag v-if="confidenceLevel === 'high'" type="success">✅ 高置信度</van-tag>
        <van-tag v-else-if="confidenceLevel === 'mid'" type="warning">⚠️ 请确认候选</van-tag>
        <van-tag v-else type="danger">🆘 建议补拍或手动选择</van-tag>
      </template>
      <template v-else>
        <p class="title-row" style="color: #b91c1c; margin-bottom: 8px">
          <span class="emoji" aria-hidden="true">🚫</span> 未识别到汽配零件
        </p>
        <p v-if="result">
          识别为：<strong>{{ result.part_name || '非汽配内容' }}</strong>
        </p>
        <p class="muted">{{ rejectReason }}</p>
        <p class="muted">请拍摄汽车零配件实物照片（如散热器、冷凝器等），当前流程已终止。</p>
      </template>
    </section>

    <section v-if="isAutoPart" class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🧩</span> 候选品类 Top3</h3>
      <div
        v-for="(item, index) in candidates"
        :key="index"
        class="candidate"
        :class="{ active: selectedName === (item.category_name || item.name) }"
        @click="selectCandidate(item)"
      >
        <div>
          <div>{{ item.category_name || item.name }}</div>
          <div class="muted">原始名：{{ item.name }}</div>
        </div>
        <strong>{{ Math.round((item.confidence || 0) * 100) }}%</strong>
      </div>
      <van-field v-model="manualName" label="✏️ 手动填写" placeholder="若候选不准可手输品类" />
    </section>

    <section v-if="isAutoPart" class="card">
      <van-checkbox v-model="optimizationConsent" shape="square" @change="onConsentChange">
        ✅ 同意用于识别优化（可选）
      </van-checkbox>
      <van-button
        v-if="store.session?.optimization_consent"
        size="mini"
        plain
        type="warning"
        style="margin-top: 8px"
        @click="revokeConsent"
      >
        撤回授权
      </van-button>
    </section>

    <div class="bottom-bar">
      <van-button v-if="isAutoPart" type="primary" block round :loading="loading" @click="next">
        🔎 查询产品
      </van-button>
      <van-button v-else type="primary" block round @click="retake">
        📷 重新拍摄零件
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'

const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const selectedCode = ref('')
const selectedName = ref('')
const manualName = ref('')
const optimizationConsent = ref(Boolean(store.session?.optimization_consent))

const result = computed(() => store.session?.result)
const isAutoPart = computed(() => {
  if (store.session?.is_auto_part === false) return false
  if (store.session?.result?.is_auto_part === false) return false
  return true
})
const rejectReason = computed(
  () => store.session?.error_message || result.value?.reason || '图片内容不是汽配零件',
)
const candidates = computed(() => result.value?.candidates || [])
const confidenceLevel = computed(() => {
  const confidence = result.value?.confidence || 0
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'mid'
  return 'low'
})

function selectCandidate(item) {
  selectedCode.value = item.category_code || ''
  selectedName.value = item.category_name || item.name
  manualName.value = selectedName.value
}

async function onConsentChange(val) {
  try {
    await store.setConsent(val)
  } catch (err) {
    showToast(err?.message || '授权更新失败')
  }
}

async function revokeConsent() {
  await store.revokeConsent()
  optimizationConsent.value = false
  showToast('已撤回授权')
}

async function next() {
  if (!isAutoPart.value) {
    showToast('未识别到汽配零件，请重新拍摄')
    return
  }
  const name = manualName.value || selectedName.value
  const oeNumber = store.session?.oe_number || ''
  if (!name && !oeNumber) {
    showToast('请确认品类，或返回上一步填写 OE')
    return
  }
  loading.value = true
  try {
    if (name) {
      await store.confirmCategory({
        category_code: selectedCode.value || null,
        category_name: name,
        optimization_consent: optimizationConsent.value,
      })
    } else if (optimizationConsent.value !== Boolean(store.session?.optimization_consent)) {
      await store.setConsent(optimizationConsent.value)
    }
    await store.searchProducts()
    router.push('/products')
  } catch (err) {
    showToast(err?.message || err?.response?.data?.message || '查询失败')
  } finally {
    loading.value = false
  }
}

function retake() {
  router.replace('/')
}

onMounted(() => {
  if (!store.session) {
    router.replace('/')
    return
  }
  if (!isAutoPart.value || !result.value) return
  selectCandidate({
    category_code: result.value.mapped_category_code,
    category_name: result.value.mapped_category_name || result.value.part_name,
    name: result.value.part_name,
    confidence: result.value.confidence,
  })
})
</script>
