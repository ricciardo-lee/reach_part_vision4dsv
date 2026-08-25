<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">✍️ Prompt 配置</h3>
      <el-button type="primary" @click="openCreate">➕ 新增版本</el-button>
    </div>
    <el-table :data="items" stripe>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="purpose" label="用途" width="100" />
      <el-table-column prop="version" label="版本" width="90" />
      <el-table-column prop="is_active" label="启用" width="80">
        <template #default="{ row }">{{ row.is_active ? '✅' : '❌' }}</template>
      </el-table-column>
      <el-table-column prop="content" label="内容" show-overflow-tooltip />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" :title="form.id ? '编辑 Prompt' : '新增 Prompt'" width="720px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="用途">
          <el-select v-model="form.purpose">
            <el-option label="vision" value="vision" />
            <el-option label="oe_ocr" value="oe_ocr" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="form.content" type="textarea" :rows="10" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const items = ref([])
const visible = ref(false)
const form = reactive({
  id: null,
  name: '',
  purpose: 'vision',
  version: 'v1',
  content: '',
  is_active: true,
  note: '',
})

async function load() {
  const res = await api.get('/api/v1/admin/prompts')
  items.value = res.data || []
}

function openCreate() {
  Object.assign(form, {
    id: null,
    name: '',
    purpose: 'vision',
    version: 'v1',
    content: '',
    is_active: true,
    note: '',
  })
  visible.value = true
}

function openEdit(row) {
  Object.assign(form, row)
  visible.value = true
}

async function save() {
  const payload = {
    name: form.name,
    purpose: form.purpose,
    version: form.version,
    content: form.content,
    is_active: form.is_active,
    note: form.note,
  }
  if (form.id) await api.put(`/api/v1/admin/prompts/${form.id}`, payload)
  else await api.post('/api/v1/admin/prompts', payload)
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

onMounted(load)
</script>
