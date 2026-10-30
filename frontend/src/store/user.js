// 全局登录态。登录后 userId 由服务端返回的用户 id 决定（各页面仍按 userId 取数，无需改动）。
import { ref, watch } from 'vue'
import { getMe } from '../api'

const KEY = 'spl_user_id'
const saved = Number(localStorage.getItem(KEY) || 0)

export const userId = ref(saved > 0 ? saved : 1)
export const currentUser = ref(null)     // { id, email, email_masked, nickname, is_demo }
export const authReady = ref(false)      // 启动时是否已完成登录态探测

watch(userId, (v) => localStorage.setItem(KEY, String(v)))

export function setUserId(v) {
  const n = Number(v)
  if (Number.isFinite(n) && n > 0) userId.value = Math.floor(n)
}

/** 应用登录结果（登录/演示登录/刷新令牌后调用） */
export function applyLogin(payload) {
  if (payload?.user) {
    currentUser.value = payload.user
    userId.value = payload.user.id
  }
}

export function clearLogin() {
  currentUser.value = null
}

/** 启动时探测登录态：带 Cookie 调 /auth/me */
export async function bootstrapAuth() {
  try {
    const me = await getMe()
    currentUser.value = me
    userId.value = me.id
    return me
  } catch {
    currentUser.value = null
    return null
  } finally {
    authReady.value = true
  }
}

export const isLoggedIn = () => !!currentUser.value
