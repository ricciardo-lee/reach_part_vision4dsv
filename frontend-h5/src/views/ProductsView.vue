<template>
  <div class="page">
    <section class="card">
      <van-steps :active="3" active-color="#1f6feb">
        <van-step>拍照上传</van-step>
        <van-step>确认品类</van-step>
        <van-step>车型/OE</van-step>
        <van-step>查看产品</van-step>
      </van-steps>
    </section>

    <section class="card">
      <h2 class="title-row"><span class="emoji" aria-hidden="true">📦</span> 匹配产品</h2>
      <p class="muted">
        品类：{{ store.session?.confirmed_category_name || '-' }}
        · OE：{{ store.session?.oe_number || '-' }}
      </p>
    </section>

    <section class="card" v-if="store.products.length">
      <div v-for="item in store.products" :key="item.sku" class="product-item">
        <div style="display: flex; justify-content: space-between; gap: 8px">
          <strong>{{ item.name }}</strong>
          <span>💰 {{ item.price != null ? `¥${item.price}` : '-' }}</span>
        </div>
        <div class="muted">SKU：{{ item.sku }}</div>
        <div class="muted">适配：{{ item.fitment || '-' }}</div>
        <div class="muted">库存：{{ item.stock_status || '-' }}</div>
        <van-tag plain type="primary">🔎 {{ item.match_reason || '匹配结果' }}</van-tag>
      </div>
    </section>

    <section class="card" v-else>
      <p class="title-row"><span class="emoji">📭</span> 暂无匹配产品</p>
      <p class="muted">可返回修改品类、车型或 OE 后再试。</p>
    </section>

    <section class="card">
      <h3 class="title-row"><span class="emoji" aria-hidden="true">🗣️</span> 本次识别准确吗？</h3>
      <div style="display: flex; gap: 8px">
        <van-button type="success" block @click="feedback(true)">👍 准确</van-button>
        <van-button type="danger" block plain @click="feedback(false)">👎 不准</van-button>
      </div>
    </section>

    <div class="bottom-bar" style="display: flex; gap: 8px">
      <van-button block round @click="$router.push('/result')">↩️ 返回调整</van-button>
      <van-button type="primary" block round @click="$router.push('/')">📷 再识一张</van-button>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { useRecognitionStore } from '@/stores/recognition'

const store = useRecognitionStore()
const router = useRouter()

async function feedback(correct) {
  await store.sendFeedback(correct)
  showToast(correct ? '感谢反馈 🎉' : '已记录，我们会优化')
}

onMounted(() => {
  if (!store.session) router.replace('/')
})
</script>
