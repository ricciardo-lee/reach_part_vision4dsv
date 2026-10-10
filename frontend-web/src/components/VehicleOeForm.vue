<template>
  <el-form class="filter-form" label-position="top" @submit.prevent>
    <div class="section-head">
      <h3>{{ t('vehicle.title') }}</h3>
      <button type="button" class="link-button" :disabled="!vehicleFilled" @click="clearVehicle">{{ t('common.clear') }}</button>
    </div>
    <p v-if="catalogError" class="muted">{{ catalogError }}</p>
    <div class="vehicle-grid">
      <el-form-item :label="t('vehicle.brand')">
        <el-select
          v-model="brandValue"
          filterable
          clearable
          :placeholder="t('vehicle.brandPlaceholder')"
          :loading="brandLoading"
          @change="onBrandChange"
        >
          <el-option v-for="item in brandOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('vehicle.series')">
        <el-select
          v-model="seriesValue"
          filterable
          clearable
          :placeholder="t('vehicle.seriesPlaceholder')"
          :disabled="!brandValue"
          :loading="seriesLoading"
          @change="onSeriesChange"
        >
          <el-option v-for="item in seriesOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('vehicle.model')">
        <el-select
          v-model="modelValue"
          filterable
          clearable
          :placeholder="t('vehicle.modelPlaceholder')"
          :disabled="!seriesValue"
          :loading="modelLoading"
          @change="onModelChange"
        >
          <el-option v-for="item in modelOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('vehicle.year')">
        <el-select
          v-model="yearValue"
          filterable
          clearable
          :placeholder="t('vehicle.yearPlaceholder')"
          :disabled="!modelValue"
          :loading="yearLoading"
        >
          <el-option v-for="item in yearOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
    </div>

    <div class="section-head oe-head">
      <h3>{{ t('oe.title') }}</h3>
      <button type="button" class="link-button" :disabled="!oeFilled" @click="clearOe">{{ t('common.clear') }}</button>
    </div>
    <div class="oe-toolbar">
      <el-input
        id="oe-number"
        v-model="oeNumber"
        clearable
        :placeholder="t('oe.placeholder')"
        :aria-label="t('oe.label')"
        @input="onOeEdit"
      />
      <input ref="oeInput" class="sr-only" type="file" accept="image/*" @change="onOePick" />
      <el-button @click="oeInput?.click()">{{ t('oe.pickPlate') }}</el-button>
      <el-button :loading="ocrLoading" @click="runOeOcr">{{ t('oe.recognize') }}</el-button>
      <el-tag v-if="store.oeConfirmed" type="success">{{ t('oe.confirmed') }}</el-tag>
    </div>
    <div
      class="oe-drop"
      :class="{ over: oeDragOver }"
      @dragenter.prevent="onOeDragEnter"
      @dragover.prevent
      @dragleave.prevent="onOeDragLeave"
      @drop.prevent="onOeDrop"
    >
      <span class="muted">{{ t('oe.dropHint') }}</span>
      <img v-if="oePreview" :src="oePreview" :alt="t('oe.previewAlt')" />
    </div>
    <p v-if="store.oeOcrMeta" class="muted ocr-meta">
      {{ t('oe.confidence', { pct: Math.round((store.oeOcrMeta.confidence || 0) * 100) }) }}
      <span v-if="store.oeOcrMeta.reason"> · {{ store.oeOcrMeta.reason }}</span>
    </p>
    <div v-if="store.oeCandidates.length" class="candidates" role="list" :aria-label="t('oe.candidatesAria')">
      <button
        v-for="oe in store.oeCandidates"
        :key="oe"
        type="button"
        class="candidate"
        :class="{ active: oeNumber === oe }"
        :aria-pressed="oeNumber === oe"
        @click="pickOe(oe)"
      >
        {{ oe }}
      </button>
      <el-button type="success" :disabled="!oeNumber.trim()" :loading="confirmOeLoading" @click="confirmOe">
        {{ t('oe.confirm') }}
      </el-button>
    </div>
    <el-collapse v-if="store.oeCandidates.length" class="oe-note">
      <el-collapse-item :title="t('oe.howToUse')" name="oe">
        <p class="muted">{{ t('oe.confirmHint') }}</p>
      </el-collapse-item>
    </el-collapse>
  </el-form>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/api/client'
