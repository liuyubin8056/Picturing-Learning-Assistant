<script setup>
import { computed } from 'vue'
import { renderInline } from '../utils/markdown'

// 行内富文本：短文本里的公式/加粗/代码。
// 不产生 <p>，可以安全放进 <span>、<button>、flex 容器和表格单元格。
// 需要段落、列表、表格等块级结构时用 MarkdownView。
const props = defineProps({
  text: { type: [String, Number], default: '' },
})

const html = computed(() => renderInline(props.text))
</script>

<template>
  <span class="inline-md" v-html="html"></span>
</template>

<style scoped>
.inline-md {
  display: inline;
}
/* 行内公式不该撑开行高，也不能被白色空间规则折在奇怪的位置 */
.inline-md :deep(.katex) {
  font-size: 1em;
}
.inline-md :deep(.katex-display) {
  margin: 4px 0;
  overflow-x: auto;
  overflow-y: hidden;
}
</style>
