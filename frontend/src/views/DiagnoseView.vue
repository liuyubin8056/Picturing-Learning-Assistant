<script setup>
import { ref, onMounted, computed } from 'vue'
import { getProfile, generateDiagnose, getLatestDiagnose, listDiagnose, getRadar, getUnlockStatus } from '../api'
import { userId } from '../store/user'
import RadarChart from '../components/RadarChart.vue'
import MarkdownView from '../components/MarkdownView.vue'
import Icon from '../components/Icon.vue'

const loading = ref(true)
const radar = ref({ axes: [], weak_points: [], signal_count: 0 })
const profileMd = ref('')
const stats = ref([])            // 每个知识点：kp_name / chapter / score / weak
const report = ref(null)
const reportList = ref([])
const genBusy = ref(false)
const error = ref('')

// 雷达下钻：选中章节 → 该章节的知识点小雷达
const selectedChapter = ref('')

// 解锁状态：拍照上传过题目后才解锁诊断
const unlocked = ref(true)

const weakPoints = computed(() => radar.value.weak_points || [])
const hasSignal = computed(() => (radar.value.signal_count || 0) > 0)

// 按章节聚合知识点（小雷达数据源）
const chapterStats = computed(() => {
  const map = {}
  for (const s of stats.value) {
    const ch = s.chapter || '未分类'
    ;(map[ch] ||= []).push(s)
  }
  return map
})

const chapterList = computed(() =>
  Object.entries(chapterStats.value).map(([name, items]) => ({
    name,
    count: items.length,
    avg: items.reduce((a, b) => a + b.score, 0) / items.length,
    weak: items.filter((i) => i.weak >= 0.35).length,
  })).sort((a, b) => b.avg - a.avg)
)

const subAxes = computed(() => {
  if (!selectedChapter.value) return []
  return (chapterStats.value[selectedChapter.value] || []).map((s) => ({
    axis: s.kp_name,
    value: s.score,
    kp_count: 1,
  }))
})

const subList = computed(() => {
  if (!selectedChapter.value) return []
  return [...(chapterStats.value[selectedChapter.value] || [])].sort((a, b) => b.weak - a.weak)
})

// 全书章节数 vs 已练习章节数（用于提示"还有几章未开始"）
const unpracticedCount = computed(() =>
  (radar.value.axes || []).filter((a) => a.practiced === false).length
)

const overallAvg = computed(() => {
  if (!stats.value.length) return 0
  return stats.value.reduce((a, b) => a + b.score, 0) / stats.value.length
})

const practicedCount = computed(
  () => (radar.value.axes || []).filter((a) => a.practiced !== false).length
)

function drill(i) {
  const ch = radar.value.axes[i]?.axis
  if (ch) selectedChapter.value = selectedChapter.value === ch ? '' : ch
}

// 某章节下的重点攻克项（章节名可能带多余空格，用包含匹配兜底）
function chapterWeak(name) {
  const n = (name || '').trim()
  if (!n) return []
  return weakPoints.value.filter((w) => {
    const c = (w.chapter || '').trim()
    return c && (c === n || n.includes(c) || c.includes(n))
  })
}

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 前置：没上传过题目就不解锁诊断，避免展示一堆 0
    const u = await getUnlockStatus(userId.value).catch(() => null)
    unlocked.value = u ? !!u.unlocked : true
    if (!unlocked.value) return

    const [p, r] = await Promise.all([getProfile(userId.value), getRadar(userId.value)])
    profileMd.value = p.markdown || ''
    stats.value = p.stats || []
    radar.value = r
    try {
      report.value = await getLatestDiagnose(userId.value)
    } catch { report.value = null }
    reportList.value = await listDiagnose(userId.value).catch(() => [])
  } catch (e) {
    error.value = e.message || '加载失败，请确认后端已启动'
  } finally {
    loading.value = false
  }
}

async function genReport(useLlm) {
  genBusy.value = true
  try {
    report.value = await generateDiagnose(userId.value, useLlm)
    window.__toast?.(useLlm ? 'AI 诊断报告已生成' : '已生成快速报告（零 token 消耗）')
    reportList.value = await listDiagnose(userId.value).catch(() => [])
  } catch (e) {
    window.__toast?.('生成失败：' + (e.message || ''))
  } finally {
    genBusy.value = false
  }
}

