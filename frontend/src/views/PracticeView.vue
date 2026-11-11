<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import {
  createTest, submitTest, detailedSolution, listTests,
  explainQuestion, judgeQuestionImage, getUnlockStatus,
} from '../api'
import { userId } from '../store/user'
import MarkdownView from '../components/MarkdownView.vue'
import Icon from '../components/Icon.vue'

// 看解析还不懂时的困惑类型（与后端 CONFUSION_LABELS 对应）
const CONFUSIONS = [
  { tag: 'step', label: '某一步跳太快' },
  { tag: 'why', label: '为什么能这样变形' },
  { tag: 'concept', label: '概念没学过' },
  { tag: 'formula', label: '公式不会套' },
  { tag: 'start', label: '不知道从哪下手' },
  { tag: 'answer', label: '不明白答案为什么是它' },
]

const TYPE_LABEL = {
  choice: '单选',
  multiple: '多选',
  judge: '判断',
  fill: '填空',
  solve: '解答',
}

const mode = ref('setup')       // setup | answering | result
const purpose = ref('weakness')
const count = ref(3)            // 题量选项：1 / 3 / 5

// 解锁状态：拍照上传过题目后，薄弱/复习才可用；随机练习始终可用
const unlocked = ref(false)
const qaCount = ref(0)

const session = ref(null)
const answers = ref({})         // { [questionId]: { answer, self_correct } }
const submitting = ref(false)
const judgeResult = ref(null)
const detailLoading = ref({})   // { [qid]: true }
const details = ref({})         // { [qid]: 文本 }
const history = ref([])
const error = ref('')

// 「还是不懂」交互状态（按题目 id 索引）
const tutorSel = ref({})        // { qid: [tag, ...] }
const tutorCustom = ref({})     // { qid: '自定义描述' }
const tutorLoading = ref({})    // { qid: true }
const tutorOut = ref({})        // { qid: '讲解 markdown' }
const tutorFollowup = ref({})   // { qid: [{tag,label}] }
const tutorOpen = ref({})       // { qid: true } 展开「换个讲法」面板

function toggleTutor(qid) {
  tutorOpen.value = { ...tutorOpen.value, [qid]: !tutorOpen.value[qid] }
}

// 主观题拍照判分状态
const judgeBusy = ref({})       // { qid: true }
const judgeRes = ref({})        // { qid: {correct, reason, student_answer, confidence} }

// 题干展示：默认文字版（排版统一、手机上无需横向拖动），需要核对原题时再展开原图
const stemImageOpen = ref({})   // { [qid]: true } 表示该题已展开原题图

function hasStemImage(q) {
  return !!(q.stem_image_path || q.image_path)
}

function isStemImageOpen(q) {
  return !!stemImageOpen.value[q.id]
}

function toggleStemImage(qid) {
  stemImageOpen.value = { ...stemImageOpen.value, [qid]: !stemImageOpen.value[qid] }
}

// 原题图放大：题干切图多为 684px 宽的窄条，缩到手机宽度后字偏小，点一下看大图
const zoomSrc = ref('')
function openZoom(q) {
  zoomSrc.value = '/' + (q.stem_image_path || q.image_path)
}

function pickJudgeFile(q) {
  document.getElementById('judge-file-' + q.id)?.click()
}

async function onJudgeFile(q, e) {
  const f = e.target.files?.[0]
  if (!f) return
  e.target.value = ''  // 允许重选同一文件
  judgeBusy.value = { ...judgeBusy.value, [q.id]: true }
  try {
    const r = await judgeQuestionImage(q.id, f, userId.value)
    judgeRes.value = { ...judgeRes.value, [q.id]: r }
    // 判分可用则回填为本题作答结果，提交时直接用
    if (typeof r.correct === 'boolean') {
      answers.value = { ...answers.value, [q.id]: { ...(answers.value[q.id] || {}), self_correct: r.correct } }
      window.__toast?.(r.correct ? 'AI 判定答对，已记录' : 'AI 判定答错，已记录')
    } else {
      window.__toast?.('AI 无法确定，请自己判对错')
    }
  } catch (err) {
    window.__toast?.('阅卷失败：' + (err.message || ''))
  } finally {
    judgeBusy.value = { ...judgeBusy.value, [q.id]: false }
  }
}

function toggleConfusion(qid, tag) {
  const cur = tutorSel.value[qid] || []
  const i = cur.indexOf(tag)
  const next = i >= 0 ? cur.filter((t) => t !== tag) : [...cur, tag]
  tutorSel.value = { ...tutorSel.value, [qid]: next }
}

