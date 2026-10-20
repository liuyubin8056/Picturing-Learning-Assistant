// 后端 API 封装：统一前缀 /api/v1，错误统一抛出带 detail 的 Error。
// 开发期由 Vite proxy 转发到 FastAPI（见 vite.config.js）。

const BASE = '/api/v1'

async function request(path, { method = 'GET', body, isForm } = {}) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    if (isForm) {
      opts.body = body // FormData，浏览器自动带 boundary
    } else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  const res = await fetch(BASE + path, opts)
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text }
  }
  if (!res.ok) {
    const msg = data?.detail || data?.message || `请求失败（HTTP ${res.status}）`
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data
}

// ---------- 答疑 ----------
export const askQuestion = (file, userId, clientId) => {
  const fd = new FormData()
  fd.append('image', file)
  fd.append('user_id', String(userId))
  fd.append('client_question_id', clientId)
  return request('/questions', { method: 'POST', body: fd, isForm: true })
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
  request(`/diagnose/users/${userId}?use_llm=${useLlm}`, { method: 'POST' })
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
  request(`/tests/questions/${qid}/detailed-solution`, { method: 'POST' })

// 看解析还不懂 → 带着困惑让模型换讲法（feedback_tags 会注入 prompt）
export const explainQuestion = (qid, payload) =>
  request(`/tests/questions/${qid}/explain`, { method: 'POST', body: payload })

// 考试式作答：上传手写解答照片，模型按答案匹配判分
export const judgeQuestionImage = (qid, file, userId) => {
  const fd = new FormData()
  fd.append('image', file)
  if (userId != null) fd.append('user_id', String(userId))
  return request(`/tests/questions/${qid}/judge-image`, { method: 'POST', body: fd, isForm: true })
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
