<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px; gap: 8px; flex-wrap: wrap">
      <h3 style="margin: 0">🧾 识别记录</h3>
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
      </div>
    </div>
    <el-table :data="items" stripe style="width: 100%">
      <el-table-column prop="public_id" label="会话 ID" min-width="200" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="part_name" label="识别品类" width="120" />
      <el-table-column prop="confidence" label="置信度" width="90">
        <template #default="{ row }">{{ row.confidence != null ? Math.round(row.confidence * 100) + '%' : '-' }}</template>
      </el-table-column>
      <el-table-column prop="confirmed_category_name" label="用户确认" width="120" />
      <el-table-column prop="oe_number" label="OE" width="110" />
      <el-table-column prop="task_id" label="Task" min-width="120" show-overflow-tooltip />
      <el-table-column prop="error_message" label="错误" min-width="140" show-overflow-tooltip />
      <el-table-column label="操作" width="180" fixed="right">
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

    <el-drawer v-model="drawer" title="识别详情" size="420px">
      <pre style="white-space: pre-wrap; font-size: 12px">{{ detailText }}</pre>
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
const drawer = ref(false)
const detailText = ref('')

async function load() {
  const res = await api.get('/api/v1/admin/sessions', {
    params: {
      page: page.value,
      page_size: 20,
      status: status.value || undefined,
      feedback_correct: feedbackCorrect.value === undefined || feedbackCorrect.value === ''
        ? undefined
        : feedbackCorrect.value,
    },
  })
  items.value = res.data.items || []
  total.value = res.data.total || 0
}

async function showDetail(publicId) {
  const res = await api.get(`/api/v1/admin/sessions/${publicId}`)
  detailText.value = JSON.stringify(res.data, null, 2)
  drawer.value = true
}

async function retry(publicId) {
  const res = await api.post(`/api/v1/admin/sessions/${publicId}/retry`)
  ElMessage.success(res.message || '已重新提交识别')
  await load()
}

onMounted(load)
</script>
