<template>
  <div>
    <div class="stat-grid">
      <div class="stat-item">
        <div class="label">📈 总识别会话</div>
        <div class="value">{{ stats.total_sessions ?? '-' }}</div>
      </div>
      <div class="stat-item">
        <div class="label">✅ 成功</div>
        <div class="value">{{ stats.success_sessions ?? '-' }}</div>
      </div>
      <div class="stat-item">
        <div class="label">❌ 失败</div>
        <div class="value">{{ stats.failed_sessions ?? '-' }}</div>
      </div>
      <div class="stat-item">
        <div class="label">🎯 平均置信度</div>
        <div class="value">{{ fmtPct(stats.avg_confidence) }}</div>
      </div>
      <div class="stat-item">
        <div class="label">👍 反馈正确率</div>
        <div class="value">{{ fmtPct(stats.feedback_correct_rate) }}</div>
      </div>
      <div class="stat-item">
        <div class="label">🥇 Top-1</div>
        <div class="value">{{ fmtPct(stats.top1_hit_rate) }}</div>
      </div>
      <div class="stat-item">
        <div class="label">🥉 Top-3</div>
        <div class="value">{{ fmtPct(stats.top3_hit_rate) }}</div>
      </div>
      <div class="stat-item">
        <div class="label">🚫 拒识率</div>
        <div class="value">{{ fmtPct(stats.reject_rate) }}</div>
      </div>
      <div class="stat-item">
        <div class="label">🏷️ 已标注会话</div>
        <div class="value">{{ stats.labeled_sessions ?? '-' }}</div>
      </div>
    </div>
    <div class="page-card">
      <h3>🚀 快捷入口</h3>
      <el-space wrap>
        <el-button type="primary" @click="$router.push('/sessions')">查看识别记录</el-button>
        <el-button @click="$router.push('/mappings')">维护品类映射</el-button>
        <el-button @click="$router.push('/prompts')">调整 Prompt</el-button>
      </el-space>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '@/api/client'

const stats = ref({})

function fmtPct(v) {
  if (v == null) return '-'
  return `${Math.round(Number(v) * 100)}%`
}

onMounted(async () => {
  const res = await api.get('/api/v1/admin/stats')
  stats.value = res.data || {}
})
</script>
