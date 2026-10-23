<script setup>
import { ref, computed } from 'vue'
import { askQuestion, submitFeedback } from '../api'
import { userId } from '../store/user'
import MarkdownView from '../components/MarkdownView.vue'

const fileInput = ref(null)
const preview = ref('')          // 本地预览 URL
const pickedFile = ref(null)
const busy = ref(false)
const result = ref(null)         // 答疑结果（QuestionOut）
const error = ref('')

// 反馈区
const selected = ref([])
const custom = ref('')
const fbBusy = ref(false)
const fbDone = ref(false)
const fbResult = ref(null)

const options = computed(() => result.value?.feedback_options || [])
const answerText = computed(() => result.value?.answer || '')

// 一图多题：逐题讲解 + 题号切换（单题时不显示按钮）
const activeProblem = ref(0)
const problems = computed(() => {
  const ps = result.value?.problems
  return Array.isArray(ps) ? ps.filter((p) => p && (p.answer || p.title)) : []
})
const shownAnswer = computed(() => {
  const ps = problems.value
  if (!ps.length) return result.value?.answer || ''
  const p = ps[Math.min(activeProblem.value, ps.length - 1)]
  return p?.answer || result.value?.answer || ''
})

function chooseFile() {
  fileInput.value?.click()
}

async function onFile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  if (preview.value) URL.revokeObjectURL(preview.value)
  pickedFile.value = f
  preview.value = URL.createObjectURL(f)
  // 重置上一轮结果
  result.value = null
  fbDone.value = false
  fbResult.value = null
  selected.value = []
  custom.value = ''
  error.value = ''
  activeProblem.value = 0
}

async function doAsk() {
  if (!pickedFile.value) return
  busy.value = true
  error.value = ''
  try {
    const clientId = 'web-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8)
    result.value = await askQuestion(pickedFile.value, userId.value, clientId)
    if (result.value.status === 'failed') {
      error.value = result.value.error_msg || '答疑失败，请重试'
    }
  } catch (e) {
    error.value = e.message || '请求失败'
  } finally {
    busy.value = false
  }
}

function reset() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  pickedFile.value = null
  result.value = null
  fbDone.value = false
  fbResult.value = null
  selected.value = []
  custom.value = ''
  error.value = ''
  activeProblem.value = 0
}

function toggle(tag) {
  const i = selected.value.indexOf(tag)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(tag)
}

async function doFeedback(solved = false) {
  if (!result.value) return
  if (!solved && !selected.value.length && !custom.value.trim()) {
    window.__toast?.('请至少选择一个原因，或填写自定义描述')
    return
  }
  fbBusy.value = true
  try {
    const notes = custom.value.trim() ? [custom.value.trim()] : []
    fbResult.value = await submitFeedback(result.value.id, {
      selected: solved ? [] : selected.value,
      custom: solved ? [] : notes,
      solved,
    })
    fbDone.value = true
    window.__toast?.(solved ? '已记录：看懂了 ✓' : `反馈已记录，画像已更新（影响 ${fbResult.value.kp_updated} 个知识点）`)
  } catch (e) {
    window.__toast?.('反馈提交失败：' + (e.message || ''))
  } finally {
    fbBusy.value = false
  }
}
</script>

