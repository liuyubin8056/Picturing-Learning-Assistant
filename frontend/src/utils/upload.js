// 断点续传上传器（Web 与 App 共用同一份实现）。
//
// 协议见 backend/app/services/upload_service.py：
//   init → 逐片 PUT → complete
//
// 断点怎么续：把 (文件名, 大小, 修改时间) 作为指纹，记下 upload_id 到 localStorage；
// 用户重新选同一张图时先问服务端"哪些片已收到"，只补缺口。
// 弱网下每片单独重试 3 次（600ms / 1.5s / 3s 退避），失败不丢已传的分片。

import { apiUrl, authFetch } from '../api'

const STATE_KEY = 'spl_upload_state'
const MAX_RETRY = 3
const RETRY_DELAYS = [600, 1500, 3000]
const CHUNK_TIMEOUT = 60000
const META_TIMEOUT = 20000

function fingerprint(file) {
  return `${file.name}|${file.size}|${file.lastModified || 0}`
}

function loadState() {
  try {
    return JSON.parse(localStorage.getItem(STATE_KEY) || '{}')
  } catch {
    return {}
  }
}

function saveState(map) {
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify(map))
  } catch {
    /* 隐私模式忽略 */
  }
}

function recall(file, uploadId) {
  const map = loadState()
  map[fingerprint(file)] = { uploadId, at: Date.now() }
  saveState(map)
}

/** 是否还有未完成的上传（用于首页提示"继续上传"） */
export function pendingUpload(file) {
  const st = loadState()[fingerprint(file)]
  return st?.uploadId || ''
}

export function forgetUpload(file) {
  const map = loadState()
  delete map[fingerprint(file)]
  saveState(map)
}

async function readError(res, fallback) {
  try {
    const d = await res.json()
    return d?.detail || fallback
  } catch {
    return fallback
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function putChunk(uploadId, index, blob, signal) {
  let lastErr
  for (let attempt = 0; attempt < MAX_RETRY; attempt++) {
    try {
      const res = await authFetch('', {
        method: 'PUT',
        fullUrl: apiUrl(`/uploads/${uploadId}/chunks/${index}`),
        body: blob,
        headers: { 'Content-Type': 'application/octet-stream' },
        timeout: CHUNK_TIMEOUT,
        signal,
      })
      if (res.ok) return await res.json()
      // 4xx 是协议错误（大小不符/越界），重试无用，直接抛
      if (res.status >= 400 && res.status < 500) {
        throw new Error(await readError(res, `分片 ${index} 上传失败`))
      }
      lastErr = new Error(`分片 ${index} 上传失败（HTTP ${res.status}）`)
    } catch (e) {
      if (e.name === 'AbortError') throw e
      // 服务端明确拒绝（4xx）不再重试
      if (/分片|越界|完成|不存在/.test(e.message || '')) throw e
      lastErr = e
    }
    // 还没到最后一次，等一会儿再来
    if (attempt < MAX_RETRY - 1) await sleep(RETRY_DELAYS[attempt])
  }
  throw lastErr || new Error(`分片 ${index} 上传失败`)
}

/**
 * 分片上传文件，返回 upload_id（可直接传给答疑接口）。
 * @param {File} file
 * @param {{onProgress?: (p:{percent:number, uploaded:number, total:number, resumed:boolean}) => void, signal?: AbortSignal}} opts
 */
export async function uploadResumable(file, { onProgress, signal } = {}) {
  if (!file) throw new Error('没有选择文件')
  let meta = null
  const remembered = pendingUpload(file)

  // ① 有历史记录：先问服务端进度，能续就续
  if (remembered) {
    try {
      const res = await authFetch(`/uploads/${remembered}`, { timeout: META_TIMEOUT, signal })
      if (res.ok) {
        meta = await res.json()
        if (meta.status === 'completed') {
          forgetUpload(file)
          return meta.upload_id
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') throw e
      meta = null
    }
  }

  // ② 没有可用会话：新建
  if (!meta) {
    const res = await authFetch('/uploads/init', {
      method: 'POST',
      body: {
        filename: file.name || 'photo.jpg',
        size: file.size,
        content_type: file.type || 'image/jpeg',
      },
      timeout: META_TIMEOUT,
      signal,
    })
    if (!res.ok) throw new Error(await readError(res, '创建上传会话失败'))
    meta = await res.json()
    recall(file, meta.upload_id)
  }

  const uploadId = meta.upload_id
  const cs = meta.chunk_size
  const total = meta.total_chunks
  const received = new Set(meta.received || [])
  const resumed = received.size > 0

  const sizeOf = (i) => Math.min(cs, file.size - i * cs)
  let uploaded = [...received].reduce((n, i) => n + sizeOf(i), 0)
  const report = () =>
    onProgress?.({
      percent: Math.floor((uploaded / file.size) * 100),
      uploaded,
      total: file.size,
      resumed,
    })
  report()

  // ③ 只补缺口（可乱序，一片失败不影响其它已完成分片）
  for (let i = 0; i < total; i++) {
    if (signal?.aborted) throw new DOMException('已取消', 'AbortError')
    if (received.has(i)) continue
    const start = i * cs
    const blob = file.slice(start, Math.min(start + cs, file.size))
    await putChunk(uploadId, i, blob, signal)
    uploaded += blob.size
    report()
  }

  // ④ 合并
  const done = await authFetch(`/uploads/${uploadId}/complete`, {
    method: 'POST',
    timeout: CHUNK_TIMEOUT,
    signal,
  })
  if (!done.ok) throw new Error(await readError(done, '合并分片失败'))

  forgetUpload(file)
  return uploadId
}
