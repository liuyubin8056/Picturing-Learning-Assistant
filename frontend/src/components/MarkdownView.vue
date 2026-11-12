<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'

// 统一的内容渲染组件：Markdown + LaTeX（KaTeX）。
// 注意：必须走 renderMarkdown —— 它负责转义（防 XSS）与公式渲染，
// 直接 v-html 原始文本会既丢格式又有注入风险。
const props = defineProps({
  text: { type: String, default: '' },
})

const html = computed(() => renderMarkdown(props.text))
</script>

<template>
  <div class="md" v-html="html"></div>
</template>

<style scoped>
/* KaTeX 默认 font-size 是 1.21em，比中文正文明显大一号，
   和汉字混排时看起来像"公式在喊话"。压到正文尺寸附近才自然。 */
.md :deep(.katex) {
  font-size: 1.04em;
}
/* 块级公式宽度可能超过手机屏，允许横向滚动而不是把整页撑宽 */
.md :deep(.katex-display) {
  margin: 12px 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 2px;
}
</style>
