<script setup>
import { ref, computed } from 'vue'
import { askQuestion, submitFeedback } from '../api'
import { userId } from '../store/user'
import MarkdownView from '../components/MarkdownView.vue'
import Icon from '../components/Icon.vue'

const fileInput = ref(null)
const preview = ref('') // 本地预览 URL
const pickedFile = ref(null)
const busy = ref(false)
// 已等待秒数：让用户能区分"模型在思考"和"页面卡死了"
const waited = ref(0)
let waitTimer = null

function startWaiting() {
  waited.value = 0
  clearInterval(waitTimer)
  waitTimer = setInterval(() => (waited.value += 1), 1000)
}

function stopWaiting() {
  clearInterval(waitTimer)
  waitTimer = null
}
const result = ref(null) // 答疑结果（QuestionOut）
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
  // 允许再次选择同一张图片
  e.target.value = ''
}

async function doAsk() {
  if (!pickedFile.value) return
  busy.value = true
  error.value = ''
  startWaiting()
  try {
    const clientId = 'web-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8)
    result.value = await askQuestion(pickedFile.value, userId.value, clientId)
    if (result.value.status === 'failed') {
      error.value = result.value.error_msg || '答疑失败，请重试'
    }
  } catch (e) {
    error.value = e.message || '请求失败'
  } finally {
    stopWaiting()
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
    window.__toast?.(
      solved ? '已记录：看懂了 ✓' : `反馈已记录，画像已更新（影响 ${fbResult.value.kp_updated} 个知识点）`
    )
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

    <!-- 首屏引导 -->
    <section v-if="!busy && !result && !error" class="hero">
      <span class="hero-eq one">∫</span>
      <span class="hero-eq two">∑</span>
      <span class="hero-eq three">lim</span>
      <p class="hero-eyebrow">
        <Icon name="sparkles" :size="13" :stroke="2" />
        AI 拍照答疑
      </p>
      <h2 class="hero-title">拍一道题，<br />看见你卡在哪</h2>
      <p class="hero-sub">分步讲解 · 错因反馈 · 自动沉淀成你的学习画像</p>
      <div class="hero-chips">
        <span>分步讲解</span>
        <span>一图多题</span>
        <span>越用越懂你</span>
      </div>
    </section>

    <!-- 采集区 -->
    <section v-if="!result || busy" class="card capture">
      <template v-if="!preview">
        <button type="button" class="dropzone" @click="chooseFile">
          <span class="dz-ico"><Icon name="camera" :size="26" :stroke="1.7" /></span>
          <b>拍下题目，或从相册选择</b>
          <span class="dz-sub">支持 JPG / PNG，题干与公式都能识别</span>
        </button>
      </template>

      <template v-else>
        <div class="shot-preview">
          <img :src="preview" class="preview" alt="题目预览" />
          <div class="shot-tools">
            <button type="button" class="icon-btn" title="重新拍摄" @click="chooseFile">
              <Icon name="refresh" :size="16" :stroke="2" />
            </button>
            <button type="button" class="icon-btn" title="清空" @click="reset">
              <Icon name="x" :size="16" :stroke="2" />
            </button>
          </div>
        </div>
      </template>

      <button class="btn primary block ask-btn" :disabled="!pickedFile || busy" @click="doAsk">
        <Icon v-if="!busy" name="sparkles" :size="17" :stroke="2" />
        <span>{{ busy ? 'AI 正在解题…' : '开始答疑' }}</span>
      </button>

      <div class="step-trail">
        <span><i>1</i>拍照</span>
        <em></em>
        <span><i>2</i>看讲解</span>
        <em></em>
        <span><i>3</i>说卡点</span>
      </div>
    </section>

    <!-- 拍照小提示：短、可扫读，不抢主流程 -->
    <div v-if="!result && !busy" class="tip-strip">
      <span><Icon name="sun" :size="14" :stroke="1.9" />光线均匀</span>
      <span><Icon name="scan" :size="14" :stroke="1.9" />四角拍全</span>
      <span><Icon name="sparkles" :size="14" :stroke="1.9" />公式也能认</span>
    </div>

    <!-- 加载 -->
    <section v-if="busy" class="card process">
      <div class="card-head">
        <span class="card-ico"><Icon name="scan" :size="20" /></span>
        <div class="card-head-text">
          <div class="card-title">正在读懂这道题</div>
          <div class="card-sub">
            已等待 {{ waited }} 秒 ·
            {{ waited >= 90 ? '模型仍在推理，网络慢时会久一些' : '推理型模型通常需要 1~3 分钟' }}
          </div>
        </div>
      </div>
      <ul class="steps">
        <li class="done">
          <span class="s-dot"><Icon name="check" :size="11" :stroke="3" /></span>
          图片已上传
        </li>
        <li class="active">
          <span class="s-dot"></span>
          识别公式与题干
        </li>
        <li>
          <span class="s-dot"></span>
          生成分步讲解
        </li>
      </ul>
      <div class="sk" style="height: 9px; width: 92%; margin-top: 16px"></div>
      <div class="sk" style="height: 9px; width: 78%; margin-top: 9px"></div>
      <div class="sk" style="height: 9px; width: 64%; margin-top: 9px"></div>
    </section>

    <!-- 错误 -->
    <section v-else-if="error" class="card">
      <div class="card-head">
        <span class="card-ico rose"><Icon name="alert" :size="20" /></span>
        <div class="card-head-text">
          <div class="card-title">这次没解出来</div>
          <div class="card-sub">可以重试，或换一张更清晰的图片</div>
        </div>
      </div>
      <div class="banner err">{{ error }}</div>
      <div class="btn-row">
        <button class="btn" @click="chooseFile">换一张</button>
        <button class="btn primary" @click="doAsk">重试</button>
      </div>
    </section>

    <!-- 答疑结果 -->
    <template v-if="result && !busy">
      <div class="shot-bar">
        <img v-if="preview" :src="preview" alt="题目缩略图" />
        <div class="shot-info">
          <b>题目已上传</b>
          <span>换一张可以继续问</span>
        </div>
        <button class="btn sm" @click="chooseFile">
          <Icon name="refresh" :size="14" :stroke="2" />
          换一题
        </button>
      </div>

      <section class="card result-card">
        <div class="card-head">
          <span class="card-ico teal"><Icon name="sparkles" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">AI 分步讲解</div>
            <div class="card-sub">
              {{ problems.length > 1 ? `识别到 ${problems.length} 道题，点题号切换` : '已按步骤拆解，跟着看即可' }}
            </div>
          </div>
        </div>

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

        <div class="answer">
          <MarkdownView :text="shownAnswer" />
        </div>
      </section>

      <!-- 互动反馈（画像数据来源） -->
      <section class="card">
        <div class="card-head">
          <span class="card-ico amber"><Icon name="bulb" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">卡在哪里了？</div>
            <div class="card-sub">可选 · 反馈会立即更新你的学习画像</div>
          </div>
          <span class="tag">可多选</span>
        </div>

        <div v-if="fbDone" class="banner ok done-banner">
          <Icon name="check" :size="16" :stroke="2.4" />
          <span>
            反馈已记录{{ fbResult ? `（影响 ${fbResult.kp_updated} 个知识点）` : '' }}
            <template v-if="fbResult?.score_delta < 0"> · 掌握度调整为 {{ fbResult.score_delta }}</template>
          </span>
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
              <span class="k"><Icon v-if="selected.includes(o.tag)" name="check" :size="13" :stroke="2.8" /></span>
              <span class="opt-title">{{ o.label }}</span>
            </label>
          </div>
          <p v-else class="muted drop-note">本题未生成候选选项，可以直接在下方描述。</p>

          <textarea
            v-model="custom"
            rows="2"
            placeholder="其他原因（可选），例如：公式忘了、没看懂第三步…"
            class="custom-input"
          ></textarea>

          <div class="btn-row" style="margin-top: 11px">
            <button class="btn ok" :disabled="fbBusy" @click="doFeedback(true)">
              <Icon name="check" :size="16" :stroke="2.4" />
              我懂了
            </button>
            <button class="btn primary" :disabled="fbBusy" @click="doFeedback(false)">
              {{ fbBusy ? '提交中…' : '提交反馈' }}
            </button>
          </div>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* ---------- 首屏 hero ---------- */
.hero {
  position: relative;
  overflow: hidden;
  margin-bottom: 14px;
  padding: 22px 20px 20px;
  border-radius: 24px;
  color: #fff;
  background: linear-gradient(135deg, #4c6fff 0%, #6357ff 52%, #8b5cf6 100%);
  box-shadow: 0 24px 44px -24px rgba(76, 111, 255, 0.8);
}

.hero::before {
  content: '';
  position: absolute;
  top: -120px;
  right: -70px;
  width: 240px;
  height: 240px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.3), rgba(255, 255, 255, 0) 68%);
}

.hero-eq {
  position: absolute;
  font-family: Georgia, 'Times New Roman', serif;
  font-style: italic;
  color: #fff;
  opacity: 0.14;
  pointer-events: none;
  line-height: 1;
}

.hero-eq.one {
  right: 22px;
  top: 26px;
  font-size: 56px;
}

.hero-eq.two {
  right: 58px;
  bottom: 30px;
  font-size: 34px;
  opacity: 0.11;
}

.hero-eq.three {
  right: 92px;
  top: 86px;
  font-size: 18px;
  opacity: 0.1;
}

.hero-eyebrow {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  background: rgba(255, 255, 255, 0.16);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.hero-title {
  position: relative;
  margin: 14px 0 8px;
  font-size: 25px;
  font-weight: 800;
  line-height: 1.34;
  letter-spacing: -0.03em;
}

.hero-sub {
  position: relative;
  max-width: 300px;
  font-size: 12.5px;
  line-height: 1.65;
  color: rgba(255, 255, 255, 0.82);
}

.hero-chips {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 16px;
}

.hero-chips span {
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.14);
  font-size: 11.5px;
  font-weight: 500;
}

/* ---------- 采集卡 ---------- */
.capture {
  padding: 14px;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 26px 16px 24px;
  border: 1.5px dashed var(--brand-ring);
  border-radius: 17px;
  background: var(--card-2);
  color: var(--ink);
  font: inherit;
  cursor: pointer;
  transition: border-color 0.2s var(--ease), background 0.2s var(--ease);
}

.dropzone:hover {
  border-color: var(--brand);
  background: var(--brand-weak);
}

.dz-ico {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-bottom: 6px;
  border-radius: 19px;
  color: #fff;
  background: var(--grad);
  box-shadow: 0 12px 24px -12px rgba(76, 111, 255, 0.75);
}

.dropzone b {
  font-size: 14.5px;
  font-weight: 650;
}

.dz-sub {
  font-size: 11.5px;
  color: var(--ink-3);
}

.ask-btn {
  margin-top: 12px;
}

.shot-preview {
  position: relative;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--img-bg);
}

