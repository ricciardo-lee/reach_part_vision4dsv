<template>
  <div>
    <section class="card">
      <div class="section-head">
        <h3>{{ t('vehicle.title') }}</h3>
        <button type="button" class="clear-btn" :disabled="!vehicleFilled" @click="clearVehicle">
          {{ t('common.clear') }}
        </button>
      </div>
      <van-field
        v-model="brand"
        is-link
        readonly
        :label="t('vehicle.brand')"
        :placeholder="t('common.pleaseSelect')"
        @click="openBrand"
      />
      <van-field
        v-model="series"
        is-link
        readonly
        :label="t('vehicle.series')"
        :placeholder="t('common.pleaseSelect')"
        @click="openSeries"
      />
      <van-field
        v-model="model"
        is-link
        readonly
        :label="t('vehicle.model')"
        :placeholder="t('common.pleaseSelect')"
        @click="openModels"
      />
      <van-field
        v-model="year"
        is-link
        readonly
        :label="t('vehicle.year')"
        :placeholder="t('common.pleaseSelect')"
        @click="openYears"
      />
    </section>

    <section class="card">
      <div class="section-head">
        <h3>{{ t('oe.title') }}</h3>
        <button type="button" class="clear-btn" :disabled="!oeFilled" @click="clearOe">
          {{ t('common.clear') }}
        </button>
      </div>
      <van-field
        v-model="oeNumber"
        :label="t('oe.label')"
        :placeholder="t('oe.placeholder')"
        @update:model-value="onOeEdit"
      />
      <van-uploader v-model="oeFiles" :max-count="1" accept="image/*" capture="environment" :after-read="onOeRead" />
      <van-button size="small" type="primary" plain style="margin-top: 8px" :loading="ocrLoading" @click="runOeOcr">
        {{ t('oe.recognizeEmoji') }}
      </van-button>
      <div v-if="store.oeOcrMeta" class="muted" style="margin-top: 8px">
        {{ t('oe.confidence', { pct: Math.round((store.oeOcrMeta.confidence || 0) * 100) }) }}
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
          ✅ {{ t('oe.confirmWithValue', { value: oeNumber || t('oe.pleasePick') }) }}
        </van-button>
        <p class="muted">{{ t('oe.confirmHintShort') }}</p>
        <p v-if="store.oeConfirmed" class="muted" style="color: #15803d">{{ t('oe.confirmed') }}</p>
      </div>
    </section>

    <van-popup v-model:show="showYear" position="bottom" round>
      <van-picker :columns="yearColumns" @confirm="onYear" @cancel="showYear = false" />
    </van-popup>
    <IndexedOptionSheet
      v-model:show="showBrand"
      :title="t('vehicle.selectBrand')"
      :indexed="brandIndexed"
      @select="onBrandSelect"
    />
    <IndexedOptionSheet
      v-model:show="showSeries"
      :title="t('vehicle.selectSeries')"
      :indexed="seriesIndexed"
      @select="onSeriesSelect"
    />
    <IndexedOptionSheet
      v-model:show="showModel"
      :title="t('vehicle.selectModel')"
      :indexed="modelIndexed"
      @select="onModelSelect"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { showToast } from 'vant'
import api from '@/api/client'
import { useRecognitionStore } from '@/stores/recognition'
import IndexedOptionSheet from '@/components/IndexedOptionSheet.vue'

const { t } = useI18n()
const store = useRecognitionStore()
const ocrLoading = ref(false)
const confirmOeLoading = ref(false)
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

const showBrand = ref(false)
const showSeries = ref(false)
const showModel = ref(false)
const showYear = ref(false)
const brandIndexed = ref({ letters: [], groups: [], items: [] })
const seriesIndexed = ref({ letters: [], groups: [], items: [] })
const modelIndexed = ref({ letters: [], groups: [], items: [] })
const yearColumns = ref([])

const emptyIndexed = () => ({ letters: [], groups: [], items: [] })
const vehicleFilled = computed(() =>
  Boolean(brandValue.value || seriesValue.value || modelValue.value || yearValue.value),
)
const oeFilled = computed(() =>
  Boolean(
    oeNumber.value.trim() ||
      oeFiles.value.length ||
      oeFileObj.value ||
      store.oeCandidates.length ||
      store.oeOcrMeta,
  ),
)

function yearLabel(value) {
  const text = String(value || '')
  if (!text) return ''
  if (text.endsWith('款') || !/^\d+$/.test(text)) return text
  return t('vehicle.yearSuffix', { year: text })
}