async function askTutor(q, overrideTags = null) {
  const tags = overrideTags || tutorSel.value[q.id] || []
  const custom = overrideTags ? '' : (tutorCustom.value[q.id] || '')
  if (!tags.length && !custom.trim()) {
    window.__toast?.('先点一个你觉得卡住的地方，或写一句自己的话')
    return
  }
  tutorLoading.value = { ...tutorLoading.value, [q.id]: true }
  try {
    const r = await explainQuestion(q.id, {
      user_id: userId.value,
      feedback_tags: tags,
      custom: custom.trim() || null,
    })
    tutorOut.value = { ...tutorOut.value, [q.id]: r.explain_md }
    tutorFollowup.value = { ...tutorFollowup.value, [q.id]: r.feedback_options || [] }
    if (overrideTags) {
      tutorSel.value = { ...tutorSel.value, [q.id]: overrideTags }
    }
  } catch (e) {
    window.__toast?.('讲解生成失败：' + (e.message || ''))
  } finally {
    tutorLoading.value = { ...tutorLoading.value, [q.id]: false }
  }
}

function followupAsk(q, opt) {
  askTutor(q, [opt.tag])
}

function scrollTop() {
  document.querySelector('.app-body')?.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(async () => {
  await Promise.all([loadHistory(), loadUnlock()])
})

async function loadUnlock() {
  try {
    const r = await getUnlockStatus(userId.value)
    unlocked.value = !!r.unlocked
    qaCount.value = r.qa_count || 0
    // 未解锁时只有「随机练习」可用
    if (!unlocked.value) purpose.value = 'random'
    else if (purpose.value === 'random') purpose.value = 'weakness'
  } catch {
    unlocked.value = true  // 接口异常不阻塞使用
  }
}

async function loadHistory() {
  try {
    history.value = await listTests(userId.value)
  } catch { /* 忽略历史加载失败 */ }
}

async function start() {
  error.value = ''
  submitting.value = true
  try {
    session.value = await createTest(userId.value, { purpose: purpose.value, count: count.value })
    if (!session.value.total) {
      error.value = '题库中没有匹配到合适的题目：请先导入题库，或换个练习范围。'
      return
    }
    answers.value = {}
    judgeResult.value = null
    details.value = {}
    judgeRes.value = {}
    tutorOpen.value = {}
    tutorOut.value = {}
    tutorSel.value = {}
    tutorCustom.value = {}
    tutorFollowup.value = {}
    mode.value = 'answering'
    nextTick(scrollTop)
  } catch (e) {
    error.value = e.message || '组卷失败'
  } finally {
    submitting.value = false
  }
}

function pick(qid, key) {
  answers.value[qid] = { ...(answers.value[qid] || {}), answer: key }
}

function setSelf(qid, ok) {
  answers.value[qid] = { ...(answers.value[qid] || {}), self_correct: ok }
}

const answeredCount = computed(() => {
  const qs = session.value?.questions || []
  return qs.filter((q) => {
    const a = answers.value[q.id]
    if (!a) return false
    return q.is_objective ? !!a.answer : typeof a.self_correct === 'boolean'
  }).length
})

function isAnswered(q) {
  const a = answers.value[q.id]
  if (!a) return false
  return q.is_objective ? !!a.answer : typeof a.self_correct === 'boolean'
}

const answerPct = computed(() => {
  const total = session.value?.questions?.length || 0
  return total ? Math.round((answeredCount.value / total) * 100) : 0
})

const finishedCount = computed(() => history.value.filter((h) => h.status === 'submitted').length)

const scorePct = computed(() => (judgeResult.value ? Math.round(judgeResult.value.score * 100) : 0))

const scoreTitle = computed(() => {
  const s = judgeResult.value?.score ?? 0
  if (s >= 0.8) return '漂亮，稳住这个手感'
  if (s >= 0.5) return '有进步，再补两块短板'
  return '先把基础步骤补齐'
})

async function submit() {
  const qs = session.value?.questions || []
  if (answeredCount.value < qs.length) {
    window.__toast?.(`还有 ${qs.length - answeredCount.value} 题未作答`)
    return
  }
  submitting.value = true
  try {
    const payload = qs.map((q) => {
      const a = answers.value[q.id] || {}
      return q.is_objective
        ? { question_id: q.id, answer: a.answer }
        : { question_id: q.id, self_correct: !!a.self_correct }
    })
    judgeResult.value = await submitTest(session.value.id, payload)
    mode.value = 'result'
    window.__toast?.(`已提交：答对 ${judgeResult.value.right}/${judgeResult.value.total}`)
    loadHistory()
    nextTick(scrollTop)
  } catch (e) {
    window.__toast?.(e.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadDetail(qid) {
  detailLoading.value = { ...detailLoading.value, [qid]: true }
  try {
    const r = await detailedSolution(qid)
    details.value = { ...details.value, [qid]: r.detailed }
  } catch (e) {
    window.__toast?.('详细解析生成失败：' + (e.message || ''))
  } finally {
    detailLoading.value = { ...detailLoading.value, [qid]: false }
  }
}

function restart() {
  session.value = null
  judgeResult.value = null
  error.value = ''
  mode.value = 'setup'
  nextTick(scrollTop)
}

const judgeOf = (qid) => (judgeResult.value?.detail || []).find((d) => d.question_id === qid)
</script>

<template>
  <div class="screen">
    <!-- ① 组卷设置 -->
    <template v-if="mode === 'setup'">
      <section class="plan-hero">
        <span class="plan-deco"><Icon name="target" :size="120" :stroke="1" /></span>
        <p class="eyebrow">
          <Icon name="target" :size="13" :stroke="2" />
          自适应组卷
        </p>
        <h2>只练你薄弱的那几步</h2>
        <p class="plan-copy">按拍照反馈与错题记录出题，难度比例基础 3 : 中等 5 : 挑战 2。</p>
        <div class="plan-meta">
          <span>{{ unlocked ? '已解锁薄弱点练习' : '随机练习可用' }}</span>
          <span>客观题自动判分</span>
          <span>{{ finishedCount }} 组已完成</span>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <span class="card-ico"><Icon name="grid" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">练习范围</div>
            <div class="card-sub">选一个方向，系统自动组卷</div>
          </div>
        </div>

        <div v-if="!unlocked" class="banner warn locked-banner">
          <Icon name="lock" :size="16" />
          <span>
            还没上传过题目，先拍一道题才能解锁「薄弱点攻坚 / 巩固复习」。
            <router-link to="/camera" class="link">去拍照 <Icon name="arrow-right" :size="13" /></router-link>
          </span>
        </div>

        <div class="opt-list">
          <button class="opt range" :class="{ sel: purpose === 'random' }" @click="purpose = 'random'">
            <span class="range-ico"><Icon name="grid" :size="18" /></span>
            <span class="opt-body">
              <span class="opt-title">随机练习</span>
              <span class="opt-desc">始终可用 · 从题库随机抽题</span>
            </span>
            <span class="opt-check" :class="{ on: purpose === 'random' }">
              <Icon v-if="purpose === 'random'" name="check" :size="12" :stroke="3" />
            </span>
          </button>

          <button
            class="opt range"
            :class="{ sel: purpose === 'weakness', locked: !unlocked }"
            :disabled="!unlocked"
            @click="purpose = 'weakness'"
          >
            <span class="range-ico"><Icon name="target" :size="18" /></span>
            <span class="opt-body">
              <span class="opt-title">薄弱点攻坚</span>
              <span class="opt-desc">优先练拍照问过、错得多的知识点</span>
            </span>
            <span v-if="!unlocked" class="tag"><Icon name="lock" :size="11" />待解锁</span>
            <span v-else class="opt-check" :class="{ on: purpose === 'weakness' }">
              <Icon v-if="purpose === 'weakness'" name="check" :size="12" :stroke="3" />
            </span>
          </button>

          <button
            class="opt range"
            :class="{ sel: purpose === 'review', locked: !unlocked }"
            :disabled="!unlocked"
            @click="purpose = 'review'"
          >
            <span class="range-ico"><Icon name="refresh" :size="18" /></span>
            <span class="opt-body">
              <span class="opt-title">巩固复习</span>
              <span class="opt-desc">练掌握度较高的知识点，防止遗忘</span>
            </span>
            <span v-if="!unlocked" class="tag"><Icon name="lock" :size="11" />待解锁</span>
            <span v-else class="opt-check" :class="{ on: purpose === 'review' }">
              <Icon v-if="purpose === 'review'" name="check" :size="12" :stroke="3" />
            </span>
          </button>
        </div>

        <div class="divider"></div>

        <div class="count-row">
          <div>
            <div class="card-title" style="font-size: 14px">本组题量</div>
            <div class="card-sub">建议一次 3 题，专注完成</div>
          </div>
          <div class="seg count-seg">
            <button v-for="c in [1, 3, 5]" :key="c" :class="{ on: count === c }" @click="count = c">
              {{ c }} 题
            </button>
          </div>
        </div>

        <button class="btn primary block start-btn" :disabled="submitting" @click="start">
          <Icon v-if="!submitting" name="play" :size="16" :stroke="2.2" />
          {{ submitting ? '组卷中…' : '生成练习卷' }}
        </button>

        <div v-if="error" class="banner warn" style="margin-top: 12px">
          <Icon name="alert" :size="16" />
          <span>{{ error }}</span>
        </div>
      </section>

      <section v-if="history.length" class="card">
        <div class="card-head">
          <span class="card-ico neutral"><Icon name="history" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">历史练习</div>
            <div class="card-sub">最近 {{ Math.min(history.length, 5) }} 组</div>
          </div>
        </div>
        <div class="hist-list">
          <div v-for="h in history.slice(0, 5)" :key="h.id" class="hist-row">
            <span class="hist-dot" :class="h.status === 'submitted' ? 'ok' : 'warn'"></span>
            <div class="hist-main">
              <b>{{ h.title }}</b>
              <span v-if="h.status === 'submitted' && h.score != null" class="num">
                答对 {{ h.right }}/{{ h.right + h.wrong }} · 得分 {{ Math.round(h.score * 100) }}%
              </span>
              <span v-else>尚未提交</span>
            </div>
            <span class="tag" :class="h.status === 'submitted' ? 'ok' : 'warn'">
              {{ h.status === 'submitted' ? '已完成' : '未提交' }}
            </span>
          </div>
        </div>
      </section>
    </template>

    <!-- ② 答题 -->
    <template v-else-if="mode === 'answering'">
      <section class="card quiz-head">
        <div class="quiz-top">
          <div class="quiz-title-wrap">
            <div class="quiz-title">{{ session.title }}</div>
            <div class="quiz-sub">
              已作答 <b class="num">{{ answeredCount }}</b> / {{ session.questions.length }}
            </div>
          </div>
          <button class="btn sm ghost" @click="restart">
            <Icon name="x" :size="14" :stroke="2" />
            退出
          </button>
        </div>
        <div class="progress quiz-progress">
          <i :style="{ width: answerPct + '%' }"></i>
        </div>
      </section>

      <section
        v-for="q in session.questions"
        :key="q.id"
        class="card q-card"
        :class="{ 'q-done': isAnswered(q) }"
      >
        <div class="q-head">
          <span class="q-index">第 {{ q.order_no }} 题</span>
          <span class="tag">{{ TYPE_LABEL[q.question_type] || q.question_type }}</span>
          <span v-if="q.difficulty" class="tag ghost">难度 {{ q.difficulty }}</span>
          <span v-for="k in (q.kp_names || [])" :key="k" class="tag brand">{{ k }}</span>
          <span v-if="isAnswered(q)" class="tag ok"><Icon name="check" :size="11" :stroke="2.6" />已作答</span>
        </div>

        <!-- 题干区：默认文字版；原题图按需展开，避免同一题出现两份内容 -->
        <div class="stem-box"><MarkdownView :text="q.stem" /></div>
        <div v-if="hasStemImage(q)" class="stem-img-bar">
          <button type="button" class="stem-img-btn" :class="{ on: isStemImageOpen(q) }" @click="toggleStemImage(q.id)">
            <Icon :name="isStemImageOpen(q) ? 'x' : 'image'" :size="14" :stroke="2" />
            {{ isStemImageOpen(q) ? '收起原题图' : '查看原题图' }}
          </button>
        </div>
        <div v-if="hasStemImage(q) && isStemImageOpen(q)" class="img-card q-img expanded" @click="openZoom(q)">
          <img :src="'/' + (q.stem_image_path || q.image_path)" alt="题目原图" loading="lazy" />
        </div>

        <!-- 客观题 -->
        <template v-if="q.is_objective && q.options?.length">
          <div class="opt-list q-options">
            <button
              v-for="o in q.options"
              :key="o.key"
              class="opt"
              :class="{ sel: answers[q.id]?.answer === o.key }"
              @click="pick(q.id, o.key)"
            >
              <span class="k">{{ o.key }}</span>
              <span class="opt-body"><MarkdownView :text="o.text" /></span>
            </button>
          </div>
        </template>
        <!-- 客观题：填空等无选项 -->
        <template v-else-if="q.is_objective">
          <label class="field-label" :for="'fill-' + q.id">你的答案</label>
          <input
            :id="'fill-' + q.id"
            :value="answers[q.id]?.answer || ''"
            @input="(e) => pick(q.id, e.target.value)"
            placeholder="填写你的答案"
          />
        </template>
        <!-- 主观题：拍照上传让 AI 阅卷，或自评 -->
        <template v-else>
          <div class="solve-panel">
            <div class="solve-head">
              <span class="solve-ico"><Icon name="pencil" :size="17" /></span>
              <div>
                <b>解答题</b>
                <span>拍下解题过程让 AI 判分，或直接自评</span>
              </div>
            </div>
            <input
              :id="'judge-file-' + q.id"
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              @change="(e) => onJudgeFile(q, e)"
            />
            <button
              class="btn primary block"
              :disabled="judgeBusy[q.id]"
              @click="pickJudgeFile(q)"
            >
              <Icon name="camera" :size="17" :stroke="1.9" />
              {{ judgeBusy[q.id] ? 'AI 阅卷中（约 20~60 秒）…' : '拍下我的解答，AI 判分' }}
            </button>

            <div
              v-if="judgeRes[q.id]"
              class="judge-box"
              :class="judgeRes[q.id].correct === true ? 'ok' : judgeRes[q.id].correct === false ? 'err' : ''"
            >
              <div class="judge-head">
                <b v-if="judgeRes[q.id].correct === true">AI 判定：答对了</b>
                <b v-else-if="judgeRes[q.id].correct === false">AI 判定：答错了</b>
                <b v-else>AI 拿不准，请自己判断</b>
                <span v-if="judgeRes[q.id].confidence" class="tag">
                  把握 {{ Math.round(judgeRes[q.id].confidence * 100) }}%
                </span>
              </div>
              <div v-if="judgeRes[q.id].student_answer" class="judge-answer">
                识别到你的答案：<b>{{ judgeRes[q.id].student_answer }}</b>
              </div>
              <div v-if="judgeRes[q.id].reason" class="judge-reason">{{ judgeRes[q.id].reason }}</div>
            </div>

            <div class="self-row">
              <span class="self-label">或者自评</span>
              <button
                class="btn self-btn"
                :class="{ 'is-ok': answers[q.id]?.self_correct === true }"
                @click="setSelf(q.id, true)"
              >
                <Icon name="check" :size="15" :stroke="2.4" />
                我做对了
              </button>
              <button
                class="btn self-btn"
                :class="{ 'is-err': answers[q.id]?.self_correct === false }"
                @click="setSelf(q.id, false)"
              >
                <Icon name="x" :size="15" :stroke="2.4" />
                我做错了
              </button>
            </div>
          </div>
        </template>
      </section>

      <div class="submit-dock">
        <button class="btn primary block" :disabled="submitting" @click="submit">
          <Icon v-if="!submitting" name="check" :size="17" :stroke="2.4" />
          {{ submitting ? '判分中…' : '提交并判分' }}
        </button>
      </div>
    </template>

    <!-- ③ 结果 -->
    <template v-else>
      <section class="card score-card">
        <div class="score-ring-wrap">
          <svg viewBox="0 0 120 120" class="score-ring" aria-hidden="true">
            <defs>
              <linearGradient id="scoreGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#4c6fff" />
                <stop offset="100%" stop-color="#7b61ff" />
              </linearGradient>
            </defs>
            <circle cx="60" cy="60" r="52" class="ring-track" />
            <circle
              cx="60"
              cy="60"
              r="52"
              class="ring-val"
              :stroke-dashoffset="327 * (1 - judgeResult.score)"
            />
          </svg>
          <div class="score-center">
            <b class="num">{{ scorePct }}<small>%</small></b>
            <span>得分</span>
          </div>
        </div>
        <h2 class="score-title">{{ scoreTitle }}</h2>
        <p class="score-sub">答对 {{ judgeResult.right }} / {{ judgeResult.total }} 题 · 错题已自动加入错题本</p>
        <div class="btn-row score-actions">
          <button class="btn primary" :disabled="submitting" @click="start">
            <Icon name="refresh" :size="16" :stroke="2.2" />
            {{ submitting ? '组卷中…' : '再来一组' }}
          </button>
          <button class="btn" @click="restart">调整设置</button>
        </div>
        <div v-if="error" class="banner warn" style="margin-top: 12px; margin-bottom: 0">
          <Icon name="alert" :size="16" />
          <span>{{ error }}</span>
        </div>
      </section>

      <section v-for="q in session.questions" :key="q.id" class="card review-card">
        <template v-if="judgeOf(q.id)">
          <div class="rev-head">
            <span class="rev-status" :class="judgeOf(q.id).correct ? 'ok' : 'err'">
              <Icon :name="judgeOf(q.id).correct ? 'check' : 'x'" :size="16" :stroke="2.6" />
            </span>
            <div class="rev-title">
              <b>第 {{ q.order_no }} 题</b>
              <span>{{ TYPE_LABEL[q.question_type] || q.question_type }} · {{ judgeOf(q.id).judged_by === 'auto' ? '系统判分' : '自评' }}</span>
            </div>
            <span class="tag" :class="judgeOf(q.id).correct ? 'ok' : 'err'">
              {{ judgeOf(q.id).correct ? '答对' : '答错' }}
            </span>
          </div>

          <div class="stem-box"><MarkdownView :text="q.stem" /></div>

          <div class="compare">
            <div v-if="judgeOf(q.id).your_answer != null" class="cmp-row">
              <span class="cmp-k">你的答案</span>
              <div class="cmp-v" :class="judgeOf(q.id).correct ? 'ok' : 'err'">{{ judgeOf(q.id).your_answer }}</div>
            </div>
            <div class="cmp-row">
              <span class="cmp-k">正确答案</span>
              <div class="cmp-v ok"><MarkdownView :text="judgeOf(q.id).correct_answer" /></div>
            </div>
          </div>

          <details class="sol">
            <summary>
              <span class="sol-ico"><Icon name="book" :size="16" /></span>
              <b>书上的解析</b>
              <Icon class="chev" name="chevron-down" :size="16" />
            </summary>
            <div class="sol-body">
              <div v-if="q.solution_image_path" class="img-card" style="margin-bottom: 8px">
                <img :src="'/' + q.solution_image_path" alt="解析图" />
              </div>
              <div class="answer">
                <MarkdownView :text="q.solution || '（无）'" />
              </div>
            </div>
          </details>

          <!-- 看解析还不懂 → 带着困惑让模型换讲法（默认收起，避免每题都很长） -->
          <div class="tutor">
            <button
              type="button"
              class="tutor-toggle"
              :class="{ open: tutorOpen[q.id] }"
              :aria-expanded="!!tutorOpen[q.id]"
              @click="toggleTutor(q.id)"
            >
              <span class="tutor-toggle-ico"><Icon name="bulb" :size="16" /></span>
              <span class="tutor-toggle-text">
                <b>还是不懂？</b>
                <em>告诉我卡在哪，AI 换个讲法</em>
              </span>
              <Icon :name="tutorOpen[q.id] ? 'chevron-up' : 'chevron-down'" :size="16" />
            </button>

            <div v-if="tutorOpen[q.id] || tutorOut[q.id]" class="tutor-box">
              <div class="chip-row">
                <button
                  v-for="c in CONFUSIONS"
                  :key="c.tag"
                  class="chip"
                  :class="{ on: tutorSel[q.id]?.includes(c.tag) }"
                  @click="toggleConfusion(q.id, c.tag)"
                >{{ c.label }}</button>
              </div>
              <input
                v-model="tutorCustom[q.id]"
                placeholder="也可以用自己的话说（可选）"
                class="tutor-input"
              />
              <button
                class="btn primary block"
                style="margin-top: 9px"
                :disabled="tutorLoading[q.id]"
                @click="askTutor(q)"
              >
                <Icon name="sparkles" :size="16" :stroke="2" />
                {{ tutorLoading[q.id] ? 'AI 正在重新讲解（约 30~90 秒）…' : '换个讲法' }}
              </button>

              <div v-if="tutorOut[q.id]" class="tutor-reply">
                <div class="answer tutor-answer">
                  <MarkdownView :text="tutorOut[q.id]" />
                </div>
                <div v-if="tutorFollowup[q.id]?.length" class="followup">
                  <div class="muted">还不清楚？点一下继续追问：</div>
                  <div class="chip-row">
                    <button
                      v-for="o in tutorFollowup[q.id]"
                      :key="o.tag"
                      class="chip"
                      @click="followupAsk(q, o)"
                    >{{ o.label }}</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="details[q.id]" class="detail-block">
            <h3>AI 详细讲解</h3>
            <div class="answer tutor-answer">
              <MarkdownView :text="details[q.id]" />
            </div>
          </div>
          <button
            v-else
            class="btn block detail-btn"
            :disabled="detailLoading[q.id]"
            @click="loadDetail(q.id)"
          >
            <Icon name="sparkles" :size="16" :stroke="2" />
            {{ detailLoading[q.id] ? '生成中（约 30~90 秒）…' : '看 AI 详细讲解（按需生成）' }}
          </button>
        </template>
      </section>
    </template>

    <!-- 原题图放大（点击关闭） -->
    <teleport to="body">
      <div v-if="zoomSrc" class="zoom-mask" @click="zoomSrc = ''">
        <img :src="zoomSrc" alt="题目原图" />
        <span class="zoom-hint">点击任意处关闭</span>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
/* ---------- 组卷设置 ---------- */
.plan-hero {
  position: relative;
  overflow: hidden;
  padding: 20px;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 24px;
  background:
    radial-gradient(120% 130% at 0% 0%, #e9eeff 0%, #f5f2ff 46%, var(--card) 100%);
  box-shadow: var(--shadow);
}

[data-theme='dark'] .plan-hero {
  background:
    radial-gradient(120% 130% at 0% 0%, #1b2547 0%, #191a35 46%, var(--card) 100%);
}

.plan-deco {
  position: absolute;
  right: -18px;
  bottom: -22px;
  color: var(--brand);
  opacity: 0.09;
  pointer-events: none;
}

.plan-hero h2 {
  position: relative;
  margin: 10px 0 6px;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.35;
}

.plan-copy {
  position: relative;
  max-width: 290px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--ink-2);
}

.plan-meta {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
}

.plan-meta span {
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.6);
  color: var(--ink-2);
  font-size: 11px;
  font-weight: 500;
}

[data-theme='dark'] .plan-meta span {
  background: rgba(255, 255, 255, 0.05);
}

.locked-banner {
  align-items: center;
  margin-bottom: 12px;
}

.locked-banner .link {
  margin-left: 2px;
}

/* 练习范围选项 */
.range {
  align-items: center;
  padding: 13px 14px;
}

.range-ico {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 12px;
  background: var(--brand-weak);
  color: var(--brand);
  transition: all 0.18s var(--ease);
}

.opt.sel .range-ico {
  background: var(--brand);
  color: #fff;
  box-shadow: 0 8px 16px -8px rgba(76, 111, 255, 0.7);
}

.range .opt-body {
  display: flex;
  flex-direction: column;
  padding-top: 0;
}

.opt-check {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin-left: auto;
  border: 1.5px solid var(--line);
  border-radius: 50%;
  color: #fff;
  background: transparent;
}

.opt-check.on {
  border-color: transparent;
  background: var(--brand);
}

.opt.locked {
  opacity: 0.78;
  background: var(--card-2);
  cursor: not-allowed;
}

.opt.locked .range-ico {
  background: var(--line-2);
  color: var(--ink-3);
}

.count-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}

.count-seg {
  flex: 0 0 156px;
}

.start-btn {
  margin-top: 16px;
}

/* 历史练习 */
.hist-list {
  display: flex;
  flex-direction: column;
}

.hist-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}

.hist-row:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.hist-dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-3);
}

