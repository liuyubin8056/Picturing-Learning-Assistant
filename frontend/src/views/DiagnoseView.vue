<script setup>
import { ref, onMounted, computed } from 'vue'
import { getProfile, generateDiagnose, getLatestDiagnose, listDiagnose, getRadar } from '../api'
import { userId } from '../store/user'
import RadarChart from '../components/RadarChart.vue'
import MarkdownView from '../components/MarkdownView.vue'

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

function drill(i) {
  const ch = radar.value.axes[i]?.axis
  if (ch) selectedChapter.value = selectedChapter.value === ch ? '' : ch
}

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
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
    <div v-if="loading" class="card loading"><div class="spinner"></div>加载画像…</div>

    <div v-else-if="error" class="card">
      <div class="banner err">{{ error }}</div>
      <button class="btn primary block" @click="load">重试</button>
    </div>

    <template v-else>
      <div v-if="!hasSignal" class="card">
        <h2>📊 学习诊断</h2>
        <div class="banner warn">
          还没有学习数据。先去「拍照」问一道题并提交反馈，或做一次「练习」，这里就会有你的专属画像了。
        </div>
      </div>

      <template v-else>
        <!-- 大雷达：各章总体掌握度 -->
        <div class="card">
          <h2>掌握度总览（按章节）</h2>
          <RadarChart :axes="radar.axes || []" interactive @select="drill" />
          <p class="muted" style="text-align: center; margin-bottom: 0">
            共 {{ radar.signal_count }} 条学习信号 · {{ (radar.axes || []).length }} 个章节 ·
            <span style="color: var(--brand)">点击章节名查看该章知识点</span>
          </p>
        </div>

        <!-- 章节列表（点选下钻） -->
        <div class="card">
          <h2>章节明细</h2>
          <div
            v-for="c in chapterList"
            :key="c.name"
            class="chapter-row"
            :class="{ on: selectedChapter === c.name }"
            @click="selectedChapter = selectedChapter === c.name ? '' : c.name"
          >
            <div style="flex: 1">
              <b style="font-size: 14px">{{ c.name }}</b>
              <div class="muted" style="font-size: 12px">
                {{ c.count }} 个知识点
                <template v-if="c.weak"> · <span style="color: var(--err)">薄弱 {{ c.weak }}</span></template>
              </div>
            </div>
            <span class="tag" :style="{ color: scoreColor(c.avg), borderColor: scoreColor(c.avg) }">
              {{ c.avg.toFixed(2) }}
            </span>
            <span class="chev">{{ selectedChapter === c.name ? '▾' : '›' }}</span>
          </div>
          <p v-if="unpracticedCount" class="muted" style="font-size: 12px; margin: 8px 0 0">
            另有 {{ unpracticedCount }} 个章节尚未学习（雷达图上显示为 0，可点击查看）
          </p>
        </div>

        <!-- 小雷达：选中章节的知识点掌握度 -->
        <div v-if="selectedChapter" class="card">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px">
            <h2 style="margin: 0; flex: 1">{{ selectedChapter }}</h2>
            <button class="btn ghost" @click="selectedChapter = ''">收起</button>
          </div>
          <template v-if="subAxes.length">
            <RadarChart :axes="subAxes" :max-width="340" />
            <div style="margin-top: 6px">
              <div
                v-for="s in subList"
                :key="s.kp_id"
                style="display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--line)"
              >
                <span style="flex: 1; font-size: 13.5px">{{ s.kp_name }}</span>
                <span class="tag" :style="{ color: scoreColor(s.score), borderColor: scoreColor(s.score) }">
                  掌握 {{ s.score.toFixed(2) }}
                </span>
                <span v-if="s.weak >= 0.35" class="tag err">薄弱 {{ s.weak.toFixed(2) }}</span>
              </div>
            </div>
            <p class="muted" style="font-size: 12px; margin: 8px 0 0">
              共 {{ subAxes.length }} 个知识点；薄弱度 ≥ 0.35 会被列为重点攻克对象。
            </p>
          </template>
          <div v-else class="banner warn" style="margin-top: 8px">
            该章节还没有学习记录。去「拍照」提问或做一次「练习」后，这里会显示本章各知识点的掌握度。
          </div>
        </div>

        <!-- 薄弱点 -->
        <div class="card" v-if="weakPoints.length">
          <h2>🔴 需要重点攻克（{{ weakPoints.length }}）</h2>
          <div
            v-for="w in weakPoints.slice(0, 8)"
            :key="w.kp_id"
            style="padding: 8px 0; border-bottom: 1px solid var(--line)"
          >
            <div style="display: flex; align-items: center; gap: 8px">
              <b style="flex: 1; font-size: 14px">{{ w.kp_name }}</b>
              <span class="tag err">薄弱 {{ w.weak.toFixed(2) }}</span>
            </div>
            <div class="muted" style="font-size: 12px">
              {{ w.chapter }} · 掌握度 {{ w.score.toFixed(2) }}
              <template v-if="w.error_tags?.length"> · 错因：{{ w.error_tags.join('、') }}</template>
            </div>
          </div>
        </div>

        <!-- 诊断报告 -->
        <div class="card">
          <h2>📄 诊断报告</h2>
          <template v-if="report && report.content_md">
            <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap">
              <span class="tag brand">v{{ report.version }}</span>
              <span class="tag" v-if="report.confidence != null">置信度 {{ report.confidence }}</span>
              <span class="tag" v-if="report.token_used">成本 {{ report.token_used }} tok</span>
            </div>
            <div class="answer" style="max-height: 520px">
              <MarkdownView :text="report.content_md" />
            </div>
            <div v-if="report.evidence?.length" style="margin-top: 12px">
              <h3>原题证据</h3>
              <div v-for="(ev, i) in report.evidence" :key="i" class="muted" style="font-size: 12.5px">
                <template v-if="ev.type === 'test'">· 自测做错：{{ (ev.stem || '').slice(0, 46) }}（你答 {{ ev.user_answer ?? '—' }}，正确 {{ ev.correct_answer }}）</template>
                <template v-else-if="ev.type === 'qa'">· 答疑反馈：{{ (ev.feedback?.selected || []).join('、') || '自定义描述' }}</template>
                <template v-else>· 该知识点暂无具体证据（样本不足）</template>
              </div>
            </div>
          </template>
          <p v-else class="muted">还没有生成过诊断报告。</p>

          <div class="btn-row" style="margin-top: 12px">
            <button class="btn" :disabled="genBusy" @click="genReport(false)">快速报告（0 成本）</button>
            <button class="btn primary" :disabled="genBusy" @click="genReport(true)">
              {{ genBusy ? '生成中…' : 'AI 深度报告' }}
            </button>
          </div>
          <p class="muted" style="font-size: 12px; margin-bottom: 0">
            快速报告由规则引擎生成，不消耗 token；AI 报告会请大模型撰写（约 1~3 分钟）。
          </p>
        </div>

        <!-- 画像原文 -->
        <div class="card" v-if="profileMd">
          <h2>📝 我的画像（Markdown 存档）</h2>
          <div class="answer" style="max-height: 420px">
            <MarkdownView :text="profileMd" />
          </div>
          <p class="muted" style="font-size: 12px; margin-bottom: 0">每次提交反馈或完成练习后即时更新。</p>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.chapter-row {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 8px; border-radius: 10px; cursor: pointer;
  border-bottom: 1px solid var(--line);
}
.chapter-row:hover { background: #f8fafd; }
.chapter-row.on { background: var(--brand-weak); }
.chev { color: var(--ink-3); font-size: 15px; }
</style>
