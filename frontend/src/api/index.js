// 后端 API 封装：统一前缀 /api/v1，错误统一抛出带 detail 的 Error。
// 开发期由 Vite proxy 转发到 FastAPI（见 vite.config.js）。

const BASE = '/api/v1'

// 普通接口 30 秒；大模型接口单独放宽。
// 依据：答疑实测 30~90s，慢时 2~3 分钟；Nginx 那边是 300s，
// 前端超时留在 180s，比后端早一点断，用户能立刻看到提示而不是一直转。
const DEFAULT_TIMEOUT = 30000
export const LLM_TIMEOUT = 180000

async function request(path, { method = 'GET', body, isForm, timeout = DEFAULT_TIMEOUT } = {}) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    if (isForm) {
      opts.body = body // FormData，浏览器自动带 boundary
    } else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }

  // 没有超时的话，网络卡住时用户只会看到一直转圈，分不清"在算"还是"挂了"
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)

  let res
  try {
    res = await fetch(BASE + path, { ...opts, signal: ctrl.signal })
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`请求超时（已等待 ${Math.round(timeout / 1000)} 秒），网络较慢或服务繁忙，请稍后重试`)
    }
    throw new Error('网络连接失败，请检查网络后重试')
  } finally {
    clearTimeout(timer)
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
  return data
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
export const exportMyData = async () => {
  const res = await fetch(BASE + '/auth/export')
  if (!res.ok) {
    let msg = `导出失败（HTTP ${res.status}）`
    try {
      const d = await res.json()
      if (d?.detail) msg = d.detail
    } catch { /* 忽略解析失败 */ }
    throw new Error(msg)
  }
  const blob = await res.blob()
  const name = `learnmate-我的数据-${new Date().toISOString().slice(0, 10)}.json`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ---------- 答疑 ----------
export const askQuestion = (file, userId, clientId) => {
  const fd = new FormData()
  fd.append('image', file)
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
