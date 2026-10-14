import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import 'katex/dist/katex.min.css'
import './styles/base.css'

import CameraView from './views/CameraView.vue'
import PracticeView from './views/PracticeView.vue'
import DiagnoseView from './views/DiagnoseView.vue'
import ProfileView from './views/ProfileView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/camera' },
    { path: '/camera', component: CameraView, meta: { title: '拍照答疑' } },
    { path: '/practice', component: PracticeView, meta: { title: '练习' } },
    { path: '/diagnose', component: DiagnoseView, meta: { title: '诊断' } },
    { path: '/profile', component: ProfileView, meta: { title: '我的' } },
  ],
})

createApp(App).use(router).mount('#app')
