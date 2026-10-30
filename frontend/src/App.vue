<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { userId, currentUser, clearLogin } from './store/user'
import { logout as apiLogout } from './api'

const route = useRoute()
const router = useRouter()

const isLogin = computed(() => route.path === '/login')
const displayName = computed(
  () => currentUser.value?.nickname || currentUser.value?.email_masked || `用户 ${userId.value}`
)

// 任一接口返回 401 → 登录态失效，统一回登录页
window.addEventListener('auth:expired', () => {
  clearLogin()
  if (route.path !== '/login') router.replace('/login')
})

async function doLogout() {
  try {
    await apiLogout()
  } catch {
    /* 令牌可能已失效，忽略 */
  }
  clearLogin()
  router.replace('/login')
}

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
    <header class="appbar" v-if="!isLogin">
      <span class="logo">∑</span>
      <div class="who">
        <b>{{ title }}</b>
        <small>{{ displayName }}<template v-if="currentUser?.is_demo"> · 演示账号</template></small>
      </div>
      <span class="spacer"></span>
      <button class="logout" @click="doLogout">退出</button>
    </header>

    <!-- keep-alive：切到其它页再回来，拍照/练习的进度不被清空 -->
    <router-view v-slot="{ Component }">
      <keep-alive>
        <component :is="Component" />
      </keep-alive>
    </router-view>

    <nav class="tabbar" v-if="!isLogin">
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
