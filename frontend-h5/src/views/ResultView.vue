<template>
  <div class="page">
    <section class="card">
      <van-steps :active="1" active-color="#1f6feb">
        <van-step>拍照上传</van-step>
        <van-step>确认品类</van-step>
        <van-step>车型/OE</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
    </section>

    <section class="card">
      <h2 class="title-row"><span class="emoji" aria-hidden="true">🤖</span> 识别结果</h2>
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
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🚗</span> 车型信息（可选）</h3>
      <van-field v-model="brand" is-link readonly label="品牌" placeholder="请选择" @click="openBrand" />
      <van-field v-model="series" is-link readonly label="车系" placeholder="请选择" @click="openSeries" />
      <van-field v-model="model" is-link readonly label="车型" placeholder="请选择" @click="openModels" />
      <van-field v-model="year" is-link readonly label="年款" placeholder="请选择" @click="openYears" />
    </section>

    <section v-if="isAutoPart" class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🔢</span> OE 零件号</h3>
      <van-field v-model="oeNumber" label="OE" placeholder="可手工输入 OE 号" @update:model-value="onOeEdit" />
      <van-uploader v-model="oeFiles" :max-count="1" accept="image/*" capture="environment" :after-read="onOeRead" />
      <van-button size="small" type="primary" plain style="margin-top: 8px" :loading="ocrLoading" @click="runOeOcr">
        🏷️ 识别铭牌 OE
      </van-button>
      <div v-if="store.oeOcrMeta" class="muted" style="margin-top: 8px">
        OCR 置信度 {{ Math.round((store.oeOcrMeta.confidence || 0) * 100) }}%
        <span v-if="store.oeOcrMeta.reason"> · {{ store.oeOcrMeta.reason }}</span>
      </div>
      <div v-if="store.oeCandidates.length" style="margin-top: 8px">
        <van-tag
          v-for="oe in store.oeCandidates"
          :key="oe"
          style="margin: 0 6px 6px 0"
          type="primary"
          @click="pickOe(oe)"
        >
          {{ oe }}
        </van-tag>
        <van-button
          size="small"
          type="success"
          block
          style="margin-top: 8px"
          :disabled="!oeNumber"
          :loading="confirmOeLoading"
          @click="confirmOe"
        >
          ✅ 确认 OE：{{ oeNumber || '请选择' }}
        </van-button>
        <p class="muted">使用铭牌候选时，请先点确认再查产品。</p>
        <p v-if="store.oeConfirmed" class="muted" style="color: #15803d">已确认 OE</p>
      </div>
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

    <van-popup v-model:show="showYear" position="bottom" round>
      <van-picker :columns="yearColumns" @confirm="onYear" @cancel="showYear = false" />
    </van-popup>

    <IndexedOptionSheet
      v-model:show="showBrand"
      title="选择品牌"
      :indexed="brandIndexed"
      @select="onBrandSelect"
    />
    <IndexedOptionSheet
      v-model:show="showSeries"
      title="选择车系"
      :indexed="seriesIndexed"
      @select="onSeriesSelect"
    />
    <IndexedOptionSheet
      v-model:show="showModel"
      title="选择车型"
      :indexed="modelIndexed"
      @select="onModelSelect"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import api from '@/api/client'
import { useRecognitionStore } from '@/stores/recognition'
import IndexedOptionSheet from '@/components/IndexedOptionSheet.vue'

const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const ocrLoading = ref(false)
const confirmOeLoading = ref(false)
const selectedCode = ref('')
const selectedName = ref('')
const manualName = ref('')
const brand = ref('')
const series = ref('')
const model = ref('')
const year = ref('')
const brandValue = ref('')
const seriesValue = ref('')
const modelValue = ref('')
const yearValue = ref('')
const oeNumber = ref('')
const oeFiles = ref([])
const oeFileObj = ref(null)
const usedOcrCandidate = ref(false)
const optimizationConsent = ref(Boolean(store.session?.optimization_consent))

const showBrand = ref(false)
const showSeries = ref(false)
const showModel = ref(false)
const showYear = ref(false)
const brandIndexed = ref({ letters: [], groups: [], items: [] })
const seriesIndexed = ref({ letters: [], groups: [], items: [] })
const modelIndexed = ref({ letters: [], groups: [], items: [] })
const yearColumns = ref([])

const emptyIndexed = () => ({ letters: [], groups: [], items: [] })

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
  const c = result.value?.confidence || 0
  if (c >= 0.8) return 'high'
  if (c >= 0.5) return 'mid'
  return 'low'
})

function selectCandidate(item) {
  selectedCode.value = item.category_code || ''
  selectedName.value = item.category_name || item.name
  manualName.value = selectedName.value
}

function onOeRead(item) {
  oeFileObj.value = item.file
}