<template>
  <div class="screen">
    <input ref="fileInput" type="file" accept="image/*" capture="environment" hidden @change="onFile" />

    <!-- 采集区 -->
    <div class="card">
      <h2>📷 拍照上传题目</h2>
      <p class="hint" style="margin-top: 0">
        拍下你要问的高数题，AI 会给出分步讲解；看完后可以告诉我"卡在哪"，帮我建立你的专属画像。
      </p>

      <div v-if="preview" style="margin-bottom: 12px">
        <img :src="preview" class="preview" alt="题目预览" />
      </div>
      <div v-else
        style="border: 1.5px dashed var(--line); border-radius: 12px; padding: 32px 16px; text-align: center; color: var(--ink-3); margin-bottom: 12px">
        <div style="font-size: 34px">🖼️</div>
        <div style="margin-top: 6px; font-size: 13px">尚未选择图片</div>
      </div>

      <div class="btn-row">
        <button class="btn" @click="chooseFile">{{ preview ? '重新选择' : '选择/拍摄图片' }}</button>
        <button class="btn primary" :disabled="!pickedFile || busy" @click="doAsk">
          {{ busy ? 'AI 解题中…' : '开始答疑' }}
        </button>
      </div>
      <button v-if="preview" class="btn ghost block" style="margin-top: 10px" @click="reset">清空重来</button>
    </div>

    <!-- 加载 -->
    <div v-if="busy" class="card loading">
      <div class="spinner"></div>
      正在识图推理（推理型模型通常需要 1~3 分钟，请稍候）…
    </div>

    <!-- 错误 -->
    <div v-else-if="error" class="card">
      <div class="banner err">{{ error }}</div>
      <button class="btn primary block" @click="doAsk">重试（同一题目 ID，后端会复用图片）</button>
    </div>

    <!-- 答疑结果 -->
    <template v-if="result && !busy">
      <div class="card">
        <h2>✅ AI 分步讲解</h2>

        <!-- 一图多题：在详解上方提供题号切换 -->
        <div v-if="problems.length > 1" class="problem-tabs">
          <button
            v-for="(p, i) in problems"
            :key="i"
            class="ptab"
            :class="{ on: activeProblem === i }"
            @click="activeProblem = i"
          >
            第 {{ p.no || i + 1 }} 题<template v-if="p.title"><span class="pt">· {{ p.title }}</span></template>
          </button>
        </div>
        <div v-else-if="problems.length === 1 && result.answer && problems[0].answer" class="banner" style="margin-bottom: 8px">
          照片识别到 1 道题
        </div>

        <div class="answer">
          <MarkdownView :text="shownAnswer" />
        </div>
      </div>

      <!-- 互动反馈（画像数据来源） -->
      <div class="card">
        <h2>💬 卡在哪里了？（可选，帮我更懂你）</h2>
        <p class="hint" style="margin-top: 0">多选或不限数量，也可以自己写。反馈会立即更新你的学习画像。</p>

        <div v-if="fbDone" class="banner" style="margin-bottom: 8px">
          ✓ 反馈已记录{{ fbResult ? `（影响 ${fbResult.kp_updated} 个知识点）` : '' }}
          <template v-if="fbResult?.score_delta < 0"> · 掌握度调整为 {{ fbResult.score_delta }}</template>
        </div>

        <template v-if="!fbDone">
          <div v-if="options.length" class="opt-list">
            <!-- 用原生 checkbox 承载选中态：移动端手指滑动不会连续触发多个选项 -->
            <label
              v-for="o in options"
              :key="o.tag"
              class="opt"
              :class="{ sel: selected.includes(o.tag) }"
            >
              <input
                type="checkbox"
                hidden
                :checked="selected.includes(o.tag)"
                @change="toggle(o.tag)"
              />
              <span class="k">{{ selected.includes(o.tag) ? '✓' : '+' }}</span>
              <span>{{ o.label }}</span>
            </label>
          </div>
          <p v-else class="muted">（本题未生成候选选项，可直接在下方描述）</p>

          <textarea
            v-model="custom"
            rows="2"
            placeholder="其他原因（可选），例如：公式忘了、没看懂第三步…"
            style="margin-top: 10px"
          ></textarea>

          <div class="btn-row" style="margin-top: 10px">
            <button class="btn ok" :disabled="fbBusy" @click="doFeedback(true)">我懂了</button>
            <button class="btn primary" :disabled="fbBusy" @click="doFeedback(false)">
              {{ fbBusy ? '提交中…' : '提交反馈' }}
            </button>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 一图多题：题号切换条 */
.problem-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--line);
}
.ptab {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink-2);
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ptab.on {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-weak);
  font-weight: 600;
}
.ptab .pt { opacity: 0.75; font-weight: 400; }
</style>
