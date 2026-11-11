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
import PrivacyView from './views/PrivacyView.vue'
import AdminView from './views/AdminView.vue'
import { authReady, bootstrapAuth, currentUser } from './store/user'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/camera' },
    {
      path: '/login',
      component: LoginView,
      meta: { title: '登录', subtitle: '用邮箱验证码进入你的学习档案', public: true },
    },
    {
      path: '/privacy',
      component: PrivacyView,
      meta: { title: '隐私政策', public: true },
    },
    {
      // 管理后台：专属地址，自己处理登录（不经过主壳的守卫）
      path: '/admin',
      component: AdminView,
      meta: { title: '管理后台', public: true },
    },
    {
      path: '/camera',
      component: CameraView,
      meta: { title: '拍照答疑', subtitle: '拍下题目，AI 带你一步步看懂' },
    },
    {
      path: '/practice',
      component: PracticeView,
      meta: { title: '针对练习', subtitle: '只练你薄弱的那几步，练完即时反馈' },
    },
    {
      path: '/diagnose',
      component: DiagnoseView,
      meta: { title: '学习诊断', subtitle: '看清自己的知识地图，找到下一步' },
    },
    {
      path: '/profile',
      component: ProfileView,
      meta: { title: '我的档案', subtitle: '错题本、学习画像与个人设置' },
    },
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