.hist-dot.ok {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-weak);
}

.hist-dot.warn {
  background: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-weak);
}

.hist-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.hist-main b {
  font-size: 13.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hist-main span {
  font-size: 11.5px;
  color: var(--ink-3);
}

/* ---------- 答题 ---------- */
.quiz-head {
  position: sticky;
  top: 0;
  z-index: 15;
  padding: 14px 16px;
  background: var(--card);
}

.quiz-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.quiz-title-wrap {
  flex: 1;
  min-width: 0;
}

.quiz-title {
  font-size: 14.5px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quiz-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-3);
}

.quiz-sub b {
  color: var(--brand);
  font-weight: 700;
}

.quiz-progress {
  margin-top: 10px;
}

.q-card {
  padding: 16px;
}

.q-done {
  border-color: rgba(16, 185, 129, 0.35);
}

.q-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 11px;
}

.q-index {
  margin-right: 2px;
  font-size: 13.5px;
  font-weight: 720;
  letter-spacing: -0.01em;
}

/* 原题图开关：默认收起，题干只显示文字版 */
.stem-img-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.stem-img-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  color: var(--ink-2);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.16s var(--ease), border-color 0.16s var(--ease), background 0.16s var(--ease);
}

.stem-img-btn:hover,
.stem-img-btn.on {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-weak);
}

