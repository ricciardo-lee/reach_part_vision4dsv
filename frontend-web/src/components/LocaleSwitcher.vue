<template>
  <div class="locale-switcher" role="group" :aria-label="t('lang.switchToEn')">
    <button
      type="button"
      class="locale-btn"
      :class="{ active: locale === 'zh-CN' }"
      :aria-pressed="locale === 'zh-CN'"
      :title="t('lang.switchToZh')"
      @click="switchTo('zh-CN')"
    >
      {{ t('lang.zh') }}
    </button>
    <button
      type="button"
      class="locale-btn"
      :class="{ active: locale === 'en-US' }"
      :aria-pressed="locale === 'en-US'"
      :title="t('lang.switchToEn')"
      @click="switchTo('en-US')"
    >
      {{ t('lang.en') }}
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '@/i18n'

const { t, locale } = useI18n()
const current = computed(() => locale.value)

function switchTo(next) {
  if (current.value === next) return
  setLocale(next)
}
</script>

<style scoped>
.locale-switcher {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  overflow: hidden;
}

.locale-btn {
  border: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.72);
  cursor: pointer;
  padding: 5px 10px;
  font-size: 12px;
  line-height: 1;
}

.locale-btn.active {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
  font-weight: 600;
}
</style>
