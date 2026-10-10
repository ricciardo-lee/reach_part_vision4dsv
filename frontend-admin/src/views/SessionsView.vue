<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px; gap: 8px; flex-wrap: wrap">
      <h3 style="margin: 0">识别记录</h3>
      <div style="display: flex; gap: 8px; flex-wrap: wrap">
        <el-select v-model="status" clearable placeholder="状态筛选" style="width: 140px" @change="load">
          <el-option label="done" value="done" />
          <el-option label="failed" value="failed" />
          <el-option label="processing" value="processing" />
        </el-select>
        <el-select v-model="feedbackCorrect" clearable placeholder="反馈筛选" style="width: 140px" @change="load">
          <el-option label="反馈不准" :value="false" />
          <el-option label="反馈准确" :value="true" />
        </el-select>
        <el-select v-model="recognitionMode" clearable placeholder="识别路径" style="width: 160px" @change="load">
          <el-option label="图库直匹配" value="sku_match" />
          <el-option label="品类候选" value="category_match" />
          <el-option label="原识别回退" value="vision_fallback" />
        </el-select>
      </div>
    </div>
    <el-table :data="items" stripe style="width: 100%">
      <el-table-column prop="public_id" label="会话 ID" min-width="180" show-overflow-tooltip />
      <el-table-column label="用户" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ row.display_name || row.username || '-' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column label="识别路径" width="110">
        <template #default="{ row }">{{ modeLabel(row.recognition_mode) }}</template>
      </el-table-column>
      <el-table-column prop="matched_sku" label="匹配 SKU" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ row.matched_sku || '-' }}</template>
      </el-table-column>
      <el-table-column label="检索分" width="90">
        <template #default="{ row }">
          {{ row.retrieval_score != null ? Number(row.retrieval_score).toFixed(3) : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="part_name" label="识别品类" width="110">
        <template #default="{ row }">{{ row.part_name || '-' }}</template>
      </el-table-column>
      <el-table-column prop="confidence" label="置信度" width="90">
        <template #default="{ row }">{{ row.confidence != null ? Math.round(row.confidence * 100) + '%' : '-' }}</template>
      </el-table-column>
      <el-table-column prop="confirmed_category_name" label="用户确认" width="110" />
      <el-table-column prop="oe_number" label="OE" width="100" />
      <el-table-column prop="task_id" label="Task" min-width="100" show-overflow-tooltip />
      <el-table-column prop="error_message" label="错误" min-width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="showDetail(row.public_id)">详情</el-button>
          <el-button link type="warning" @click="retry(row.public_id)">重试</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div style="margin-top: 12px; display: flex; justify-content: flex-end">
      <el-pagination
        background
        layout="prev, pager, next"
        :total="total"
        v-model:current-page="page"
        :page-size="20"
        @current-change="load"
      />
    </div>

    <el-drawer v-model="drawer" title="识别详情" size="520px">
      <div v-if="detail" class="detail">
        <section>
          <h4>会话摘要</h4>
          <dl class="kv">
            <dt>路径</dt><dd>{{ modeLabel(detail.recognition_mode) }}</dd>
            <dt>用户</dt><dd>{{ detail.session?.display_name || detail.session?.username || '-' }}</dd>
            <dt>状态</dt><dd>{{ detail.session?.status || '-' }}</dd>
            <dt>确认品类</dt><dd>{{ detail.session?.confirmed_category_name || '-' }}</dd>
            <dt>OE</dt><dd>{{ detail.session?.oe_number || '-' }}</dd>
            <dt>车型</dt>
            <dd>
              {{
                [detail.session?.vehicle_brand, detail.session?.vehicle_series, detail.session?.vehicle_model]
                  .filter(Boolean)
                  .join(' ') || '-'
              }}
            </dd>
            <dt>错误</dt><dd>{{ detail.session?.error_message || '-' }}</dd>
          </dl>
        </section>

        <section v-if="(detail.retrieval_results || []).length">
          <h4>图库检索</h4>
          <div v-for="r in detail.retrieval_results" :key="r.id" class="block">
            <dl class="kv">
              <dt>接受</dt><dd>{{ r.accepted ? '是' : '否' }}</dd>
              <dt>决策</dt><dd>{{ r.decision || '-' }}</dd>
              <dt>匹配 SKU</dt><dd class="em">{{ r.matched_sku || '-' }}</dd>
              <dt>选中品类</dt><dd>{{ r.selected_category_cn || r.selected_category_id || '-' }}</dd>
              <dt>品类置信</dt><dd>{{ fmtScore(r.category_confidence) }}</dd>
              <dt>Vision 辅助</dt><dd>{{ r.vision_assisted ? '是' : '否' }}</dd>
              <dt>分数</dt><dd class="em">{{ fmtScore(r.score) }}</dd>
              <dt>Margin</dt><dd>{{ fmtScore(r.margin) }}</dd>
              <dt>回退原因</dt><dd>{{ r.fallback_reason || '-' }}</dd>
              <dt>索引</dt><dd>{{ r.index_version || '-' }}</dd>
              <dt>模型</dt><dd>{{ r.embedding_model || '-' }}</dd>
              <dt>耗时</dt><dd>{{ r.latency_ms != null ? r.latency_ms + ' ms' : '-' }}</dd>
              <dt>图数</dt><dd>{{ r.image_count ?? '-' }}</dd>
            </dl>
            <div v-if="(r.candidates || []).length" class="candidates">
              <div class="sub">候选</div>
              <div v-for="(c, i) in r.candidates.slice(0, 5)" :key="i" class="cand">
                {{ c.sku || c.matched_sku || '-' }}
                · {{ fmtScore(c.score ?? c.similarity) }}
                · {{ c.category_cn || c.category_id || '' }}
              </div>
            </div>
          </div>
        </section>

        <section v-if="detail.product_snapshot">
          <h4>产品快照</h4>
          <dl class="kv">
            <dt>结果数</dt><dd>{{ detail.product_snapshot.result_count ?? '-' }}</dd>
          </dl>
          <pre class="json">{{ JSON.stringify(detail.product_snapshot.result_payload, null, 2) }}</pre>
        </section>

        <section v-if="(detail.results || []).length">
          <h4>Vision 结果</h4>
          <div v-for="r in detail.results" :key="r.id" class="block">
            <dl class="kv">
              <dt>类型</dt><dd>{{ visionPurpose(r) }}</dd>
              <dt>模型</dt><dd>{{ r.model_name || '-' }}</dd>
              <dt>品类</dt><dd class="em">{{ r.part_name || '-' }}</dd>
              <dt>置信度</dt><dd class="em">{{ r.confidence != null ? Math.round(r.confidence * 100) + '%' : '-' }}</dd>
              <dt>映射</dt><dd>{{ r.mapped_category_name || r.mapped_category_code || '-' }}</dd>
              <dt>成功</dt><dd>{{ r.success ? '是' : '否' }}</dd>
              <dt>判断依据</dt><dd class="em">{{ r.reason || '-' }}</dd>
              <dt>错误</dt><dd>{{ r.error_message || '-' }}</dd>
              <dt>耗时</dt><dd>{{ r.latency_ms != null ? r.latency_ms + ' ms' : '-' }}</dd>
            </dl>
            <div v-if="(r.candidates || []).length" class="candidates">
              <div class="sub">Vision 候选</div>
              <div v-for="(c, i) in r.candidates" :key="i" class="cand">
                {{ c.name || c.category_name || '-' }}
                · {{ c.confidence != null ? Math.round(c.confidence * 100) + '%' : '-' }}
                · {{ c.category_code || '' }}
              </div>
            </div>
            <div v-if="constrainedMeta(r)" class="candidates">
              <div class="sub">约束品类判定详情</div>
              <div class="cand">允许品类：{{ formatAllowed(constrainedMeta(r).allowed_categories) }}</div>
              <div class="cand">选中 ID：{{ constrainedMeta(r).selected_category_id || '-' }}</div>
              <div class="cand">在允许列表：{{ constrainedMeta(r).in_allowlist ? '是' : '否' }}</div>
              <div class="cand">采纳为品类匹配：{{ constrainedMeta(r).accepted_for_category_match ? '是' : '否' }}</div>
              <div class="cand">模型依据：{{ constrainedMeta(r).vision_reason || r.reason || '-' }}</div>
            </div>
            <div v-if="constrainedMeta(r)?.retrieval_candidates_by_category" class="candidates">
              <div class="sub">当时检索候选（按品类）</div>
              <pre class="json">{{ JSON.stringify(constrainedMeta(r).retrieval_candidates_by_category, null, 2) }}</pre>
            </div>
            <details v-if="r.raw_response" class="raw">
              <summary>原始返回 JSON</summary>
              <pre class="json">{{ JSON.stringify(r.raw_response, null, 2) }}</pre>
            </details>
          </div>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const items = ref([])
const total = ref(0)
const page = ref(1)
const status = ref('')
const feedbackCorrect = ref(undefined)
const recognitionMode = ref('')
const drawer = ref(false)
const detail = ref(null)

function modeLabel(mode) {
  if (mode === 'sku_match') return '图库直匹配'
  if (mode === 'category_match') return '品类候选'
  if (mode === 'vision_fallback') return '原识别回退'
  return '-'
}

function visionPurpose(r) {
  const purpose = r?.raw_response?.purpose
  if (purpose === 'constrained_category' || String(r?.model_name || '').includes('constrained_category')) {
    return '候选约束品类判定'
  }
  return '完整 Vision 识别'
}

function constrainedMeta(r) {
  const raw = r?.raw_response
  if (!raw || raw.purpose !== 'constrained_category') return null
  return raw
}

function formatAllowed(list) {
  if (!Array.isArray(list) || !list.length) return '-'
  return list.map((x) => x.category_cn || x.category_id || '-').join(' / ')
}

function fmtScore(v) {
  if (v == null || v === '') return '-'
  return Number(v).toFixed(3)
}

async function load() {
  const res = await api.get('/api/v1/admin/sessions', {
    params: {
      page: page.value,
      page_size: 20,
      status: status.value || undefined,
      feedback_correct: feedbackCorrect.value === undefined || feedbackCorrect.value === ''
        ? undefined
        : feedbackCorrect.value,
      recognition_mode: recognitionMode.value || undefined,
    },
  })
  items.value = res.data.items || []
  total.value = res.data.total || 0
}

async function showDetail(publicId) {
  const res = await api.get(`/api/v1/admin/sessions/${publicId}`)
  detail.value = res.data || null
  drawer.value = true
}

async function retry(publicId) {
  const res = await api.post(`/api/v1/admin/sessions/${publicId}/retry`)
  ElMessage.success(res.message || '已重新提交识别')
  await load()
}

onMounted(load)
</script>

<style scoped>
.detail section {
  margin-bottom: 20px;
}
.detail h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #303133;
}
.kv {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 6px 10px;
  margin: 0;
  font-size: 13px;
}
.kv dt {
  color: #909399;
}
.kv dd {
  margin: 0;
  word-break: break-all;
}
.kv dd.em {
  font-weight: 600;
  color: #303133;
}
.block {
  padding: 10px 0;
  border-bottom: 1px solid #ebeef5;
}
.block:last-child {
  border-bottom: none;
}
.candidates {
  margin-top: 8px;
  font-size: 12px;
  color: #606266;
}
.candidates .sub {
  margin-bottom: 4px;
  color: #909399;
}
.cand {
  padding: 2px 0;
}
.json {
  margin: 8px 0 0;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 11px;
  white-space: pre-wrap;
  max-height: 200px;
  overflow: auto;
}
.raw {
  margin-top: 8px;
  font-size: 12px;
  color: #606266;
}
.raw summary {
  cursor: pointer;
  color: #409eff;
}
</style>
