<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { userId } from './store/user'

const route = useRoute()

const tabs = [
  { path: '/camera', ic: '📷', label: '拍照' },
  { path: '/practice', ic: '✏️', label: '练习' },
  { path: '/diagnose', ic: '📊', label: '诊断' },
  { path: '/profile', ic: '👤', label: '我的' },
]

const title = computed(() => route.meta.title || '智能拍照学习助手')
const toast = ref('')
let toastTimer = null

// 全局轻提示（供子组件通过 provide/inject 或事件使用）
window.__toast = (msg, ms = 2200) => {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), ms)
}
</script>

<template>
  <div class="app-shell">
    <header class="appbar">
      <span class="logo">∑</span>
      <div>
        <b>{{ title }}</b>
        <small>智能拍照学习助手 · 用户 {{ userId }}</small>
      </div>
      <span class="spacer"></span>
    </header>

    <router-view v-slot="{ Component }">
      <component :is="Component" />
    </router-view>

    <nav class="tabbar">
      <router-link
        v-for="t in tabs"
        :key="t.path"
        :to="t.path"
        :class="{ on: route.path === t.path }"
      >
        <span class="ic">{{ t.ic }}</span>
        <span>{{ t.label }}</span>
      </router-link>
    </nav>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>
