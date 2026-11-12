// 后端 API 封装：统一前缀 /api/v1，错误统一抛出带 detail 的 Error。
//
// 两种运行形态：
// - Web：请求同源相对路径，由 Nginx/Vite 转发；登录凭证走 httpOnly Cookie
// - App（Capacitor）：页面在本地 file/localhost 里，必须指向远程服务器；
//   原生 WebView 跨域不带 Cookie，所以改用 Authorization: Bearer

/* global Capacitor */

const RAW_ORIGIN = (import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')

// 是否是打包后的 App：构建时注入 VITE_APP_MODE=app，或运行期有 Capacitor 桥
export const IS_APP =
  import.meta.env.VITE_APP_MODE === 'app' ||
  (typeof window !== 'undefined' && !!window.Capacitor?.isNativePlatform?.())

export const API_ORIGIN = RAW_ORIGIN
const BASE = RAW_ORIGIN + '/api/v1'

/** 拼出完整 API 地址（分片上传需要自己发 PUT 原始字节） */
export const apiUrl = (p) => BASE + p

const TOKEN_KEY = 'spl_token'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 隐私模式下 localStorage 不可用，退化为仅 Cookie */
  }
}

/** 静态资源（题图 / 上传图）绝对地址：Web 走相对，App 拼服务器源 */
export function mediaUrl(path) {
  if (!path) return ''
  if (/^(https?:|data:|blob:)/.test(path)) return path
  const p = path.startsWith('/') ? path : '/' + path
  return RAW_ORIGIN ? RAW_ORIGIN + p : p
}

/** 统一的鉴权头：App 用它替代 Cookie */
export function authHeaders(extra = {}) {
  const h = { 'X-Client': IS_APP ? 'app' : 'web', ...extra }
  const t = getToken()
  if (t) h['Authorization'] = `Bearer ${t}`
  return h
}

// 普通接口 30 秒；大模型接口单独放宽。
// 依据：答疑实测 30~90s，慢时 2~3 分钟；Nginx 那边是 300s，
// 前端超时留在 180s，比后端早一点断，用户能立刻看到提示而不是一直转。
const DEFAULT_TIMEOUT = 30000
export const LLM_TIMEOUT = 180000

/** 暴露给需要自己控制流程的调用方（导出下载、分片上传、图片请求） */
export async function authFetch(path, { method = 'GET', body, isForm, headers, timeout = DEFAULT_TIMEOUT, fullUrl, signal } = {}) {
  const h = authHeaders(headers)
  const opts = { method, headers: h }
  if (body !== undefined) {
    // 二进制与表单必须原样发：Blob 走 JSON.stringify 会变成 "{}"（2 字节），
    // 分片上传时会报"分片大小不符"，这个坑踩过一次
    const raw =
      isForm ||
      (typeof Blob !== 'undefined' && body instanceof Blob) ||
      (typeof FormData !== 'undefined' && body instanceof FormData) ||
      (typeof ArrayBuffer !== 'undefined' &&
        (body instanceof ArrayBuffer || ArrayBuffer.isView(body)))
    if (raw) {
      opts.body = body
    } else {
      h['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  // Web 端凭证在 Cookie 里，跨源请求（App 指向服务器）靠 Bearer，不需要 credentials
  opts.credentials = IS_APP ? 'omit' : 'same-origin'

  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  // 外部取消（用户退出页面）与超时共用一个 signal
  if (signal) signal.addEventListener('abort', () => ctrl.abort(), { once: true })
  try {
    return await fetch(fullUrl || BASE + path, { ...opts, signal: ctrl.signal })
  } finally {
    clearTimeout(timer)
  }
}

async function request(path, { method = 'GET', body, isForm, timeout = DEFAULT_TIMEOUT } = {}) {
  let res
  try {
    res = await authFetch(path, { method, body, isForm, timeout })
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`请求超时（已等待 ${Math.round(timeout / 1000)} 秒），网络较慢或服务繁忙，请稍后重试`)
    }
    throw new Error('网络连接失败，请检查网络后重试')
  }

  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text }
  }

  if (!res.ok) {
    // 登录态失效：广播事件，由 App.vue 统一跳登录页（避免 api ↔ store 循环依赖）
    if (res.status === 401 && !path.startsWith('/auth/')) {
      setToken('')
      window.dispatchEvent(new Event('auth:expired'))
    }
    // 限流：后端会带 retry_after，直接告诉用户等多久
    if (res.status === 429) {
      const wait = data?.retry_after
      throw new Error(wait ? `操作太频繁，请 ${wait} 秒后再试` : '操作太频繁，请稍后再试')
    }
    const msg = data?.detail || data?.message || `请求失败（HTTP ${res.status}）`
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }

  // App 端登录成功会把 token 放在响应体里，这里统一收口存储
  if (data && typeof data === 'object' && data.token) setToken(data.token)
  return data
}