.q-img {
  max-height: 340px;
  overflow: hidden;
}

/* 展开态：用户主动点开核对原题，必须完整可读，不能再截断 */
.q-img.expanded {
  max-height: none;
  overflow: visible;
}

.q-img.expanded img {
  max-height: none;
  height: auto;
  object-fit: contain;
  cursor: zoom-in;
}

/* 放大层：题干切图多为 684px 宽，按接近原尺寸显示（超出可横向滚动），别再用 100% 压回去 */
.zoom-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  padding: 16px;
  background: rgba(12, 16, 28, 0.9);
  overflow: auto;
  cursor: zoom-out;
}

.zoom-mask img {
  display: block;
  width: 640px;
  max-width: none;
  height: auto;
  margin: 6vh auto 0;
  border-radius: 10px;
  background: #fff;
}

.zoom-hint {
  display: block;
  margin-top: 12px;
  text-align: center;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.q-img img {
  max-height: 340px;
  object-fit: contain;
}

.q-options {
  margin-top: 11px;
}

.field-label {
  display: block;
  margin: 12px 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-2);
}

/* 主观题面板 */
.solve-panel {
  margin-top: 12px;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--card-2);
}

.solve-head {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 10px;
}

.solve-ico {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: var(--brand-weak);
  color: var(--brand);
}

