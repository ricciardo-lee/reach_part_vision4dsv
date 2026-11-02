<template>
  <div class="page-card">
    <h3 style="margin: 0 0 12px">技术参数</h3>
    <el-tabs v-model="active">
      <el-tab-pane label="散热器 Radiator" name="radiator">
        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="物料编码"
            clearable
            style="width: 200px"
            @keyup.enter="loadRadiator"
          />
          <el-button @click="loadRadiator">查询</el-button>
          <el-button @click="downloadTemplate('radiator')">下载模板</el-button>
          <el-button @click="exportRadiator">导出</el-button>
          <el-upload :show-file-list="false" :http-request="importRadiator" accept=".xlsx,.xls">
            <el-button type="primary">导入 Excel</el-button>
          </el-upload>
        </div>
        <el-table :data="items" stripe v-loading="loading">
          <el-table-column prop="material_code" label="物料编码" min-width="140" />
          <el-table-column prop="core_material" label="core_material" min-width="120" />
          <el-table-column prop="tank_material" label="tank_material" min-width="120" />
          <el-table-column prop="inlet_location" label="inlet" width="100" />
          <el-table-column prop="outlet_location" label="outlet" width="100" />
          <el-table-column prop="core_row_quantity" label="core_rows" width="100" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeRadiator(row.id)">停用</el-button>
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
            @current-change="loadRadiator"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="压缩机 Compressor" name="compressor">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="表头待确认"
          description="压缩机技术参数表头尚未确认，仅可下载占位模板。"
          style="margin-bottom: 16px"
        />
        <el-button @click="downloadTemplate('compressor')">下载占位模板</el-button>
        <el-button type="primary" disabled>导入（待表头）</el-button>
      </el-tab-pane>

      <el-tab-pane label="冷凝器 Condenser" name="condenser">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="表头待确认"
          description="冷凝器技术参数表头尚未确认，仅可下载占位模板。"
          style="margin-bottom: 16px"
        />
        <el-button @click="downloadTemplate('condenser')">下载占位模板</el-button>
        <el-button type="primary" disabled>导入（待表头）</el-button>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { downloadBlob } from '@/api/client'

const active = ref('radiator')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref('')
const loading = ref(false)

async function loadRadiator() {
  loading.value = true
  try {
    const res = await api.get('/api/v1/admin/catalog/specs/radiator', {
      params: { page: page.value, page_size: pageSize, keyword: keyword.value },
    })
    items.value = res.data?.items || []
    total.value = res.data?.total || 0
  } finally {
    loading.value = false
  }
}

async function downloadTemplate(category) {
  await downloadBlob(
    `/api/v1/admin/catalog/specs/${category}/template`,
    `spec_${category}_template.xlsx`,
  )
}

async function exportRadiator() {
  await downloadBlob('/api/v1/admin/catalog/specs/radiator/export', 'spec_radiator_export.xlsx', {
    keyword: keyword.value,
  })
}

async function importRadiator(option) {
  const form = new FormData()
  form.append('file', option.file)
  await api.post('/api/v1/admin/catalog/specs/radiator/import', form)
  ElMessage.success('导入完成')
  await loadRadiator()
}

async function removeRadiator(id) {
  await ElMessageBox.confirm('确认停用该技术参数行？', '提示')
  await api.delete(`/api/v1/admin/catalog/specs/radiator/${id}`)
  ElMessage.success('已停用')
  await loadRadiator()
}

watch(active, (val) => {
  if (val === 'radiator') loadRadiator()
})

onMounted(loadRadiator)
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 12px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
