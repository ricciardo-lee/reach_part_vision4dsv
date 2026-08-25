<template>
  <div class="page-card">
    <h3>👥 管理员账号</h3>
    <el-table :data="items" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="display_name" label="显示名" />
      <el-table-column prop="role" label="角色" />
      <el-table-column prop="is_active" label="状态" width="90">
        <template #default="{ row }">{{ row.is_active ? '✅ 启用' : '❌ 禁用' }}</template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最近登录" min-width="180" />
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '@/api/client'

const items = ref([])

onMounted(async () => {
  const res = await api.get('/api/v1/admin/users')
  items.value = res.data || []
})
</script>
