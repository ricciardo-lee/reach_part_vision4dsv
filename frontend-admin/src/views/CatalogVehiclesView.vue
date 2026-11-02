<template>
  <div class="page-card">
    <div class="toolbar">
      <h3 style="margin: 0">车型适配</h3>
      <div class="actions">
        <el-input v-model="keyword" placeholder="品牌 make_name" clearable style="width: 200px" @keyup.enter="load" />
        <el-button @click="load">查询</el-button>
        <el-button @click="downloadTemplate">下载模板</el-button>
        <el-button @click="exportData">导出</el-button>
        <el-upload :show-file-list="false" :http-request="doImport" accept=".xlsx,.xls">
          <el-button type="primary">导入 Excel</el-button>
        </el-upload>
      </div>
    </div>
    <el-table :data="items" stripe v-loading="loading">
      <el-table-column prop="material_code" label="物料编码 / SKU" min-width="140" />
      <el-table-column prop="make_name" label="品牌" width="140" />
      <el-table-column prop="model_name" label="车型" min-width="140" />
      <el-table-column prop="year" label="年款" width="100" />
      <el-table-column prop="is_active" label="启用" width="80">
        <template #default="{ row }">{{ row.is_active ? '是' : '否' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="danger" @click="remove(row.id)">停用</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        v-model:current-page="page"
        :page-size="pageSize"
        @current-change="load"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { downloadBlob } from '@/api/client'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await api.get('/api/v1/admin/catalog/vehicles', {
      params: { page: page.value, page_size: pageSize, keyword: keyword.value },
    })
    items.value = res.data?.items || []
    total.value = res.data?.total || 0
  } finally {
    loading.value = false
  }
}

async function downloadTemplate() {
  await downloadBlob('/api/v1/admin/catalog/vehicles/template', 'vehicles_template.xlsx')
}

async function exportData() {
  await downloadBlob('/api/v1/admin/catalog/vehicles/export', 'vehicles_export.xlsx', {
    keyword: keyword.value,
  })
}

async function doImport(option) {
  const form = new FormData()
  form.append('file', option.file)
  await api.post('/api/v1/admin/catalog/vehicles/import', form)
  ElMessage.success('导入完成')
  await load()
}

async function remove(id) {
  await ElMessageBox.confirm('确认停用该车型适配？', '提示')
  await api.delete(`/api/v1/admin/catalog/vehicles/${id}`)
  ElMessage.success('已停用')
  await load()
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