import { useRecognitionStore } from '@/stores/recognition'

const MAX_BYTES = 10 * 1024 * 1024
const { t } = useI18n()
const store = useRecognitionStore()
const ocrLoading = ref(false)
const confirmOeLoading = ref(false)
const brandLoading = ref(false)
const seriesLoading = ref(false)
const modelLoading = ref(false)
const yearLoading = ref(false)
const catalogError = ref('')
const brandValue = ref('')
const seriesValue = ref('')
const modelValue = ref('')
const yearValue = ref('')
const brandOptions = ref([])
const seriesOptions = ref([])
const modelOptions = ref([])
const yearOptions = ref([])
const oeNumber = ref('')
const oeFileObj = ref(null)
const oePreview = ref('')
const oeDragOver = ref(false)
const oeInput = ref(null)
const usedOcrCandidate = ref(false)
let oeDragDepth = 0

const vehicleFilled = computed(() =>
  Boolean(brandValue.value || seriesValue.value || modelValue.value || yearValue.value),
)
const oeFilled = computed(() =>
  Boolean(oeNumber.value.trim() || oeFileObj.value || store.oeCandidates.length || store.oeOcrMeta),
)

function indexedItems(data) {
  return data?.items || []
}

function hydrate() {
  const session = store.session || {}
  brandValue.value = session.vehicle_brand || ''
  seriesValue.value = session.vehicle_series || ''
  modelValue.value = session.vehicle_model || ''
  yearValue.value = session.vehicle_year || ''
  oeNumber.value = session.oe_number || ''
  usedOcrCandidate.value = session.oe_source === 'ocr' && Boolean(session.oe_number)
  if (usedOcrCandidate.value) store.oeConfirmed = true
}

function onOeEdit(value) {
  if (!usedOcrCandidate.value) return
  const text = String(value ?? '').trim()
  usedOcrCandidate.value = store.oeCandidates.includes(text)
  if (!usedOcrCandidate.value) store.oeConfirmed = false
}

function pickOe(oe) {
  oeNumber.value = oe
  usedOcrCandidate.value = true
  store.oeConfirmed = false
}

async function confirmOe() {
  if (!oeNumber.value.trim()) {
    ElMessage.warning(t('oe.needOe'))
    return
  }
  confirmOeLoading.value = true
  try {
    await store.confirmOe(oeNumber.value.trim())
    usedOcrCandidate.value = true
    ElMessage.success(t('oe.oeConfirmedToast'))
  } catch {
    // The API client already shows the error.
  } finally {
    confirmOeLoading.value = false
  }
}

async function ensureSession() {
  if (!store.session?.public_id) await store.createSession()
}

function replaceOeFile(file) {
  if (!file) return
  if (file.type && !file.type.startsWith('image/')) {
    ElMessage.warning(t('oe.needPlateImage'))
    return
  }
  if (file.size > MAX_BYTES) {
    ElMessage.warning(t('home.maxSize'))
    return
  }
  if (oePreview.value) URL.revokeObjectURL(oePreview.value)
  oeFileObj.value = file
  oePreview.value = URL.createObjectURL(file)
}

function onOePick(event) {
  const file = event.target.files?.[0]
  replaceOeFile(file)
  event.target.value = ''
}

function onOeDragEnter() {
  oeDragDepth += 1
  oeDragOver.value = true
}

function onOeDragLeave() {
  oeDragDepth = Math.max(0, oeDragDepth - 1)
  if (!oeDragDepth) oeDragOver.value = false
}

function onOeDrop(event) {
  oeDragDepth = 0
  oeDragOver.value = false
  replaceOeFile(event.dataTransfer?.files?.[0])
}

async function runOeOcr() {
  if (!oeFileObj.value) {
    ElMessage.warning(t('oe.needPlateFirst'))
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
  } catch {
    // The API client already shows the error.
  } finally {
    ocrLoading.value = false
  }
}

