<template>
  <div class="page-card">
    <h3>🕵️ 审计日志</h3>
    <el-table :data="items" stripe>
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="actor_type" label="角色" width="100" />
      <el-table-column prop="actor_id" label="操作者" width="120" />
      <el-table-column prop="action" label="动作" width="180" />
      <el-table-column prop="resource_type" label="资源类型" width="140" />
      <el-table-column prop="resource_id" label="资源 ID" min-width="180" />
    </el-table>
    <div style="margin-top: 12px; display: flex; justify-content: flex-end">
      <el-pagination background layout="prev, pager, next" :total="total" v-model:current-page="page" :page-size="20" @current-change="load" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '@/api/client'

const items = ref([])
const total = ref(0)
const page = ref(1)

async function load() {
  const res = await api.get('/api/v1/admin/audit-logs', { params: { page: page.value, page_size: 20 } })
  items.value = res.data.items || []
  total.value = res.data.total || 0
}

onMounted(load)
</script>