.solve-head div,
.tutor-head div {
  display: flex;
  flex-direction: column;
}

.solve-head b,
.tutor-head b {
  font-size: 13px;
  font-weight: 650;
}

.solve-head span,
.tutor-head span {
  font-size: 11px;
  color: var(--ink-3);
}

.judge-box {
  margin-top: 10px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--card);
}

.judge-box.ok {
  border-color: rgba(16, 185, 129, 0.4);
  background: var(--ok-weak);
}

.judge-box.err {
  border-color: rgba(244, 63, 94, 0.4);
  background: var(--err-weak);
}

.judge-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.judge-head b {
  font-size: 13px;
}

.judge-box.ok .judge-head b {
  color: var(--ok-ink);
}

.judge-box.err .judge-head b {
  color: var(--err-ink);
}

.judge-answer {
  margin-top: 5px;
  font-size: 13px;
}

.judge-reason {
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.6;
}

.self-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.self-label {
  font-size: 11.5px;
  color: var(--ink-3);
  white-space: nowrap;
}

.self-btn {
  flex: 1;
  height: 38px;
  font-size: 12.5px;
  padding: 0 8px;
}

.self-btn.is-ok {
  border-color: var(--ok);
  background: var(--ok-weak);
  color: var(--ok-ink);
}

.self-btn.is-err {
  border-color: var(--err);
  background: var(--err-weak);
  color: var(--err-ink);
}

