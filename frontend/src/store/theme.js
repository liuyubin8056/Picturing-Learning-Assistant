import { ref, watch } from 'vue'

// 主题：浅色 / 深色 / 跟随系统
// - index.html 里的内联脚本会在首屏前先应用一次，避免深色闪白
// - 默认浅色；选「跟随系统」时记住选择，系统主题变化实时生效
const KEY = 'spl_theme'
const media = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-color-scheme: dark)')
  : null

const saved = typeof localStorage !== 'undefined' ? localStorage.getItem(KEY) : null

// 默认浅色：进入应用先看到明亮的主界面，深色留给夜间主动选择
// mode 是用户的选择（light/dark/system），theme 是最终生效的主题
export const mode = ref(['light', 'dark', 'system'].includes(saved) ? saved : 'light')
export const theme = ref(
  mode.value === 'system' ? (media && media.matches ? 'dark' : 'light') : mode.value
)

function apply(value) {
  const root = document.documentElement
  root.dataset.theme = value
  root.style.colorScheme = value
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', value === 'dark' ? '#0A0F1E' : '#F4F6FD')
}

function sync() {
  theme.value = mode.value === 'system'
    ? (media && media.matches ? 'dark' : 'light')
    : mode.value
}

apply(theme.value)

watch(theme, apply)

watch(mode, (value) => {
  try {
    localStorage.setItem(KEY, value)
  } catch {
    /* 隐私模式下忽略 */
  }
  sync()
})

if (media && media.addEventListener) {
  media.addEventListener('change', () => {
    if (mode.value === 'system') sync()
  })
}

export function setMode(value) {
  mode.value = value === 'dark' || value === 'light' ? value : 'system'
}

// 兼容旧调用
export function setTheme(value) {
  setMode(value)
}

export function toggleTheme() {
  setMode(theme.value === 'dark' ? 'light' : 'dark')
}

// 恢复「跟随系统」
export function followSystem() {
  setMode('system')
}