export function clearToken() {
  setToken('')
}

// ---------- 账户（邮箱验证码登录） ----------
// 凭证走 httpOnly Cookie（Web 端），前端不接触 token
export const sendEmailCode = (email) =>
  request('/auth/email/send', { method: 'POST', body: { email } })

export const loginByCode = (email, code, consent = false) =>
  request('/auth/email/login', { method: 'POST', body: { email, code, consent } })

export const getMe = () => request('/auth/me')

export const setNickname = (nickname) =>
  request('/auth/me/nickname', { method: 'PUT', body: { nickname } })

export const logout = () => request('/auth/logout', { method: 'POST' })

export const demoLogin = () => request('/auth/demo-login', { method: 'POST' })

// 导出我的全部数据（JSON 下载）。走 fetch 是因为要带 Cookie，
// 且失败时能拿到后端的错误说明而不是一个空白页。
/** 取导出数据：返回 { blob, filename }，由调用方决定存哪儿 */
export async function fetchExportData() {
  const res = await authFetch('/auth/export', { timeout: 60000 })
  if (!res.ok) {
    let msg = `导出失败（HTTP ${res.status}）`
    try {
      const d = await res.json()
      if (d?.detail) msg = d.detail
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(msg)
  }
  const blob = await res.blob()
  return { blob, filename: filenameFromResponse(res) || fallbackFilename() }
}

/** 从 Content-Disposition 里取中文文件名（服务端用 RFC 5987 编码） */
function filenameFromResponse(res) {
  const raw = res.headers.get('Content-Disposition') || ''
  const star = raw.match(/filename\*=UTF-8''([^;]+)/i)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* 继续尝试下一个 */
    }
  }
  const plain = raw.match(/filename="([^"]+)"/i)
  return plain ? plain[1] : ''
}