.submit-dock {
  position: sticky;
  bottom: 0;
  z-index: 15;
  padding: 12px 0 4px;
  background: linear-gradient(180deg, transparent, var(--bg) 45%);
}

/* ---------- 结果 ---------- */
.score-card {
  text-align: center;
  padding-top: 22px;
}

.score-ring-wrap {
  position: relative;
  width: 132px;
  height: 132px;
  margin: 0 auto;
}

.score-ring {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.ring-track,
.ring-val {
  fill: none;
  stroke-width: 10;
}

.ring-track {
  stroke: var(--line-2);
}

.ring-val {
  stroke: url(#scoreGrad);
  stroke-linecap: round;
  stroke-dasharray: 327;
  transition: stroke-dashoffset 0.8s var(--ease);
}

.score-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
}

.score-center b {
  font-size: 34px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.04em;
  background: var(--grad);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.score-center small {
  font-size: 15px;
  font-weight: 700;
}

.score-center span {
  font-size: 11px;
  color: var(--ink-3);
}

.score-title {
  margin: 14px 0 4px;
  font-size: 18px;
  font-weight: 760;
  letter-spacing: -0.02em;
}

.score-sub {
  font-size: 12.5px;
  color: var(--ink-3);
}

.score-actions {
  margin-top: 16px;
}

.review-card {
  padding: 16px;
}

.rev-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 11px;
}

.rev-status {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
}

.rev-status.ok {
  background: var(--ok-weak);
  color: var(--ok-ink);
}

.rev-status.err {
  background: var(--err-weak);
  color: var(--err-ink);
}

.rev-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.rev-title b {
  font-size: 14px;
  font-weight: 700;
}

.rev-title span {
  font-size: 11.5px;
  color: var(--ink-3);
}

.compare {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 11px;
}

.cmp-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13.5px;
}

