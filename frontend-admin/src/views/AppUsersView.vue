<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
      <h3 style="margin: 0">识别用户</h3>
      <el-button type="primary" @click="openCreate">新增用户</el-button>
    </div>
    <el-table :data="items" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="display_name" label="显示名" />
      <el-table-column prop="is_active" label="状态" width="90">
        <template #default="{ row }">{{ row.is_active ? '启用' : '禁用' }}</template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最近登录" min-width="180" />
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="warning" @click="openPassword(row)">重置密码</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" :title="form.id ? '编辑识别用户' : '新增识别用户'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="Boolean(form.id)" autocomplete="off" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item v-if="form.id" label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="passwordVisible" title="重置密码" width="420px">
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input :model-value="passwordForm.username" disabled />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="resetPassword">保存</el-button>
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
const passwordVisible = ref(false)
const saving = ref(false)
const form = reactive({
  id: null,
  username: '',
  display_name: '',
  password: '',
  is_active: true,
})
const passwordForm = reactive({
  id: null,
  username: '',
  password: '',
})

async function load() {
  const res = await api.get('/api/v1/admin/app-users')
  items.value = res.data || []
}

function openCreate() {
  Object.assign(form, {
    id: null,
    username: '',
    display_name: '',
    password: '',
    is_active: true,
  })
  visible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    username: row.username,
    display_name: row.display_name || '',
    password: '',
    is_active: row.is_active,
  })
  visible.value = true
}

function openPassword(row) {
  Object.assign(passwordForm, { id: row.id, username: row.username, password: '' })
  passwordVisible.value = true
}

async function save() {
  const username = form.username.trim()
  if (!form.id && !username) {
    ElMessage.warning('请填写用户名')
    return
  }
  if (!form.id && form.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  saving.value = true
  try {
    if (form.id) {
      await api.patch(`/api/v1/admin/app-users/${form.id}`, {
        display_name: form.display_name,
        is_active: form.is_active,
      })
    } else {
      await api.post('/api/v1/admin/app-users', {
        username,
        display_name: form.display_name,
        password: form.password,
      })
    }
    visible.value = false
    ElMessage.success('已保存')
    await load()
  } finally {
    saving.value = false
  }
}

async function resetPassword() {
  if (passwordForm.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await api.post(`/api/v1/admin/app-users/${passwordForm.id}/password`, {
      password: passwordForm.password,
    })
    passwordVisible.value = false
    ElMessage.success('密码已重置')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
