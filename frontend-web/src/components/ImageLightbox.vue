<template>
  <el-image-viewer
    v-if="url"
    :url-list="list"
    :initial-index="initialIndex"
    teleported
    @close="emit('close')"
  />
</template>

<script setup>
import { computed } from 'vue'
import { ElImageViewer } from 'element-plus'

const props = defineProps({
  url: { type: String, default: '' },
  urls: { type: Array, default: () => [] },
})

const emit = defineEmits(['close'])

const list = computed(() => (props.urls.length ? props.urls : [props.url]))
const initialIndex = computed(() => {
  const index = list.value.indexOf(props.url)
  return index >= 0 ? index : 0
})
</script>
