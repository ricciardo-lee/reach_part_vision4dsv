<template>
  <div class="layout">
    <aside class="sider">
      <h1>📷 Part Vision Admin</h1>
      <el-menu :default-active="$route.path" router background-color="#111827" text-color="#e5e7eb" active-text-color="#93c5fd">
        <el-menu-item index="/">📊 概览</el-menu-item>
        <el-menu-item index="/sessions">🧾 识别记录</el-menu-item>
        <el-menu-item index="/mappings">🧩 品类映射</el-menu-item>
        <el-menu-item index="/prompts">✍️ Prompt</el-menu-item>
        <el-menu-item index="/users">👥 管理员</el-menu-item>
        <el-menu-item index="/app-users">🧑 识别用户</el-menu-item>
        <el-menu-item index="/audit">🕵️ 审计日志</el-menu-item>
      </el-menu>
      <div style="margin: 16px 12px; color: #9ca3af; font-size: 12px">
        {{ displayName }} · {{ role }}
      </div>
      <el-button size="small" style="margin: 0 12px" @click="logout">🚪 退出</el-button>
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const displayName = computed(() => localStorage.getItem('admin_name') || 'Admin')
const role = computed(() => localStorage.getItem('admin_role') || '-')

function logout() {
  localStorage.removeItem('admin_token')
  router.push('/login')
}
</script>
