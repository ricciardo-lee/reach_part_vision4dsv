<template>
  <div class="wa-page">
    <div class="wa-stats page-card">
      <h3 style="margin: 0 0 12px">WhatsApp 对话</h3>
      <div class="stat-row">
        <div class="stat"><span>联系人</span><strong>{{ stats.contacts ?? '-' }}</strong></div>
        <div class="stat"><span>会话</span><strong>{{ stats.conversations ?? '-' }}</strong></div>
        <div class="stat"><span>进行中</span><strong>{{ stats.open_conversations ?? '-' }}</strong></div>
        <div class="stat"><span>消息</span><strong>{{ stats.messages ?? '-' }}</strong></div>
        <div class="stat"><span>LLM Tokens</span><strong>{{ stats.llm_tokens ?? '-' }}</strong></div>
        <div class="stat"><span>平均延迟</span><strong>{{ latencyLabel }}</strong></div>
      </div>
    </div>

    <div class="wa-main page-card">
      <aside class="wa-list">
        <div class="list-toolbar">
          <el-input v-model="waId" clearable placeholder="手机号筛选" @keyup.enter="loadConversations" />
          <el-select v-model="status" clearable placeholder="状态" style="width: 110px" @change="loadConversations">
            <el-option label="open" value="open" />
            <el-option label="closed" value="closed" />
          </el-select>
          <el-button type="primary" @click="loadConversations">查询</el-button>
        </div>
        <div
          v-for="item in conversations"
          :key="item.id"
          class="conv-item"
          :class="{ active: item.id === selectedId }"
          @click="selectConversation(item.id)"
        >
          <div class="conv-title">
            <strong>{{ item.profile_name || item.wa_id || '-' }}</strong>
            <el-tag size="small" :type="item.status === 'open' ? 'success' : 'info'">{{ item.status }}</el-tag>
          </div>
          <div class="conv-meta">{{ item.wa_id }} · {{ item.message_count }} msgs</div>
          <div class="conv-time">{{ item.last_message_at || item.created_at || '' }}</div>
        </div>
        <div v-if="!conversations.length" class="empty">暂无会话</div>
        <div class="pager">
          <el-pagination
            background
            layout="prev, pager, next"
            :total="total"
            v-model:current-page="page"
            :page-size="20"
            @current-change="loadConversations"
          />
        </div>
      </aside>

      <section class="wa-thread">
        <div v-if="!selectedId" class="empty">选择左侧会话查看消息</div>
        <template v-else>
          <div class="thread-header">
            <div>
              <strong>{{ conversation?.profile_name || conversation?.wa_id }}</strong>
              <span class="muted">{{ conversation?.wa_id }}</span>
            </div>
            <el-button size="small" @click="loadMessages">刷新</el-button>
          </div>
          <div class="bubbles" ref="bubblesEl">
            <div
              v-for="msg in messages"
              :key="msg.id"
              class="bubble"
              :class="msg.direction === 'out' ? 'out' : 'in'"
            >
              <div class="bubble-meta">
                {{ msg.direction === 'out' ? 'Bot' : 'User' }}
                · {{ msg.msg_type }}
                · {{ msg.delivery_status || '-' }}
                <span v-if="msg.latency_ms != null"> · {{ msg.latency_ms }}ms</span>
              </div>
              <div class="bubble-text">{{ bubbleText(msg) }}</div>
              <div v-if="msg.recognition_session_public_id" class="session-link">
                <el-button link type="primary" @click="openRecognition(msg.recognition_session_public_id)">
                  识别会话 {{ msg.recognition_session_public_id }}
                </el-button>
              </div>
              <div v-if="msg.tool_calls?.length" class="tools">
                <el-collapse>
                  <el-collapse-item title="工具调用" name="tools">
                    <pre>{{ JSON.stringify(msg.tool_calls, null, 2) }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </div>
              <div v-if="msg.token_usage" class="tokens">
                tokens: {{ JSON.stringify(msg.token_usage) }}
              </div>
              <div v-if="msg.error_message" class="error">{{ msg.error_message }}</div>
              <div class="bubble-time">{{ msg.created_at }}</div>
            </div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/client'

const router = useRouter()

const stats = ref({})
const conversations = ref([])
const messages = ref([])
const conversation = ref(null)
const selectedId = ref(null)
const page = ref(1)
const total = ref(0)
const status = ref('')
const waId = ref('')
const bubblesEl = ref(null)

const latencyLabel = computed(() => {
  const v = stats.value.avg_outbound_latency_ms
  return v == null ? '-' : `${v} ms`
})

async function loadStats() {
  const res = await api.get('/api/v1/admin/whatsapp/stats')
  stats.value = res.data || {}
}

async function loadConversations() {
  const res = await api.get('/api/v1/admin/whatsapp/conversations', {
    params: {
      page: page.value,
      page_size: 20,
      status: status.value || undefined,
      wa_id: waId.value || undefined,
    },
  })
  conversations.value = res.data?.items || []
  total.value = res.data?.total || 0
}

function bubbleText(msg) {
  if (msg.msg_type === 'image') {
    const caption = (msg.text || '').trim()
    return caption ? `[Photo] ${caption}` : '[Photo]'
  }
  if (msg.msg_type === 'interactive' && msg.direction === 'out') {
    const body = (msg.text || '').trim()
    return body ? `[Welcome card] ${body}` : '[Welcome card]'
  }
  return msg.text || `(${msg.msg_type})`
}

function openRecognition(publicId) {
  if (!publicId) return
  router.push({ path: '/sessions', query: { detail: publicId } })
}

async function selectConversation(id) {
  selectedId.value = id
  await loadMessages()
}

async function loadMessages() {
  if (!selectedId.value) return
  const res = await api.get(`/api/v1/admin/whatsapp/conversations/${selectedId.value}/messages`, {
    params: { page: 1, page_size: 200 },
  })
  conversation.value = res.data?.conversation || null
  messages.value = res.data?.items || []
  await nextTick()
  if (bubblesEl.value) {
    bubblesEl.value.scrollTop = bubblesEl.value.scrollHeight
  }
}

onMounted(async () => {
  await Promise.all([loadStats(), loadConversations()])
})
</script>

<style scoped>
.wa-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 48px);
}
.page-card {
  background: #fff;
  border-radius: 10px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
.stat {
  min-width: 110px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #6b7280;
}
.stat strong {
  color: #111827;
  font-size: 20px;
}
.wa-main {
  flex: 1;
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 12px;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}
.wa-list {
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: auto;
}
.list-toolbar {
  display: flex;
  gap: 6px;
  padding: 12px;
  border-bottom: 1px solid #e5e7eb;
  flex-wrap: wrap;
}
.conv-item {
  padding: 12px;
  border-bottom: 1px solid #f3f4f6;
  cursor: pointer;
}
.conv-item:hover,
.conv-item.active {
  background: #f0f9ff;
}
.conv-title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
.conv-meta,
.conv-time,
.muted,
.bubble-time,
.tokens {
  color: #9ca3af;
  font-size: 12px;
  margin-top: 4px;
}
.pager {
  padding: 12px;
  display: flex;
  justify-content: center;
}
.wa-thread {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.thread-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #e5e7eb;
}
.bubbles {
  flex: 1;
  overflow: auto;
  padding: 16px;
  background: #f8fafc;
}
.bubble {
  max-width: 75%;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
}
.bubble.in {
  margin-right: auto;
}
.bubble.out {
  margin-left: auto;
  background: #eff6ff;
  border-color: #bfdbfe;
}
.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
  color: #111827;
}
.bubble-meta {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 6px;
}
.tools pre {
  margin: 0;
  white-space: pre-wrap;
  font-size: 12px;
}
.error {
  color: #b91c1c;
  font-size: 12px;
  margin-top: 6px;
}
.session-link {
  margin-top: 6px;
}
.empty {
  padding: 24px;
  color: #9ca3af;
  text-align: center;
}
</style>