.shot-preview .preview {
  max-height: 260px;
  object-fit: contain;
  border: 0;
  border-radius: 0;
}

.shot-tools {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 6px;
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  color: #fff;
  background: rgba(16, 24, 40, 0.55);
  backdrop-filter: blur(6px);
  cursor: pointer;
  transition: background 0.18s;
}

.icon-btn:hover {
  background: rgba(16, 24, 40, 0.75);
}

.step-trail {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 11px;
  color: var(--ink-3);
}

.step-trail span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.step-trail i {
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: var(--brand-weak);
  color: var(--brand-ink);
  font-size: 9.5px;
  font-style: normal;
  font-weight: 700;
}

.step-trail em {
  width: 14px;
  height: 1px;
  background: var(--line);
}

/* 拍照小提示 */
.tip-strip {
  display: flex;
  gap: 6px;
  margin: 12px 2px 0;
}

.tip-strip span {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 32px;
  border-radius: 10px;
  background: var(--card-2);
  border: 1px solid var(--line-2);
  color: var(--ink-3);
  font-size: 11.5px;
  white-space: nowrap;
}

.tip-strip :deep(svg) {
  color: var(--brand);
  opacity: 0.8;
}

/* ---------- 处理中 ---------- */
.process .steps {
  display: flex;
  flex-direction: column;
  gap: 11px;
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
}

