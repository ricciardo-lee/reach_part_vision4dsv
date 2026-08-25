<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">🧩 品类映射</h3>
      <el-button type="primary" @click="openCreate">➕ 新增</el-button>
    </div>
    <el-table :data="items" stripe>
      <el-table-column prop="alias_name" label="别名" />
      <el-table-column prop="category_code" label="品类编码" />
      <el-table-column prop="category_name" label="标准品类" />
      <el-table-column prop="priority" label="优先级" width="90" />
      <el-table-column prop="is_active" label="启用" width="80">
        <template #default="{ row }">{{ row.is_active ? '✅' : '❌' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" :title="form.id ? '编辑映射' : '新增映射'" width="480px">
      <el-form label-width="100px">
        <el-form-item label="别名"><el-input v-model="form.alias_name" /></el-form-item>
        <el-form-item label="品类编码"><el-input v-model="form.category_code" /></el-form-item>
        <el-form-item label="标准品类"><el-input v-model="form.category_name" /></el-form-item>
        <el-form-item label="优先级"><el-input-number v-model="form.priority" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/client'

const items = ref([])
const visible = ref(false)
const form = reactive({
  id: null,
  alias_name: '',
  category_code: '',
  category_name: '',
  priority: 0,
  is_active: true,
  note: '',
})

async function load() {
  const res = await api.get('/api/v1/admin/mappings')
  items.value = res.data || []
}

function openCreate() {
  Object.assign(form, {
    id: null,
    alias_name: '',
    category_code: '',
    category_name: '',
    priority: 0,
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
    alias_name: form.alias_name,
    category_code: form.category_code,
    category_name: form.category_name,
    priority: form.priority,
    is_active: form.is_active,
    note: form.note,
  }
  if (form.id) await api.put(`/api/v1/admin/mappings/${form.id}`, payload)
  else await api.post('/api/v1/admin/mappings', payload)
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

async function remove(id) {
  await ElMessageBox.confirm('确认删除该映射？', '提示')
  await api.delete(`/api/v1/admin/mappings/${id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>