function scoreColor(v) {
  return v >= 0.7 ? 'var(--ok)' : v >= 0.45 ? 'var(--warn)' : 'var(--err)'
}
</script>

<template>
  <div class="screen">
    <!-- 加载骨架 -->
    <section v-if="loading" class="card">
      <div class="sk" style="width: 38%; height: 15px"></div>
      <div class="sk" style="width: 62%; height: 10px; margin-top: 10px"></div>
      <div class="sk" style="height: 210px; border-radius: 18px; margin-top: 16px"></div>
      <div class="sk" style="width: 88%; height: 10px; margin-top: 16px"></div>
      <div class="sk" style="width: 70%; height: 10px; margin-top: 9px"></div>
    </section>

    <!-- 未解锁 -->
    <section v-else-if="!unlocked" class="card state-card">
      <div class="state-ico"><Icon name="lock" :size="30" :stroke="1.6" /></div>
      <h2>诊断尚未解锁</h2>
      <p>
        诊断报告与学习画像都由你的真实学习数据驱动。先去「拍照」问一道题，
        这里就会出现你的章节掌握度和薄弱点。
      </p>
      <router-link to="/camera" class="btn primary state-btn">
        去拍一道题
        <Icon name="arrow-right" :size="16" :stroke="2.2" />
      </router-link>
      <div class="state-steps">
        <span><i>1</i>上传题目</span>
        <em></em>
        <span><i>2</i>提交卡点</span>
        <em></em>
        <span><i>3</i>生成画像</span>
      </div>
    </section>

    <!-- 加载失败 -->
    <section v-else-if="error" class="card state-card">
      <div class="state-ico rose"><Icon name="alert" :size="30" :stroke="1.7" /></div>
      <h2>画像加载失败</h2>
      <p>{{ error }}</p>
      <button class="btn primary state-btn" @click="load">
        <Icon name="refresh" :size="16" :stroke="2.2" />
        重新加载
      </button>
    </section>

    <template v-else>
      <!-- 还没有学习信号 -->
      <section v-if="!hasSignal" class="card state-card">
        <div class="state-ico"><Icon name="chart" :size="30" :stroke="1.7" /></div>
        <h2>还没有学习数据</h2>
        <p>先去「拍照」问一道题并提交反馈，或做一次「练习」，这里就会有你的专属画像了。</p>
        <div class="btn-row state-actions">
          <router-link to="/camera" class="btn primary">去拍照</router-link>
          <router-link to="/practice" class="btn">去做练习</router-link>
        </div>
      </section>

      <template v-else>
        <!-- 总览数据 -->
        <div class="diag-stats">
          <div class="dstat">
            <span class="dstat-ico"><Icon name="sparkles" :size="16" :stroke="2" /></span>
            <b class="num">{{ radar.signal_count }}</b>
            <span>学习信号</span>
          </div>
          <div class="dstat">
            <span class="dstat-ico teal"><Icon name="target" :size="16" :stroke="2" /></span>
            <b class="num" :style="{ color: scoreColor(overallAvg) }">{{ overallAvg.toFixed(2) }}</b>
            <span>平均掌握度</span>
          </div>
          <div class="dstat">
            <span class="dstat-ico rose"><Icon name="flame" :size="16" :stroke="2" /></span>
            <b class="num" :style="{ color: weakPoints.length ? 'var(--err)' : 'var(--ok)' }">
              {{ weakPoints.length }}
            </b>
            <span>薄弱知识点</span>
          </div>
        </div>

        <!-- 大雷达：各章总体掌握度 -->
        <section class="card radar-card">
          <div class="card-head">
            <span class="card-ico"><Icon name="chart" :size="20" /></span>
            <div class="card-head-text">
              <div class="card-title">章节掌握度</div>
              <div class="card-sub">已练 {{ practicedCount }} / {{ (radar.axes || []).length }} 个章节</div>
            </div>
          </div>

          <RadarChart :axes="radar.axes || []" interactive @select="drill" />

          <div class="legend">
            <span><i class="dot brand"></i>已练章节</span>
            <span><i class="dot gray"></i>未练</span>
            <span class="legend-hint"><Icon name="target" :size="12" />点章节名下钻</span>
          </div>
          <p class="radar-note">
            共 {{ radar.signal_count }} 条学习信号 · {{ (radar.axes || []).length }} 个章节
            <template v-if="unpracticedCount"> · {{ unpracticedCount }} 章尚未学习</template>
          </p>
        </section>

        <!-- 章节明细：每章可展开，小雷达与重点攻克都在本章的折叠区内 -->
        <section class="card">
          <div class="card-head">
            <span class="card-ico teal"><Icon name="book" :size="20" /></span>
            <div class="card-head-text">
              <div class="card-title">章节明细</div>
              <div class="card-sub">按平均掌握度排序，点击展开知识点</div>
            </div>
          </div>

          <div class="chapter-list">
            <div v-for="c in chapterList" :key="c.name" class="chapter-item">
              <button
                class="chapter-row"
                :class="{ on: selectedChapter === c.name }"
                @click="selectedChapter = selectedChapter === c.name ? '' : c.name"
              >
                <span class="ch-main">
                  <span class="ch-name">{{ c.name }}</span>
                  <span class="ch-meta">
                    {{ c.count }} 个知识点
                    <template v-if="c.weak"> · <em class="weak">薄弱 {{ c.weak }}</em></template>
                  </span>
                  <span class="ch-bar">
                    <i :style="{ width: Math.max(4, c.avg * 100) + '%', background: scoreColor(c.avg) }"></i>
                  </span>
                </span>
                <span class="ch-score num" :style="{ color: scoreColor(c.avg) }">{{ c.avg.toFixed(2) }}</span>
                <Icon class="chev" name="chevron-down" :size="16" />
              </button>

              <div v-if="selectedChapter === c.name" class="chapter-body">
                <template v-if="subAxes.length">
                  <div class="sub-radar">
                    <RadarChart :axes="subAxes" :max-width="280" />
                  </div>
                  <div class="kp-list">
                    <div v-for="s in subList" :key="s.kp_id" class="kp-row">
                      <span class="kp-name">{{ s.kp_name }}</span>
                      <span class="kp-bar">
                        <i :style="{ width: Math.max(4, s.score * 100) + '%', background: scoreColor(s.score) }"></i>
                      </span>
                      <span class="kp-score num" :style="{ color: scoreColor(s.score) }">{{ s.score.toFixed(2) }}</span>
                      <span v-if="s.weak >= 0.35" class="tag err">薄弱</span>
                    </div>
                  </div>
                  <p class="sub-note">
                    共 {{ subAxes.length }} 个知识点；薄弱度 ≥ 0.35 会被列为重点攻克对象。
                  </p>
                </template>
                <div v-else class="banner warn" style="margin-top: 10px">
                  <Icon name="info" :size="15" />
                  <span>该章节还没有学习记录。去「拍照」提问或做一次「练习」后，这里会显示本章各知识点的掌握度。</span>
                </div>

                <template v-if="chapterWeak(c.name).length">
                  <div class="weak-head">
                    <Icon name="flame" :size="15" />
                    本章重点攻克
                    <span class="tag err">{{ chapterWeak(c.name).length }}</span>
                  </div>
                  <div v-for="w in chapterWeak(c.name)" :key="w.kp_id" class="weak-item">
                    <div class="weak-top">
                      <b>{{ w.kp_name }}</b>
                      <span class="tag err">薄弱 {{ w.weak.toFixed(2) }}</span>
                    </div>
                    <div class="weak-meta">
                      掌握度 {{ w.score.toFixed(2) }}
                      <template v-if="w.error_tags?.length"> · 错因：{{ w.error_tags.join('、') }}</template>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <p v-if="unpracticedCount" class="unpracticed">
            另有 {{ unpracticedCount }} 个章节尚未学习（雷达图上显示为 0，可点击查看）
          </p>
        </section>

        <!-- 诊断报告 -->
        <section class="card">
          <div class="card-head">
            <span class="card-ico amber"><Icon name="book" :size="20" /></span>
            <div class="card-head-text">
              <div class="card-title">诊断报告</div>
              <div class="card-sub">
                {{ report?.content_md ? '基于最近的学习证据生成' : '还没有生成过报告' }}
                <template v-if="reportList.length > 1"> · 历史 {{ reportList.length }} 份</template>
              </div>
            </div>
            <span v-if="report?.content_md" class="tag ok"><Icon name="check" :size="11" :stroke="2.6" />已生成</span>
          </div>

          <template v-if="report && report.content_md">
            <div class="report-meta">
              <span class="tag brand">v{{ report.version }}</span>
              <span v-if="report.confidence != null" class="tag">置信度 {{ report.confidence }}</span>
              <span v-if="report.token_used" class="tag">成本 {{ report.token_used }} tok</span>
            </div>
            <div class="answer report-answer">
              <MarkdownView :text="report.content_md" />
            </div>
            <div v-if="report.evidence?.length" class="evidence">
              <h3>原题证据</h3>
              <div v-for="(ev, i) in report.evidence" :key="i" class="ev-item">
                <span class="ev-dot" :class="ev.type"></span>
                <span class="ev-text">
                  <template v-if="ev.type === 'test'">
                    自测做错：{{ (ev.stem || '').slice(0, 46) }}（你答 {{ ev.user_answer ?? '—' }}，正确 {{ ev.correct_answer }}）
                  </template>
                  <template v-else-if="ev.type === 'qa'">
                    答疑反馈：{{ (ev.feedback?.selected || []).join('、') || '自定义描述' }}
                  </template>
                  <template v-else>该知识点暂无具体证据（样本不足）</template>
                </span>
              </div>
            </div>
          </template>
          <div v-else class="report-empty">
            <Icon name="info" :size="15" />
            <span>还没有生成过诊断报告。可以先用零成本的快速报告看看结论。</span>
          </div>

          <div class="btn-row report-actions">
            <button class="btn" :disabled="genBusy" @click="genReport(false)">
              <Icon name="refresh" :size="15" :stroke="2.2" />
              快速报告
            </button>
            <button class="btn primary" :disabled="genBusy" @click="genReport(true)">
              <Icon v-if="!genBusy" name="sparkles" :size="15" :stroke="2.2" />
              {{ genBusy ? '生成中…' : 'AI 深度报告' }}
            </button>
          </div>
          <p class="report-note">
            快速报告由规则引擎生成，不消耗 token；AI 报告会请大模型撰写（约 1~3 分钟）。
          </p>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* ---------- 状态卡 ---------- */