async function loadBrands() {
  brandLoading.value = true
  try {
    const res = await api.get('/api/v1/public/vehicle/brands/indexed')
    brandOptions.value = indexedItems(res.data)
    catalogError.value = ''
  } catch {
    catalogError.value = t('vehicle.catalogUnavailable')
  } finally {
    brandLoading.value = false
  }
}

async function loadSeries() {
  if (!brandValue.value) return
  seriesLoading.value = true
  try {
    const res = await api.get('/api/v1/public/vehicle/series/indexed', { params: { brand: brandValue.value } })
    seriesOptions.value = indexedItems(res.data)
  } finally {
    seriesLoading.value = false
  }
}

async function loadModels() {
  if (!seriesValue.value) return
  modelLoading.value = true
  try {
    const res = await api.get('/api/v1/public/vehicle/models/indexed', {
      params: { brand: brandValue.value, series: seriesValue.value },
    })
    modelOptions.value = indexedItems(res.data)
  } finally {
    modelLoading.value = false
  }
}

async function loadYears() {
  if (!modelValue.value) return
  yearLoading.value = true
  try {
    const res = await api.get('/api/v1/public/vehicle/years', {
      params: { brand: brandValue.value, series: seriesValue.value, model: modelValue.value },
    })
    yearOptions.value = res.data || []
  } finally {
    yearLoading.value = false
  }
}

async function onBrandChange() {
  seriesValue.value = ''
  modelValue.value = ''
  yearValue.value = ''
  seriesOptions.value = []
  modelOptions.value = []
  yearOptions.value = []
  if (!brandValue.value) return
  try {
    await loadSeries()
  } catch {
    // The API client already shows the error.
  }
}

async function onSeriesChange() {
  modelValue.value = ''
  yearValue.value = ''
  modelOptions.value = []
  yearOptions.value = []
  if (!seriesValue.value) return
  try {
    await loadModels()
  } catch {
    // The API client already shows the error.
  }
}

async function onModelChange() {
  yearValue.value = ''
  yearOptions.value = []
  if (!modelValue.value) return
  try {
    await loadYears()
  } catch {
    // The API client already shows the error.
  }
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
    ElMessage.warning(t('oe.needConfirm'))
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
  brandValue.value = ''
  seriesValue.value = ''
  modelValue.value = ''
  yearValue.value = ''
  seriesOptions.value = []
  modelOptions.value = []
  yearOptions.value = []
}

function clearOe() {
  oeNumber.value = ''
  oeFileObj.value = null
  if (oePreview.value) URL.revokeObjectURL(oePreview.value)
  oePreview.value = ''
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
  await loadBrands()
  try {
    if (brandValue.value) await loadSeries()
    if (seriesValue.value) await loadModels()
    if (modelValue.value) await loadYears()
  } catch {
    // The API client already shows the error.
  }
})

onBeforeUnmount(() => {
  if (oePreview.value) URL.revokeObjectURL(oePreview.value)
})

defineExpose({
  submit,
  clear,
  validateOe,
  getOeNumber: () => oeNumber.value.trim(),
})
</script>

<style scoped>
.filter-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.section-head h3 {
  margin: 0;
  font-size: 15px;
}

.oe-head {
  margin-top: 16px;
}

.vehicle-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px 10px;
}

.el-select,
.el-input {
  width: 100%;
}

.oe-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.oe-toolbar .el-input {
  flex: 1 1 180px;
}

.oe-drop {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  margin-top: 8px;
  padding: 8px 12px;
  border: 1px dashed #c5ced8;
  border-radius: 8px;
  background: #f8fafc;
}

.oe-drop.over {
  border-color: var(--el-color-primary);
  background: #eff6ff;
}

.oe-drop img {
  width: 48px;
  height: 48px;
  object-fit: contain;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.ocr-meta,
.candidates {
  margin-top: 8px;
}

.candidates {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.candidate {
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  cursor: pointer;
  padding: 6px 12px;
}

.candidate.active {
  background: #1d4ed8;
  color: #fff;
}

.oe-note {
  margin-top: 8px;
  border: 0;
}

@media (max-width: 1280px) {
  .vehicle-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 720px) {
  .vehicle-grid {
    grid-template-columns: 1fr;
  }
}
</style>
