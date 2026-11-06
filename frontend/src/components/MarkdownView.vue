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