.state-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 30px 22px 26px;
}

.state-ico {
  display: grid;
  place-items: center;
  width: 70px;
  height: 70px;
  margin-bottom: 14px;
  border-radius: 24px;
  color: var(--brand);
  background: var(--brand-weak);
  box-shadow: inset 0 0 0 1px rgba(76, 111, 255, 0.08);
}

.state-ico.rose {
  color: var(--err);
  background: var(--err-weak);
}

.state-card h2 {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 760;
  letter-spacing: -0.02em;
}

.state-card p {
  max-width: 300px;
  font-size: 13px;
  line-height: 1.75;
  color: var(--ink-2);
}

.state-btn {
  margin-top: 16px;
  min-width: 168px;
  text-decoration: none;
}

.state-actions {
  margin-top: 16px;
  width: 100%;
  max-width: 300px;
}

.state-actions .btn {
  text-decoration: none;
}

.state-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
  font-size: 11px;
  color: var(--ink-3);
}

.state-steps span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.state-steps i {
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

.state-steps em {
  width: 12px;
  height: 1px;
  background: var(--line);
}

/* ---------- 总览数据 ---------- */
.diag-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
  margin-bottom: 14px;
}

.dstat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 12px 11px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--card);
  box-shadow: var(--shadow-sm);
}

.dstat-ico {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  margin-bottom: 4px;
  border-radius: 9px;
  background: var(--brand-weak);
  color: var(--brand);
}