/** 拿不到响应头时的兜底名：昵称 + 秒级时间 */
export function fallbackFilename(nickname) {
  const d = new Date()
  const p2 = (n) => String(n).padStart(2, '0')
  const ts = `${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}-${p2(d.getHours())}${p2(
    d.getMinutes()
  )}${p2(d.getSeconds())}`
  const name = (nickname || '我的数据').replace(/[\\/:*?"<>|]/g, '').slice(0, 24)
  return `学习数据-${name}-${ts}.json`
}

/** 导入学习数据（mode: merge 合并 / replace 覆盖） */
export const importMyData = (mode, data) =>
  request('/auth/import', { method: 'POST', body: { mode, data }, timeout: 60000 })

// ---------- 管理后台 ----------
export const adminUsers = () => request('/admin/users')
export const adminOverview = () => request('/admin/overview')
/** 时间轴：按天的 API 调用量与 Token 用量。
 *  - days=N：最近 N 天（含今天）
 *  - start/end：任意区间（今天 / 昨天 / 本月 / 上月 / 自定义用这个）
 *  - userId 为空表示全站 */
export const adminTimeline = ({ days = 30, start = null, end = null, userId = null } = {}) => {
  const qs = new URLSearchParams()
  if (start && end) {
    qs.set('start', start)
    qs.set('end', end)
  } else {
    qs.set('days', String(days))
  }
  if (userId != null) qs.set('user_id', String(userId))
  return request(`/admin/timeline?${qs.toString()}`)
}

// ---------- 答疑 ----------
/** 答疑：file 直接上传；传 uploadId 则复用已合并的分片上传结果 */
export const askQuestion = (file, userId, clientId, uploadId) => {
  const fd = new FormData()
  if (uploadId) fd.append('image_upload_id', uploadId)
  else fd.append('image', file)
  fd.append('user_id', String(userId))
  fd.append('client_question_id', clientId)
  return request('/questions', { method: 'POST', body: fd, isForm: true, timeout: LLM_TIMEOUT })
}
export const getQuestion = (id) => request(`/questions/${id}`)
export const listQuestions = (userId, limit = 20) =>
  request(`/users/${userId}/questions?limit=${limit}`)

// ---------- 反馈 / 画像 ----------
export const submitFeedback = (questionId, payload) =>
  request(`/profile/questions/${questionId}/feedback`, { method: 'POST', body: payload })
export const getProfile = (userId) => request(`/profile/users/${userId}`)
export const getRadar = (userId) => request(`/profile/users/${userId}/radar`)

// ---------- 诊断 ----------
export const generateDiagnose = (userId, useLlm = true) =>
  request(`/diagnose/users/${userId}?use_llm=${useLlm}`, { method: 'POST', timeout: LLM_TIMEOUT })
export const getLatestDiagnose = (userId) => request(`/diagnose/users/${userId}/latest`)
export const listDiagnose = (userId) => request(`/diagnose/users/${userId}`)

// ---------- 自测 ----------
export const createTest = (userId, { purpose = 'weakness', count = 6, chapter } = {}) => {
  const q = new URLSearchParams({ purpose, count: String(count) })
  if (chapter) q.set('chapter', chapter)
  return request(`/tests/users/${userId}/sessions?${q}`, { method: 'POST' })
}
export const getTest = (sid) => request(`/tests/sessions/${sid}`)
export const submitTest = (sid, answers) =>
  request(`/tests/sessions/${sid}/submit`, { method: 'POST', body: { answers } })
export const detailedSolution = (qid) =>
  request(`/tests/questions/${qid}/detailed-solution`, { method: 'POST', timeout: LLM_TIMEOUT })

// 练习/诊断解锁状态：拍照上传过题目（有答疑记录）才解锁
export const getUnlockStatus = (userId) =>
  request(`/tests/users/${userId}/unlock-status`)

// 看解析还不懂 → 带着困惑让模型换讲法（feedback_tags 会注入 prompt）
export const explainQuestion = (qid, payload) =>
  request(`/tests/questions/${qid}/explain`, { method: 'POST', body: payload, timeout: LLM_TIMEOUT })

// 考试式作答：上传手写解答照片，模型按答案匹配判分
export const judgeQuestionImage = (qid, file, userId) => {
  const fd = new FormData()
  fd.append('image', file)
  if (userId != null) fd.append('user_id', String(userId))
  return request(`/tests/questions/${qid}/judge-image`, { method: 'POST', body: fd, isForm: true, timeout: LLM_TIMEOUT })
}
export const listTests = (userId) => request(`/tests/users/${userId}/sessions`)

// ---------- 错题本 ----------
export const getWrongbook = (userId, status) =>
  request(`/wrongbook/users/${userId}${status ? `?status=${status}` : ''}`)
export const markMastered = (userId, wid, mastered = true) =>
  request(`/wrongbook/users/${userId}/${wid}/mastered?mastered=${mastered}`, { method: 'PUT' })

// ---------- 知识库 / 计量 ----------
export const getKbStats = () => request('/kb/stats')
export const getTokens = (userId) => request(`/tokens/summary?user_id=${userId}`)
