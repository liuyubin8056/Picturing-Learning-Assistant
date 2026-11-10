<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { userId, currentUser, clearLogin } from './store/user'
import Icon from './components/Icon.vue'

const route = useRoute()
const router = useRouter()

// 登录页与隐私政策页都是「无壳」页面：不显示顶栏/副标题/底栏
const isBare = computed(() => !!route.meta.public)

const tabs = [
  { path: '/camera', icon: 'camera', label: '拍照' },
  { path: '/practice', icon: 'pencil', label: '练习' },
  { path: '/diagnose', icon: 'chart', label: '诊断' },
  { path: '/profile', icon: 'user', label: '我的' },
]

const title = computed(() => route.meta.title || '智能拍照学习助手')
const subtitle = computed(() => route.meta.subtitle || '拍下题目，AI 带你一步步看懂')

// 顶栏显示登录身份；未登录（极少见）退回用户 id
const displayName = computed(
  () => currentUser.value?.nickname || currentUser.value?.email_masked || `用户 ${userId.value}`
)
const avatarText = computed(() => {
  const n = (displayName.value || '').trim()
  if (!n) return '?'
  const first = n[0]
  return /[\u4e00-\u9fff]/.test(first) ? first : first.toUpperCase()
})

// 任一接口返回 401 → 登录态失效，统一回登录页
function onAuthExpired() {
  clearLogin()
  if (route.path !== '/login') router.replace('/login')
}
window.addEventListener('auth:expired', onAuthExpired)

const bodyEl = ref(null)
const scrolled = ref(false)
function onScroll() {
  scrolled.value = (bodyEl.value?.scrollTop || 0) > 4
}

const toast = ref('')
let toastTimer = null

// 全局轻提示（子组件统一通过 window.__toast?.() 调用）
window.__toast = (msg, ms = 2200) => {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), ms)
}

watch(
  () => route.path,
  () => {
    document.title = `${title.value} · 智能拍照学习助手`
    if (bodyEl.value) bodyEl.value.scrollTop = 0
  },
  { immediate: true }
)

onMounted(() => {
  bodyEl.value?.addEventListener('scroll', onScroll, { passive: true })
})
onBeforeUnmount(() => {
  bodyEl.value?.removeEventListener('scroll', onScroll)
  window.removeEventListener('auth:expired', onAuthExpired)
})
</script>

<template>
  <div class="app-shell">
    <div ref="bodyEl" class="app-body">
      <header v-if="!isBare" class="appbar" :class="{ scrolled }">
        <router-link to="/camera" class="logo" aria-label="回到首页">
          <Icon name="sparkles" :size="21" :stroke="1.9" />
        </router-link>
        <div class="appbar-text">
          <h1>{{ title }}</h1>
          <p>
            <span>智能拍照学习助手</span>
            <span class="dot"></span>
            <span>{{ displayName }}<template v-if="currentUser?.is_demo"> · 演示</template></span>
          </p>
        </div>
        <router-link to="/profile" class="avatar" :aria-label="`${displayName} 的档案`">
          <span>{{ avatarText }}</span>
        </router-link>
      </header>

      <p v-if="!isBare" class="route-sub">{{ subtitle }}</p>

      <!-- keep-alive：切到其它页再回来，拍照/练习的进度不被清空（登录页不缓存） -->
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <keep-alive :exclude="['LoginView']">
            <component :is="Component" :key="route.path" />
          </keep-alive>
        </transition>
      </router-view>
    </div>

    <nav v-if="!isBare" class="tabbar">
      <router-link
        v-for="t in tabs"
        :key="t.path"
        :to="t.path"
        :class="{ on: route.path === t.path }"
        :aria-current="route.path === t.path ? 'page' : undefined"
      >
        <span class="tab-ic"><Icon :name="t.icon" :size="21" :stroke="1.9" /></span>
        <span class="tab-label">{{ t.label }}</span>
      </router-link>
    </nav>

    <transition name="toast">
      <div v-if="toast" class="toast" role="status">
        <Icon name="check" :size="15" :stroke="2.4" />
        <span>{{ toast }}</span>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.route-sub {
  padding: 0 18px;
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--ink-3);
  letter-spacing: 0.01em;
}

/* 中文昵称单字在 38px 圆内偏小，略放大 */
.appbar .avatar span {
  font-size: 15px;
  font-weight: 700;
}

/* 桌面端卡片内，副标题不贴顶 */
@media (min-width: 640px) {
  .route-sub {
    padding-top: 2px;
  }
}
</style>