function onOeEdit() {
  if (usedOcrCandidate.value) {
    usedOcrCandidate.value = store.oeCandidates.includes(oeNumber.value)
    if (!usedOcrCandidate.value) store.oeConfirmed = false
  }
}

function pickOe(oe) {
  oeNumber.value = oe
  usedOcrCandidate.value = true
  store.oeConfirmed = false
}

async function confirmOe() {
  if (!oeNumber.value) return showToast('请先选择或填写 OE')
  confirmOeLoading.value = true
  try {
    await store.confirmOe(oeNumber.value)
    usedOcrCandidate.value = true
    showToast('OE 已确认')
  } finally {
    confirmOeLoading.value = false
  }
}

async function runOeOcr() {
  if (!oeFileObj.value) {
    showToast('请先拍摄铭牌/包装图')
    return
  }
  ocrLoading.value = true
  try {
    await store.uploadImages([oeFileObj.value], 'oe_label', 0)
    await store.runOeOcr()
    if (store.oeCandidates[0]) {
      oeNumber.value = store.oeCandidates[0]
      usedOcrCandidate.value = true
    }
  } finally {
    ocrLoading.value = false
  }
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

async function loadBrands() {
  const res = await api.get('/api/v1/public/vehicle/brands/indexed')
  brandIndexed.value = res.data || emptyIndexed()
}

async function openBrand() {
  if (!brandIndexed.value.items?.length) await loadBrands()
  showBrand.value = true
}

async function openSeries() {
  if (!brandValue.value) return showToast('请先选择品牌')
  const res = await api.get('/api/v1/public/vehicle/series/indexed', {
    params: { brand: brandValue.value },
  })
  seriesIndexed.value = res.data || emptyIndexed()
  showSeries.value = true
}

async function openModels() {
  if (!seriesValue.value) return showToast('请先选择车系')
  const res = await api.get('/api/v1/public/vehicle/models/indexed', {
    params: { brand: brandValue.value, series: seriesValue.value },
  })
  modelIndexed.value = res.data || emptyIndexed()
  showModel.value = true
}

async function openYears() {
  if (!modelValue.value) return showToast('请先选择车型')
  const res = await api.get('/api/v1/public/vehicle/years', {
    params: { brand: brandValue.value, series: seriesValue.value, model: modelValue.value },
  })
  yearColumns.value = (res.data || []).map((i) => ({ text: i.label, value: i.value }))
  showYear.value = true
}

function onBrandSelect(item) {
  brand.value = item.label
  brandValue.value = item.value
  series.value = ''
  seriesValue.value = ''
  model.value = ''
  modelValue.value = ''
  year.value = ''
  yearValue.value = ''
  seriesIndexed.value = emptyIndexed()
  modelIndexed.value = emptyIndexed()
}

function onSeriesSelect(item) {
  series.value = item.label
  seriesValue.value = item.value
  model.value = ''
  modelValue.value = ''
  year.value = ''
  yearValue.value = ''
  modelIndexed.value = emptyIndexed()
}

function onModelSelect(item) {
  model.value = item.label
  modelValue.value = item.value
  year.value = ''
  yearValue.value = ''
}

function onYear({ selectedOptions }) {
  year.value = selectedOptions[0].text
  yearValue.value = selectedOptions[0].value
  showYear.value = false
}

async function next() {
  if (!isAutoPart.value) {
    showToast('未识别到汽配零件，请重新拍摄')
    return
  }
  const name = manualName.value || selectedName.value
  if (!name && !oeNumber.value) {
    showToast('请确认品类或填写 OE')
    return
  }
  if (store.oeCandidates.length && oeNumber.value && usedOcrCandidate.value && !store.oeConfirmed) {
    showToast('请先确认铭牌 OE 后再查询')
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
    const oeSource =
      store.oeCandidates.includes(oeNumber.value) || usedOcrCandidate.value ? 'ocr' : 'manual'
    await store.setVehicle({
      brand: brandValue.value || null,
      series: seriesValue.value || null,
      model: modelValue.value || null,
      year: yearValue.value || null,
      oe_number: oeNumber.value || null,
      oe_source: oeNumber.value ? oeSource : null,
    })
    if (oeNumber.value && oeSource === 'ocr' && !store.oeConfirmed) {
      await store.confirmOe(oeNumber.value)
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

onMounted(async () => {
  if (!store.session) {
    router.replace('/')
    return
  }
  if (!isAutoPart.value) return
  if (result.value) {
    selectCandidate({
      category_code: result.value.mapped_category_code,
      category_name: result.value.mapped_category_name || result.value.part_name,
      name: result.value.part_name,
      confidence: result.value.confidence,
    })
  }
  await loadBrands()
})
</script>
