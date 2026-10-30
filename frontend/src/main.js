import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import 'katex/dist/katex.min.css'
import './styles/base.css'

import CameraView from './views/CameraView.vue'
import PracticeView from './views/PracticeView.vue'
import DiagnoseView from './views/DiagnoseView.vue'
import ProfileView from './views/ProfileView.vue'
import LoginView from './views/LoginView.vue'
import { authReady, bootstrapAuth, currentUser } from './store/user'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/camera' },
    { path: '/login', component: LoginView, meta: { title: '登录', public: true } },
    { path: '/camera', component: CameraView, meta: { title: '拍照答疑' } },
    { path: '/practice', component: PracticeView, meta: { title: '练习' } },
    { path: '/diagnose', component: DiagnoseView, meta: { title: '诊断' } },
    { path: '/profile', component: ProfileView, meta: { title: '我的' } },
  ],
})

// 路由守卫：未登录一律去登录页（演示账号可在登录页一键进入）
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  if (!authReady.value) await bootstrapAuth()
  if (!currentUser.value) {
    return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  }
  return true
})

createApp(App).use(router).mount('#app')