.steps li {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  color: var(--ink-3);
}

.steps li.done {
  color: var(--ink-2);
}

.steps li.active {
  color: var(--ink);
  font-weight: 600;
}

.s-dot {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1.5px solid var(--line);
  background: var(--card);
  flex: 0 0 auto;
}

.steps li.done .s-dot {
  border-color: transparent;
  background: var(--ok);
  color: #fff;
}

.steps li.active .s-dot {
  border-color: var(--brand);
  background: var(--brand-weak);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.steps li.active .s-dot::after {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.35;
    transform: scale(0.75);
  }
}

/* ---------- 结果 ---------- */
.shot-bar {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 11px;
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 15px;
  background: var(--card);
  box-shadow: var(--shadow-sm);
}

.shot-bar img {
  width: 46px;
  height: 46px;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid var(--line);
}

.shot-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.shot-info b {
  font-size: 13px;
  font-weight: 650;
}

.shot-info span {
  font-size: 11.5px;
  color: var(--ink-3);
}

.result-card .answer {
  max-height: none;
}

.problem-tabs {
  display: flex;
  gap: 7px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  overflow-x: auto;
  scrollbar-width: none;
}

.problem-tabs::-webkit-scrollbar {
  display: none;
}

.ptab {
  flex: 0 0 auto;
  max-width: 78%;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  color: var(--ink-2);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all 0.18s var(--ease);
}

.ptab.on {
  border-color: var(--brand);
  background: var(--brand-weak);
  color: var(--brand-ink);
  font-weight: 650;
}

.ptab .pt {
  opacity: 0.68;
  font-weight: 400;
}

.capture + .process,
.capture + .card {
  margin-top: 0;
}

/* 反馈区 */
.done-banner {
  margin-bottom: 0;
  align-items: center;
}

.drop-note {
  margin-bottom: 2px;
}

.custom-input {
  margin-top: 10px;
}

.opt .opt-title {
  padding-top: 1px;
}
</style>