.dstat-ico.teal {
  background: var(--ok-weak);
  color: var(--ok-ink);
}

.dstat-ico.rose {
  background: var(--err-weak);
  color: var(--err-ink);
}

.dstat b {
  font-size: 20px;
  font-weight: 780;
  line-height: 1.2;
}

.dstat > span:last-child {
  font-size: 10.5px;
  color: var(--ink-3);
  white-space: nowrap;
}

/* ---------- 雷达卡 ---------- */
.radar-card {
  padding-bottom: 14px;
}

.radar-card :deep(.radar-wrap) {
  margin: 2px 0;
}

.legend {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--ink-3);
}

.legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand);
}

.legend .dot.gray {
  background: var(--ink-3);
  opacity: 0.5;
}

.legend-hint {
  color: var(--brand);
}

.radar-note {
  margin-top: 6px;
  text-align: center;
  font-size: 11px;
  color: var(--ink-3);
}

/* ---------- 章节明细 ---------- */
.chapter-list {
  display: flex;
  flex-direction: column;
}

.chapter-item {
  border-bottom: 1px solid var(--line);
}

.chapter-item:last-child {
  border-bottom: 0;
}

.chapter-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 11px 6px;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.18s var(--ease);
}

.chapter-row:hover {
  background: var(--card-2);
}

