<script setup>
import { ref, onMounted, computed } from 'vue'
import { getWrongbook, markMastered, getTokens, getKbStats, getProfile, listQuestions, listTests } from '../api'
import { userId, setUserId } from '../store/user'
import MarkdownView from '../components/MarkdownView.vue'

const tab = ref('wrong')        // wrong | stats
const wrong = ref({ stats: {}, items: [] })
const filter = ref('')          // '' | pending | mastered
const tokens = ref(null)
const kb = ref(null)
const overview = ref({ questions: 0, tests: 0, signals: 0, weak: 0 })
const loading = ref(true)
const uidInput = ref(String(userId.value))

const DEMO_USER = 1001  // 汇报演示用户（scripts/seed_demo_user.py 生成）

onMounted(load)

async function load() {
  loading.value = true
  try {
    wrong.value = await getWrongbook(userId.value, filter.value || undefined)
    tokens.value = await getTokens(userId.value).catch(() => null)
    kb.value = await getKbStats().catch(() => null)
    // 数据总览：让"我的数据在哪"一目了然
    const [qs, ts, prof] = await Promise.all([
      listQuestions(userId.value, 100).catch(() => []),
      listTests(userId.value).catch(() => []),
      getProfile(userId.value).catch(() => null),
    ])
    overview.value = {
      questions: (qs || []).length,
      tests: (ts || []).filter((t) => t.status === 'submitted').length,
      signals: prof?.radar?.signal_count || 0,
      weak: (prof?.radar?.weak_points || []).length,
    }
  } finally {
    loading.value = false
  }
}

async function setFilter(f) {
  filter.value = f
  wrong.value = await getWrongbook(userId.value, f || undefined)
}

async function toggleMastered(w) {
  const target = w.status !== 'mastered'
  await markMastered(userId.value, w.id, target)
  window.__toast?.(target ? '已标记掌握（掌握度 +0.2）' : '已重新加入错题')
  await load()
}

function applyUser(id) {
  setUserId(id)
  uidInput.value = String(userId.value)
  window.__toast?.('已切换用户 ' + userId.value)
  load()
}

const scenes = computed(() => {
  const s = tokens.value?.scenes || {}
  return Object.entries(s).map(([k, v]) => ({
    key: k,
    label: { qa: '拍照答疑', diagnose: '诊断报告', test_explain: '题目详解', context_probe: '上下文实验' }[k] || k,
    ...v,
  }))
})
</script>

