// 渲染工具：Markdown + LaTeX（KaTeX）。
//
// 处理流程（顺序很重要）：
//   1. 抽出数学片段（$$...$$ / $...$ / \[...\] / \(...\)）→ 占位符保护
//   2. 对"裸 LaTeX"做保守识别并包裹（兼容早期模型未加定界符的输出）
//   3. 走 Markdown 渲染（转义 + 结构）
//   4. 把占位符替换为 KaTeX 渲染结果（失败则回退原文，保证可读）
//
// 不引入完整 markdown 库：画像/报告/讲解的格式由本项目后端生成，可控。

import katex from 'katex'

const PLACEHOLDER = (i) => `\u0000MATH${i}\u0000`

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
}

// ---------- 0) 软断行：兼容"整段无换行"的历史数据 ----------
// 旧版模型输出可能把多个步骤挤成一段（无 \n）。这里在明确的步骤标记前断行，
// 仅在文本较长时启用，避免误伤短句。
function softBreaks(text) {
  if (text.length < 100 || text.includes('\n')) return text
  return text.replace(
    /(?<!\n)(?=(?:步骤[一二三四五六七八九十]|第[一二三四五六七八九十]步)[：:])/g,
    '\n'
  )
}

// ---------- 1) 数学片段抽取 ----------
// 行内公式允许跨行：模型/提取脚本常把长公式折行，旧正则 [^$\n] 遇到换行就整段失效，
// 表现为公式以源码 `\int_0^\pi...` 的形式裸露在页面上。这里放宽到 [^$]，并限长防回溯。
const MATH_RE = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$]{1,1200}?\$)/g

// ---------- 2) 裸 LaTeX 保守识别 ----------
// 仅当片段"含反斜杠命令"或"含 ^/_ 加数字/字母"且不含中文时，才认为是数学。
// 例：a_0+a_1x+\cdots+a_8x^8=(2x-1)^8 → 整体包裹为 $...$
const LATEX_CMD = /\\[a-zA-Z]+/
const SUPER_SUB = /[\^_]\s*[-+]?[0-9a-zA-Z{(]/

function wrapBareLatex(text) {
  // 以"非中文、非标点边界"切块：把连续的非中文串（可含空格）视为候选
  return text
    .split(/([\u4e00-\u9fff，。；：、？！「」（）【】]+)/)
    .map((seg) => {
      if (!seg || /[\u4e00-\u9fff]/.test(seg)) return seg
      if (!LATEX_CMD.test(seg) && !SUPER_SUB.test(seg)) return seg
      // 去掉首尾空白再包裹，保留原空格
      const m = seg.match(/^(\s*)([\s\S]*?)(\s*)$/)
      if (!m) return seg
      const [, head, body, tail] = m
      if (!body) return seg
      // 已经含 $ 的不再处理（避免嵌套）
      if (body.includes('$')) return seg
      return `${head}$${body}$${tail}`
    })
    .join('')
}

function extractMath(text) {
  const store = []
  const push = (tex, display) => {
    store.push({ tex, display })
    return PLACEHOLDER(store.length - 1)
  }

  let out = text.replace(MATH_RE, (m) => {
    if (m.startsWith('$$')) return push(m.slice(2, -2), true)
    if (m.startsWith('\\[')) return push(m.slice(2, -2), true)
    if (m.startsWith('\\(')) return push(m.slice(2, -2), false)
    return push(m.slice(1, -1), false)
  })

  // 抽取后再对剩余文本做裸 LaTeX 包裹（此时已无标准定界符）
  out = wrapBareLatex(out)
  out = out.replace(/\$([^$]{1,1200}?)\$/g, (mm, tex) => push(tex, false))
  return { text: out, store }
}

// ---------- 3) Markdown 渲染（与之前一致，输入已用占位符保护） ----------
function renderMd(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const out = []
  let i = 0
  let inList = false
  const closeList = () => { if (inList) { out.push('</ul>'); inList = false } }

  while (i < lines.length) {
    const line = lines[i]
    const t = line.trim()

    if (t.startsWith('|')) {
      closeList()
      const rows = []
      while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(lines[i].trim()); i++ }
      if (rows.length >= 2) {
        const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
        const head = cells(rows[0])
        const body = rows.slice(1).filter((r) => !/^\|[\s:|-]+\|$/.test(r))
        out.push('<table><thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>')
        for (const r of body) out.push('<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>')
        out.push('</tbody></table>')
      }
      continue
    }

    if (/^#{1,6}\s/.test(t)) {
      closeList()
      const lv = Math.min(t.match(/^#+/)[0].length, 3)
      out.push(`<h${lv}>${inline(t.replace(/^#+\s*/, ''))}</h${lv}>`)
    } else if (/^[-*]\s+/.test(t)) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push(`<li>${inline(t.replace(/^[-*]\s+/, ''))}</li>`)
    } else if (/^\d+[.、]\s*/.test(t)) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push(`<li>${inline(t.replace(/^\d+[.、]\s*/, ''))}</li>`)
    } else if (/^>\s?/.test(t)) {
      closeList()
      out.push(`<blockquote>${inline(t.replace(/^>\s?/, ''))}</blockquote>`)
    } else if (/^-{3,}$/.test(t)) {
      closeList()
      out.push('<hr/>')
    } else if (t === '') {
      closeList()
    } else {
      closeList()
      out.push(`<p>${inline(t)}</p>`)
    }
    i++
  }
  closeList()
  return out.join('\n')
}

function inline(s) {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

// ---------- 4) KaTeX 渲染 ----------
function renderMath(store) {
  return store.map(({ tex, display }) => {
    try {
      return katex.renderToString(tex, {
        displayMode: display,
        throwOnError: false,
        strict: false,
        trust: false,
        output: 'html',
      })
    } catch {
      return `<code>${esc(tex)}</code>` // 渲染失败回退为原文，保证内容不丢
    }
  })
}

/**
 * 修正模型输出里常见的两种"表示问题"，避免页面上出现乱码感：
 *  1) 字面 \n（反斜杠+n）被当成正文 → 显示成可见的 "\n"
 *     —— 只替换后面不接字母的，避免误伤 \nu \nabla \neq 等命令
 *  2) $ 定界符数量为奇数（公式被截断）→ 后半段公式退回成源代码
 *     —— 补一个 $ 收尾，让 KaTeX 至少能渲染出前半段
 */
function normalizeTex(text) {
  let t = text.replace(/\\n(?![a-zA-Z])/g, '\n')
  const dollars = t.replace(/\\\$/g, '').split('$').length - 1
  if (dollars % 2 === 1) t += '$'
  return t
}

export function renderMarkdown(md) {
  if (!md) return ''
  const { text, store } = extractMath(softBreaks(normalizeTex(String(md))))
  const html = renderMd(text)
  if (!store.length) return html
  const rendered = renderMath(store) // 只渲染一次，避免替换时重复计算
  // 占位符可能被包在 <p>/<li> 内，全局替换即可
  return html.replace(/\u0000MATH(\d+)\u0000/g, (_, idx) => rendered[Number(idx)] ?? '')
}