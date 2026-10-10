<template>
  <div class="workbench result-workbench">
    <el-alert
      v-if="store.session?.recognition_mode === 'vision_fallback'"
      type="info"
      :closable="false"
      show-icon
      :title="t('result.visionFallbackHint')"
    />

    <div class="workbench-split">
      <el-card class="pane" shadow="never">
        <template #header>{{ t('result.galleryHeader') }}</template>
        <QueryImageGallery workbench bare :images="store.session?.images || []" />
        <p v-if="!partCount" class="muted">{{ t('result.noGallery') }}</p>
      </el-card>

      <el-card class="pane" shadow="never">
        <template #header>{{ t('result.confirmHeader') }}</template>
        <template v-if="isAutoPart">
          <el-descriptions v-if="result" :column="1" border size="small">
            <el-descriptions-item :label="t('result.topCategory')">
              {{ categoryLabel(result.mapped_category_name || result.part_name) || '-' }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('result.confidence')">
              {{ Math.round((result.confidence || 0) * 100) }}%
              <el-tag v-if="confidenceLevel === 'high'" type="success" size="small">{{ t('confidence.high') }}</el-tag>
              <el-tag v-else-if="confidenceLevel === 'mid'" type="warning" size="small">{{ t('confidence.mid') }}</el-tag>
              <el-tag v-else type="danger" size="small">{{ t('confidence.low') }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item :label="t('result.reason')">
              {{ result.reason || t('result.noReason') }}
            </el-descriptions-item>
          </el-descriptions>

          <h3>{{ t('result.candidates') }}</h3>
          <el-radio-group v-model="selectedName" class="candidate-group" @change="onRadioChange">
            <el-radio
              v-for="(item, index) in candidates"
              :key="index"
              :value="item.category_name || item.name"
              border
            >
              <span class="candidate-copy">
                <strong>{{ categoryLabel(item.category_name || item.name) }}</strong>
                <span class="muted">{{
                  t('result.originalNameWithPct', {
                    name: item.name,
                    pct: Math.round((item.confidence || 0) * 100),
                  })
                }}</span>
              </span>
            </el-radio>
          </el-radio-group>
          <el-form-item :label="t('result.manual')" class="manual">
            <el-input id="manual-category" v-model="manualName" :placeholder="t('result.manualPlaceholder')" />
          </el-form-item>
          <div class="consent">
            <el-checkbox v-model="optimizationConsent" @change="onConsentChange">
              {{ t('result.consent') }}
            </el-checkbox>
            <el-button v-if="store.session?.optimization_consent" plain type="warning" @click="revokeConsent">
              {{ t('result.revoke') }}
            </el-button>
          </div>
          <div class="result-actions">
            <el-button @click="router.push('/')">{{ t('result.back') }}</el-button>
            <el-button type="primary" :loading="loading" @click="next">{{ t('result.queryProducts') }}</el-button>
          </div>
        </template>

        <template v-else>
          <el-alert type="error" :title="t('result.notAutoPart')" :closable="false" show-icon />
          <el-descriptions v-if="result" :column="1" border size="small" class="reject-copy">
            <el-descriptions-item :label="t('result.recognizedAs')">{{
              categoryLabel(result.part_name) || t('result.nonAutoContent')
            }}</el-descriptions-item>
            <el-descriptions-item :label="t('result.description')">{{ rejectReason }}</el-descriptions-item>
          </el-descriptions>
          <p class="muted">{{ t('result.retakeHint') }}</p>
          <div class="result-actions">
            <el-button type="primary" @click="retake">{{ t('result.retake') }}</el-button>
          </div>
        </template>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { categoryLabelKey, knownErrorKey } from '@shared/locales/index.js'
import { useRecognitionStore } from '@/stores/recognition'
import QueryImageGallery from '@/components/QueryImageGallery.vue'

const { t } = useI18n()
const router = useRouter()
const store = useRecognitionStore()
const loading = ref(false)
const selectedCode = ref('')
const selectedName = ref('')
const manualName = ref('')
const optimizationConsent = ref(Boolean(store.session?.optimization_consent))

const result = computed(() => store.session?.result)
const partCount = computed(
  () => (store.session?.images || []).filter((image) => image.purpose !== 'oe_label').length,
)
const isAutoPart = computed(() => {
  if (store.session?.is_auto_part === false) return false
  if (store.session?.result?.is_auto_part === false) return false
  return true
})
const rejectReason = computed(() => {
  const msg = store.session?.error_message || result.value?.reason || ''
  if (!msg) return t('result.notAutoPartReason')
  const key = knownErrorKey(msg)
  return key ? t(key) : msg
})
const candidates = computed(() => result.value?.candidates || [])
const confidenceLevel = computed(() => {
  const confidence = result.value?.confidence || 0
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'mid'
  return 'low'
})

function categoryLabel(idOrName) {
  if (!idOrName) return ''
  const key = categoryLabelKey(idOrName)
  return key ? t(key) : idOrName
}

function selectCandidate(item) {
  selectedCode.value = item.category_code || ''
  selectedName.value = item.category_name || item.name
  manualName.value = selectedName.value
}

function onRadioChange(name) {
  const item = candidates.value.find((candidate) => (candidate.category_name || candidate.name) === name)
  if (item) selectCandidate(item)
}

async function onConsentChange(val) {
  try {
    await store.setConsent(val)
  } catch {
    // The API client already shows the error.
  }
}

async function revokeConsent() {
  try {
    await store.revokeConsent()
    optimizationConsent.value = false
    ElMessage.success(t('result.revoked'))
  } catch {
    // The API client already shows the error.
  }
}

async function next() {
  if (!isAutoPart.value) {
    ElMessage.warning(t('result.notAutoPartToast'))
    return
  }
  const name = manualName.value || selectedName.value
  const oeNumber = store.session?.oe_number || ''
  if (!name && !oeNumber) {
    ElMessage.warning(t('result.needCategory'))
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
  } catch {
    // The API client already shows the error.
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

<style scoped>
.result-workbench .workbench-split {
  grid-template-columns: minmax(0, 1.15fr) minmax(380px, 0.85fr);
}

h3 {
  margin: 16px 0 8px;
  font-size: 15px;
}

.candidate-group {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  width: 100%;
}

.candidate-group :deep(.el-radio) {
  height: auto;
  margin: 0;
  padding: 10px 12px;
  white-space: normal;
}

.candidate-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.4;
}

.manual {
  margin: 16px 0 0;
}

.consent,
.result-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.result-actions {
  justify-content: flex-end;
}

.reject-copy {
  margin: 12px 0;
}

.el-tag {
  margin-left: 8px;
}

@media (max-width: 1023px) {
  .result-workbench .workbench-split {
    grid-template-columns: 1fr;
  }
}
</style>
