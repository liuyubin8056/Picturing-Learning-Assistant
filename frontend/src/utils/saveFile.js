// 保存导出文件：Web 走浏览器下载，App 写入手机目录（带降级）。
//
// Android 存储的现实（决定了这段代码的形状）：
// - Android ≤10：可以直写公共「下载 / 文档」目录
// - Android 11+：分区存储，普通应用**只能写自己创建的目录**，
//   直写公共 Downloads 会 EACCES。所以按三级降级：
//     ① downloadFile 到公共「文档」  → 老系统/宽松 ROM 能成
//     ② 写应用外部目录 Android/data/<包名>/files  → 一定能成，文件管理器可见
//     ③ 写缓存 + 调系统分享 → 用户自己选"保存到文件/下载"
// 每一级都会返回实际落点，前端照实提示，不糊弄用户。

import { API_ORIGIN, IS_APP, authHeaders } from '../api'

function webDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * @returns {Promise<{where: 'browser'|'downloads'|'documents'|'appdir'|'share', path?: string}>}
 */
export async function saveJsonFile({ blob, filename }) {
  if (!IS_APP) {
    webDownload(blob, filename)
    return { where: 'browser', path: '浏览器的「下载」目录' }
  }

  const { Filesystem, Directory, Encoding } = await import('@capacitor/filesystem')
  const text = await blob.text()

  // ① 公共「文档」目录（Android 10 及以下 / 部分厂商 ROM 可行）
  try {
    const r = await Filesystem.downloadFile({
      url: `${API_ORIGIN}/api/v1/auth/export`,
      path: filename,
      // 传原始目录名，插件用它拼公共目录（Document / Download 都是合法值）
      directory: 'DOCUMENTS',
      headers: authHeaders(),
    })
    return { where: 'downloads', path: r.path || `文档/${filename}` }
  } catch (e) {
    /* 分区存储会拦，继续降级 */
  }

  // ② 应用外部目录：无需权限，文件管理器可见（Android/data/<包名>/files）
  try {
    const r = await Filesystem.writeFile({
      path: `导出/${filename}`,
      data: text,
      directory: Directory.External,
      encoding: Encoding.UTF8,
      recursive: true,
    })
    return { where: 'appdir', path: r.uri || `Android/data/com.learnmate.app/files/导出/${filename}` }
  } catch (e) {
    /* 继续降级 */
  }

  // ③ 缓存 + 系统分享：把"存哪儿"交给用户
  const r = await Filesystem.writeFile({
    path: filename,
    data: text,
    directory: Directory.Cache,
    encoding: Encoding.UTF8,
  })
  const { Share } = await import('@capacitor/share')
  await Share.share({
    title: filename,
    text: '学习数据备份，请选择"保存到文件"存到手机里',
    url: r.uri,
    dialogTitle: '保存数据文件',
  })
  return { where: 'share', path: '已打开系统保存面板' }
}

/** 读取用户选中的 JSON 文件（Web 与 App 都用同一个 input[type=file]） */
export function readJsonFile(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onerror = () => reject(new Error('读取文件失败'))
    fr.onload = () => {
      try {
        resolve(JSON.parse(String(fr.result)))
      } catch {
        reject(new Error('不是有效的 JSON 文件'))
      }
    }
    fr.readAsText(file, 'utf-8')
  })
}