function hydrate() {
  const session = store.session || {}
  brand.value = session.vehicle_brand || ''
  brandValue.value = session.vehicle_brand || ''
  series.value = session.vehicle_series || ''
  seriesValue.value = session.vehicle_series || ''
  model.value = session.vehicle_model || ''
  modelValue.value = session.vehicle_model || ''
  yearValue.value = session.vehicle_year || ''
  year.value = yearLabel(session.vehicle_year)
  oeNumber.value = session.oe_number || ''
  usedOcrCandidate.value = session.oe_source === 'ocr' && Boolean(session.oe_number)
  if (usedOcrCandidate.value) store.oeConfirmed = true
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
  if (!oeNumber.value) return showToast(t('oe.needOe'))
  confirmOeLoading.value = true
  try {
    await store.confirmOe(oeNumber.value)
    usedOcrCandidate.value = true
    showToast(t('oe.oeConfirmedToast'))
  } finally {
    confirmOeLoading.value = false
  }
}

async function ensureSession() {
  if (!store.session?.public_id) await store.createSession()
}

async function runOeOcr() {
  if (!oeFileObj.value) {
    showToast(t('oe.needPlateImageShort'))
    return
  }
  ocrLoading.value = true
  try {
    await ensureSession()
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

async function loadBrands() {
  const res = await api.get('/api/v1/public/vehicle/brands/indexed')
  brandIndexed.value = res.data || emptyIndexed()
}

async function openBrand() {
  if (!brandIndexed.value.items?.length) await loadBrands()
  showBrand.value = true
}

async function openSeries() {
  if (!brandValue.value) return showToast(t('vehicle.needBrand'))
  const res = await api.get('/api/v1/public/vehicle/series/indexed', { params: { brand: brandValue.value } })
  seriesIndexed.value = res.data || emptyIndexed()
  showSeries.value = true
}

async function openModels() {
  if (!seriesValue.value) return showToast(t('vehicle.needSeries'))
  const res = await api.get('/api/v1/public/vehicle/models/indexed', {
    params: { brand: brandValue.value, series: seriesValue.value },
  })
  modelIndexed.value = res.data || emptyIndexed()
  showModel.value = true
}

async function openYears() {
  if (!modelValue.value) return showToast(t('vehicle.needModel'))
  const res = await api.get('/api/v1/public/vehicle/years', {
    params: { brand: brandValue.value, series: seriesValue.value, model: modelValue.value },
  })
  yearColumns.value = (res.data || []).map((item) => ({ text: item.label, value: item.value }))
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

function currentPayload() {
  const oe = oeNumber.value.trim()
  const oeSource = !oe ? null : usedOcrCandidate.value || store.oeCandidates.includes(oe) ? 'ocr' : 'manual'
  return {
    brand: brandValue.value || null,
    series: seriesValue.value || null,
    model: modelValue.value || null,
    year: yearValue.value || null,
    oe_number: oe || null,
    oe_source: oe ? oeSource : null,
  }
}

function validateOe() {
  const oe = oeNumber.value.trim()
  if (store.oeCandidates.length && oe && usedOcrCandidate.value && !store.oeConfirmed) {
    showToast(t('oe.needConfirm'))
    return false
  }
  return true
}

async function submit() {
  if (!validateOe()) return false
  const payload = currentPayload()
  await store.setVehicle(payload)
  if (payload.oe_number && payload.oe_source === 'ocr' && !store.oeConfirmed) {
    await store.confirmOe(payload.oe_number)
  }
  return true
}

function clearVehicle() {
  brand.value = ''
  brandValue.value = ''
  series.value = ''
  seriesValue.value = ''
  model.value = ''
  modelValue.value = ''
  year.value = ''
  yearValue.value = ''
  seriesIndexed.value = emptyIndexed()
  modelIndexed.value = emptyIndexed()
  yearColumns.value = []
}

function clearOe() {
  oeNumber.value = ''
  oeFiles.value = []
  oeFileObj.value = null
  usedOcrCandidate.value = false
  store.oeCandidates = []
  store.oeOcrMeta = null
  store.oeConfirmed = false
}

async function clear() {
  clearVehicle()
  clearOe()
  if (store.session?.public_id) {
    await store.setVehicle({
      brand: null,
      series: null,
      model: null,
      year: null,
      oe_number: null,
      oe_source: null,
    })
  }
}

onMounted(async () => {
  hydrate()
  try {
    await loadBrands()
  } catch (err) {
    showToast(err?.message || t('vehicle.catalogUnavailable'))
  }
})

defineExpose({
  submit,
  clear,
  validateOe,
  getOeNumber: () => oeNumber.value.trim(),
})
</script>

<style scoped>
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

h3 {
  margin: 0;
  font-size: 16px;
}

.clear-btn {
  border: 0;
  background: transparent;
  color: #2563eb;
  font-size: 13px;
  line-height: 1;
  padding: 4px 0;
}

.clear-btn:disabled {
  color: #9ca3af;
}
</style>