.chapter-row.on {
  background: var(--brand-weak);
}

.ch-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ch-name {
  font-size: 13.5px;
  font-weight: 650;
  line-height: 1.4;
}

.ch-meta {
  font-size: 11px;
  color: var(--ink-3);
}

.ch-meta .weak {
  color: var(--err-ink);
  font-style: normal;
}

.ch-bar {
  display: block;
  height: 4px;
  margin-top: 3px;
  border-radius: 99px;
  background: var(--line-2);
  overflow: hidden;
}

.ch-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 0.5s var(--ease);
}

.ch-score {
  flex: 0 0 auto;
  font-size: 15px;
  font-weight: 750;
}

.chev {
  flex: 0 0 auto;
  color: var(--ink-3);
  transition: transform 0.2s var(--ease);
}

.chapter-row.on .chev {
  transform: rotate(180deg);
  color: var(--brand);
}

.chapter-body {
  padding: 4px 6px 16px;
  animation: reveal 0.22s var(--ease);
}

@keyframes reveal {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
}

.sub-radar {
  padding: 4px 0;
  border-radius: 14px;
  background: var(--card-2);
}

.kp-list {
  margin-top: 8px;
}

.kp-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 0;
  border-bottom: 1px solid var(--line);
}

.kp-row:last-child {
  border-bottom: 0;
}

.kp-name {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  line-height: 1.45;
}

.kp-bar {
  flex: 0 0 52px;
  height: 4px;
  border-radius: 99px;
  background: var(--line-2);
  overflow: hidden;
}

.kp-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.kp-score {
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 700;
}

.sub-note {
  margin-top: 9px;
  font-size: 11px;
  color: var(--ink-3);
}

.weak-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 16px 0 6px;
  font-size: 13px;
  font-weight: 650;
  color: var(--err-ink);
}

.weak-item {
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
}

.weak-item:last-child {
  border-bottom: 0;
}

.weak-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.weak-top b {
  flex: 1;
  font-size: 13px;
  font-weight: 650;
}

.weak-meta {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--ink-3);
  line-height: 1.55;
}

.unpracticed {
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  color: var(--ink-3);
}

/* ---------- 报告 ---------- */
.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 9px;
}

.report-answer {
  max-height: none;
}

.evidence {
  margin-top: 4px;
}

.evidence h3 {
  margin-top: 14px;
}

.ev-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 5px 0;
}

.ev-dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  margin-top: 7px;
  border-radius: 50%;
  background: var(--ink-3);
}

.ev-dot.test {
  background: var(--err);
}

.ev-dot.qa {
  background: var(--brand);
}

.ev-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--ink-2);
}

.report-empty {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 13px;
  border: 1px dashed var(--line);
  border-radius: 12px;
  background: var(--card-2);
  font-size: 12.5px;
  color: var(--ink-3);
  line-height: 1.6;
}

.report-actions {
  margin-top: 14px;
}

.report-note {
  margin-top: 9px;
  font-size: 11px;
  line-height: 1.55;
  color: var(--ink-3);
}
</style>