<template>
  <div class="screen">
    <div class="card">
      <h2>👤 当前用户</h2>
      <div style="display: flex; gap: 10px">
        <input v-model="uidInput" inputmode="numeric" placeholder="用户 ID" />
        <button class="btn primary" style="flex: 0 0 auto" @click="applyUser(uidInput)">切换</button>
      </div>
      <div class="btn-row" style="margin-top: 10px">
        <button class="btn" :disabled="userId === 1" @click="applyUser(1)">我的账号（1）</button>
        <button class="btn" :class="{ primary: userId === DEMO_USER }" @click="applyUser(DEMO_USER)">
          演示数据（{{ DEMO_USER }}）
        </button>
      </div>
      <p class="muted" style="margin-bottom: 0">
        数据保存在后端数据库（backend/dev.db）与浏览器缓存中，关掉应用不会丢失；
        切换用户 ID 可查看不同账号的数据。
      </p>
    </div>

    <!-- 数据总览 -->
    <div class="card">
      <h2>数据总览</h2>
      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; text-align: center">
        <div>
          <div style="font-size: 20px; font-weight: 600; color: var(--brand)">{{ overview.questions }}</div>
          <div class="muted" style="font-size: 12px">答疑记录</div>
        </div>
        <div>
          <div style="font-size: 20px; font-weight: 600; color: var(--brand)">{{ overview.tests }}</div>
          <div class="muted" style="font-size: 12px">完成练习</div>
        </div>
        <div>
          <div style="font-size: 20px; font-weight: 600; color: var(--brand)">{{ wrong.stats.total || 0 }}</div>
          <div class="muted" style="font-size: 12px">错题</div>
        </div>
        <div>
          <div style="font-size: 20px; font-weight: 600; color: var(--brand)">{{ overview.signals }}</div>
          <div class="muted" style="font-size: 12px">画像信号</div>
        </div>
      </div>
    </div>

    <div class="btn-row" style="margin-bottom: 12px">
      <button class="btn" :class="{ primary: tab === 'wrong' }" @click="tab = 'wrong'">错题本</button>
      <button class="btn" :class="{ primary: tab === 'stats' }" @click="tab = 'stats'">数据 &amp; 成本</button>
    </div>

    <div v-if="loading" class="card loading"><div class="spinner"></div>加载中…</div>

    <!-- 错题本 -->
    <template v-else-if="tab === 'wrong'">
      <div class="card">
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
          <b style="flex: 1">共 {{ wrong.stats.total || 0 }} 道</b>
          <span class="tag warn">待攻克 {{ wrong.stats.pending || 0 }}</span>
          <span class="tag ok">已掌握 {{ wrong.stats.mastered || 0 }}</span>
        </div>
        <div class="btn-row" style="margin-top: 10px">
          <button class="btn" :class="{ primary: filter === '' }" @click="setFilter('')">全部</button>
          <button class="btn" :class="{ primary: filter === 'pending' }" @click="setFilter('pending')">待攻克</button>
          <button class="btn" :class="{ primary: filter === 'mastered' }" @click="setFilter('mastered')">已掌握</button>
        </div>
      </div>

      <div v-if="!wrong.items?.length" class="empty">还没有错题。<br />做错的题目会自动收集到这里。</div>

      <div v-for="w in wrong.items" :key="w.id" class="card">
        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap">
          <span class="tag" :class="w.status === 'mastered' ? 'ok' : 'warn'">
            {{ w.status === 'mastered' ? '已掌握' : '待攻克' }}
          </span>
          <span class="tag">{{ w.source === 'test' ? '自测错题' : '答疑未解决' }}</span>
          <span class="tag" v-if="w.wrong_count > 1">错过 {{ w.wrong_count }} 次</span>
          <span class="tag err" v-for="t in (w.error_tags || [])" :key="t">{{ t }}</span>
        </div>

        <img v-if="w.image_path && w.source === 'test'" :src="'/' + w.image_path" class="preview" style="margin-bottom: 8px" alt="" />
        <div class="stem-box">
          <MarkdownView v-if="w.stem" :text="w.stem" />
          <span v-else class="muted">（答疑图片题，见拍照记录）</span>
        </div>

        <div v-if="w.answer" style="margin-top: 8px; font-size: 14px">
          正确答案：<b style="color: var(--ok)"><MarkdownView :text="w.answer" /></b>
        </div>
        <details v-if="w.solution" style="margin-top: 8px">
          <summary class="hint" style="cursor: pointer">查看库内解析</summary>
          <div class="answer" style="margin-top: 6px"><MarkdownView :text="w.solution" /></div>
        </details>

        <button class="btn block" style="margin-top: 10px" :class="w.status === 'mastered' ? '' : 'ok'" @click="toggleMastered(w)">
          {{ w.status === 'mastered' ? '重新加入错题' : '✓ 我已掌握（掌握度 +0.2）' }}
        </button>
      </div>
    </template>

    <!-- 数据与成本 -->
    <template v-else>
      <div class="card" v-if="kb">
        <h2>知识库规模</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px">
          <div><div class="muted">章节</div><b>{{ kb.knowledge_points?.chapters }} 章 / {{ kb.knowledge_points?.sections }} 节</b></div>
          <div><div class="muted">知识点</div><b>{{ kb.knowledge_points?.points }} 个</b></div>
          <div><div class="muted">题库</div><b>{{ kb.problems }} 道</b></div>
          <div><div class="muted">可自动判分</div><b>{{ kb.objective }} 道</b></div>
        </div>
      </div>

      <div class="card" v-if="tokens">
        <h2>Token 消耗（我的）</h2>
        <div v-if="!scenes.length" class="muted">暂无调用记录。</div>
        <div v-else>
          <div v-for="s in scenes" :key="s.key" style="padding: 8px 0; border-bottom: 1px solid var(--line)">
            <div style="display: flex; gap: 8px; align-items: center">
              <b style="flex: 1; font-size: 14px">{{ s.label }}</b>
              <span class="tag">{{ s.calls }} 次调用</span>
            </div>
            <div class="muted" style="font-size: 12px">
              单次均 {{ s.avg_per_call }} tok · 推理占比 {{ s.reasoning_share }}%
              <template v-if="s.cache_hit_rate != null"> · 缓存命中 {{ s.cache_hit_rate }}%</template>
              <template v-if="s.avg_latency_ms"> · 平均 {{ (s.avg_latency_ms / 1000).toFixed(1) }}s</template>
            </div>
          </div>
          <p class="muted" style="margin-bottom: 0; margin-top: 10px">
            累计 {{ tokens.total_calls }} 次调用 / {{ tokens.total_tokens }} token
          </p>
        </div>
      </div>
      <div v-else class="card muted">本地未记录到 token 数据（可能后端未启用计量或尚无调用）。</div>
    </template>
  </div>
</template>
