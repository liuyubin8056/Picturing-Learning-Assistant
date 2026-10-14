// 简单的全局状态：当前用户 ID（无登录体系，用 localStorage 持久化，便于演示多用户）
import { ref, watch } from 'vue'

const KEY = 'spl_user_id'
const saved = Number(localStorage.getItem(KEY) || 0)

export const userId = ref(saved > 0 ? saved : 1)

watch(userId, (v) => localStorage.setItem(KEY, String(v)))

export function setUserId(v) {
  const n = Number(v)
  if (Number.isFinite(n) && n > 0) userId.value = Math.floor(n)
}