.cmp-k {
  flex: 0 0 64px;
  padding-top: 1px;
  font-size: 12px;
  color: var(--ink-3);
}

.cmp-v {
  flex: 1;
  min-width: 0;
  font-weight: 650;
  line-height: 1.6;
}

.cmp-v.ok {
  color: var(--ok-ink);
}

.cmp-v.err {
  color: var(--err-ink);
}

.cmp-v .md {
  font-size: 13.5px;
}

.sol {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--card-2);
  overflow: hidden;
}

.sol summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 12px;
  cursor: pointer;
  list-style: none;
  font-size: 13px;
  user-select: none;
}

.sol summary::-webkit-details-marker {
  display: none;
}

.sol summary b {
  flex: 1;
  font-weight: 650;
}

.sol-ico {
  display: grid;
  place-items: center;
  color: var(--brand);
}

.sol .chev {
  color: var(--ink-3);
  transition: transform 0.2s var(--ease);
}

.sol[open] .chev {
  transform: rotate(180deg);
}

.sol-body {
  padding: 0 12px 12px;
}

.sol-body .answer {
  background: var(--card);
  max-height: none;
}

.tutor {
  margin-top: 13px;
}

.tutor-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s var(--ease), background 0.18s var(--ease);
}

.tutor-toggle:hover,
.tutor-toggle.open {
  border-color: var(--brand-ring);
  background: var(--card-2);
}

.tutor-toggle-ico {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 9px;
  background: var(--brand-weak);
  color: var(--brand-ink);
}

.tutor-toggle-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.tutor-toggle-text b {
  font-size: 13px;
  font-weight: 650;
}

.tutor-toggle-text em {
  font-style: normal;
  font-size: 11.5px;
  color: var(--ink-3);
}

.tutor-toggle > svg:last-child {
  color: var(--ink-3);
}

.tutor-box {
  margin-top: 8px;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--card-2);
}

.tutor-input {
  margin-top: 9px;
  background: var(--card);
}

.tutor-reply {
  margin-top: 11px;
}

.tutor-answer {
  max-height: none;
  border-color: var(--brand-ring);
  background: var(--card);
}

.followup {
  margin-top: 9px;
}

.followup .muted {
  margin-bottom: 6px;
  font-size: 12px;
}

.detail-block {
  margin-top: 13px;
}

.detail-block h3 {
  margin-bottom: 7px;
}

.detail-btn {
  margin-top: 12px;
}
</style>
