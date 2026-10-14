<script setup>
import { ref, computed, onMounted } from 'vue'
import { createTest, submitTest, detailedSolution, listTests } from '../api'
import { userId } from '../store/user'
import MarkdownView from '../components/MarkdownView.vue'

const mode = ref('setup')       // setup | answering | result
const purpose = ref('weakness')
const count = ref(6)

const session = ref(null)
const answers = ref({})         // { [questionId]: { answer, self_correct } }
const submitting = ref(false)
const judgeResult = ref(null)
const detailLoading = ref({})   // { [qid]: true }
const details = ref({})         // { [qid]: 文本 }
const history = ref([])
const error = ref('')

onMounted(loadHistory)

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
    mode.value = 'answering'
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
  mode.value = 'setup'
}

const judgeOf = (qid) => (judgeResult.value?.detail || []).find((d) => d.question_id === qid)
</script>

<template>
  <div class="screen">
    <!-- ① 组卷设置 -->
    <template v-if="mode === 'setup'">
      <div class="card">
        <h2>✏️ 针对性练习</h2>
        <p class="hint" style="margin-top: 0">
          按你的薄弱点自动组卷（难度阶梯：基础 3 : 中等 5 : 挑战 2）。客观题自动判分，主观题做完自己判对错。
        </p>

        <h3>练习范围</h3>
        <div class="opt-list">
          <button class="opt" :class="{ sel: purpose === 'weakness' }" @click="purpose = 'weakness'">
            <span class="k">●</span><span>薄弱点攻坚（优先练错得多的知识点）</span>
          </button>
          <button class="opt" :class="{ sel: purpose === 'review' }" @click="purpose = 'review'">
            <span class="k">●</span><span>巩固复习（练掌握度较高的知识点）</span>
          </button>
        </div>

        <h3>题量</h3>
        <div class="btn-row">
          <button
            v-for="c in [4, 6, 10]"
            :key="c"
            class="btn"
            :class="{ primary: count === c }"
            @click="count = c"
          >{{ c }} 题</button>
        </div>

        <button class="btn primary block" style="margin-top: 16px" :disabled="submitting" @click="start">
          {{ submitting ? '组卷中…' : '开始练习' }}
        </button>
        <div v-if="error" class="banner warn" style="margin-top: 12px">{{ error }}</div>
      </div>

      <div class="card" v-if="history.length">
        <h2>历史练习</h2>
        <div
          v-for="h in history.slice(0, 5)"
          :key="h.id"
          style="display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 1px solid var(--line)"
        >
          <span class="tag" :class="h.status === 'submitted' ? 'ok' : 'warn'">
            {{ h.status === 'submitted' ? '已完成' : '未提交' }}
          </span>
          <span style="flex: 1; font-size: 13px">{{ h.title }}</span>
          <span class="muted" v-if="h.status === 'submitted'">
            {{ h.right }}/{{ h.right + h.wrong }} · {{ Math.round(h.score * 100) }}%
          </span>
        </div>
      </div>
    </template>

    <!-- ② 答题 -->
    <template v-else-if="mode === 'answering'">
      <div class="card" style="display: flex; align-items: center">
        <div style="flex: 1">
          <b>{{ session.title }}</b>
          <div class="muted">已作答 {{ answeredCount }}/{{ session.questions.length }}</div>
        </div>
        <button class="btn ghost" @click="restart">退出</button>
      </div>

      <div v-for="q in session.questions" :key="q.id" class="card">
        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap">
          <span class="tag brand">第 {{ q.order_no }} 题</span>
          <span class="tag">{{ { choice: '单选', multiple: '多选', judge: '判断', fill: '填空', solve: '解答' }[q.question_type] || q.question_type }}</span>
          <span class="tag" v-if="q.difficulty">难度 {{ q.difficulty }}</span>
          <span class="tag" v-for="k in (q.kp_names || [])" :key="k">{{ k }}</span>
        </div>

        <img v-if="q.image_path" :src="'/' + q.image_path" class="preview" style="margin-bottom: 10px" alt="题目图" />
        <div class="stem-box"><MarkdownView :text="q.stem" /></div>

        <!-- 客观题 -->
        <template v-if="q.is_objective && q.options?.length">
          <div class="opt-list" style="margin-top: 10px">
            <button
              v-for="o in q.options"
              :key="o.key"
              class="opt"
              :class="{ sel: answers[q.id]?.answer === o.key }"
              @click="pick(q.id, o.key)"
            >
              <span class="k">{{ o.key }}</span>
              <span style="flex: 1"><MarkdownView :text="o.text" /></span>
            </button>
          </div>
        </template>
        <!-- 客观题：填空等无选项 -->
        <input
          v-else-if="q.is_objective"
          :value="answers[q.id]?.answer || ''"
          @input="(e) => pick(q.id, e.target.value)"
          placeholder="填写你的答案"
          style="margin-top: 10px"
        />
        <!-- 主观题：自评对错 -->
        <template v-else>
          <p class="hint" style="margin-bottom: 6px">这题是解答题：请对照自己的草稿判断——</p>
          <div class="btn-row">
            <button class="btn" :class="{ ok: answers[q.id]?.self_correct === true }" @click="setSelf(q.id, true)">✔ 我做对了</button>
            <button class="btn" :class="{ warn: answers[q.id]?.self_correct === false }" @click="setSelf(q.id, false)">✘ 我做错了</button>
          </div>
        </template>
      </div>

      <button class="btn primary block" :disabled="submitting" @click="submit">
        {{ submitting ? '判分中…' : '提交并判分' }}
      </button>
    </template>

    <!-- ③ 结果 -->
    <template v-else>
      <div class="card" style="text-align: center">
        <div style="font-size: 34px">{{ judgeResult.score >= 0.8 ? '🎉' : judgeResult.score >= 0.5 ? '💪' : '📖' }}</div>
        <h2 style="margin: 6px 0">得分 {{ Math.round(judgeResult.score * 100) }}%</h2>
        <div class="muted">答对 {{ judgeResult.right }} / {{ judgeResult.total }} 题（错题已自动加入错题本）</div>
        <div class="btn-row" style="margin-top: 14px">
          <button class="btn" @click="restart">再来一组</button>
          <button class="btn ghost" @click="mode = 'setup'">返回</button>
        </div>
      </div>

      <div v-for="q in session.questions" :key="q.id" class="card">
        <template v-if="judgeOf(q.id)">
          <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap">
            <span class="tag brand">第 {{ q.order_no }} 题</span>
            <span class="tag" :class="judgeOf(q.id).correct ? 'ok' : 'err'">
              {{ judgeOf(q.id).correct ? '答对' : '答错' }}
            </span>
            <span class="tag">{{ judgeOf(q.id).judged_by === 'auto' ? '系统判分' : '自评' }}</span>
          </div>

          <div class="stem-box"><MarkdownView :text="q.stem" /></div>

          <div style="margin-top: 10px; font-size: 14px">
            <div v-if="judgeOf(q.id).your_answer != null">
              你的答案：<b :style="{ color: judgeOf(q.id).correct ? 'var(--ok)' : 'var(--err)' }">{{ judgeOf(q.id).your_answer }}</b>
            </div>
            <div>正确答案：<b style="color: var(--ok)"><MarkdownView :text="judgeOf(q.id).correct_answer" /></b></div>
          </div>

          <h3>库内解析</h3>
          <div class="answer" style="max-height: none">
            <MarkdownView :text="q.solution || '（无）'" />
          </div>

          <template v-if="details[q.id]">
            <h3>AI 详细讲解</h3>
            <div class="answer" style="max-height: none; border-color: var(--brand)">
              <MarkdownView :text="details[q.id]" />
            </div>
          </template>
          <button v-else class="btn block" style="margin-top: 10px" :disabled="detailLoading[q.id]" @click="loadDetail(q.id)">
            {{ detailLoading[q.id] ? '生成中（约 30~90 秒）…' : '🤖 看 AI 详细讲解（按需生成，节省成本）' }}
          </button>
        </template>
      </div>
    </template>
  </div>
</template>
