<template>
  <van-popup
    :show="show"
    position="bottom"
    round
    :style="{ height: '72%' }"
    @update:show="onUpdateShow"
  >
    <div class="sheet">
      <div class="sheet-header">
        <button type="button" class="link" @click="close">{{ t('common.cancel') }}</button>
        <strong>{{ title || t('common.pleaseSelect') }}</strong>
        <span class="spacer" />
      </div>
      <van-field
        v-model="keyword"
        clearable
        left-icon="search"
        :placeholder="t('common.search')"
        class="search"
      />
      <div class="sheet-body">
        <van-index-bar v-if="filteredGroups.length" :index-list="filteredLetters" sticky>
          <div v-for="group in filteredGroups" :key="group.letter">
            <van-index-anchor :index="group.letter" />
            <van-cell
              v-for="item in group.items"
              :key="item.value"
              :title="item.label"
              is-link
              clickable
              @click="pick(item)"
            />
          </div>
        </van-index-bar>
        <p v-else class="empty muted">{{ t('common.noMatch') }}</p>
      </div>
    </div>
  </van-popup>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: '' },
  /** { letters, groups: [{ letter, items: [{value,label,letter}] }], items } */
  indexed: { type: Object, default: () => ({ letters: [], groups: [], items: [] }) },
})

const emit = defineEmits(['update:show', 'select'])

const keyword = ref('')

watch(
  () => props.show,
  (open) => {
    if (open) keyword.value = ''
  },
)

const filteredGroups = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  const groups = props.indexed?.groups || []
  if (!q) return groups
  return groups
    .map((g) => ({
      letter: g.letter,
      items: (g.items || []).filter((item) => {
        const label = String(item.label || '').toLowerCase()
        const value = String(item.value || '').toLowerCase()
        return label.includes(q) || value.includes(q)
      }),
    }))
    .filter((g) => g.items.length)
})

const filteredLetters = computed(() => filteredGroups.value.map((g) => g.letter))

function onUpdateShow(val) {
  emit('update:show', val)
}

function close() {
  emit('update:show', false)
}

function pick(item) {
  emit('select', item)
  emit('update:show', false)
}
</script>

<style scoped>
.sheet {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}
.sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}
.sheet-header .link {
  border: 0;
  background: transparent;
  color: #646566;
  font-size: 14px;
  padding: 0;
}
.sheet-header .spacer {
  width: 2.5em;
}
.search {
  flex: none;
}
.sheet-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  position: relative;
}
.empty {
  text-align: center;
  padding: 40px 16px;
}
.muted {
  color: #969799;
}
</style>
