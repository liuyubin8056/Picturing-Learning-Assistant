<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  sendEmailCode,
  loginByCode,
  getMe,
  adminUsers,
  adminOverview,
  adminTimeline,
  demoLogin,
  logout as apiLogout,
} from '../api'
import { applyLogin, currentUser, clearLogin } from '../store/user'
import Icon from '../components/Icon.vue'
import TrendChart from '../components/TrendChart.vue'

defineOptions({ name: 'AdminView' })

// ---------- 登录态 ----------
const checking = ref(true)
const me = ref(null)          // 管理员信息（null = 未登录或无权限）
const denied = ref(false)     // 登录了但不是管理员

// ---------- 登录表单 ----------
const email = ref('')
const code = ref('')
const step = ref('email')     // email | code
const cooldown = ref(0)
const busy = ref(false)
const error = ref('')

const emailOk = computed(() => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim()))
const canSend = computed(() => emailOk.value && cooldown.value === 0 && !busy.value)

function tickCooldown() {
  cooldown.value = 60
  const t = setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) clearInterval(t)
  }, 1000)
}

async function sendCode() {
  if (!canSend.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await sendEmailCode(email.value.trim())
    tickCooldown()
    step.value = 'code'
    window.__toast?.(r?.debug_code ? `验证码：${r.debug_code}（开发模式）` : '验证码已发送，请查收邮箱')
  } catch (e) {
    error.value = e.message || '发送失败'
  } finally {
    busy.value = false
  }
}

async function doLogin() {
  if (!code.value.trim()) {
    error.value = '请输入验证码'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const r = await loginByCode(email.value.trim(), code.value.trim(), false)
    applyLogin(r)
    const info = await getMe()
    if (!info?.is_admin) {
      denied.value = true
      me.value = null
      return
    }
    me.value = info
    await loadAll()
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    busy.value = false
  }
}

async function doLogout() {
  try {
    await apiLogout()
  } catch {
    /* 忽略 */
  }
  clearLogin()
  me.value = null
  users.value = []
  overview.value = null
  timeline.value = null
  step.value = 'email'
  code.value = ''
}

async function enterDemo() {
  try {
    const r = await demoLogin()
    applyLogin(r)
    window.__toast?.('已切换到演示账号')
    window.location.hash = '#/camera'
  } catch (e) {
    window.__toast?.(e.message || '进入演示账号失败')
  }
}

// ---------- 数据 ----------
const loading = ref(false)
const users = ref([])
const overview = ref(null)

const timeline = ref(null)
const tlLoading = ref(false)
const tlDays = ref(30)
const tlUserId = ref(null)          // null = 全站；点某一行后只看这个人

async function loadAll() {
  loading.value = true
  try {
    const [ov, list] = await Promise.all([adminOverview(), adminUsers()])
    overview.value = ov
    users.value = list.users || []
    await loadTimeline()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadTimeline() {
  tlLoading.value = true
  try {
    timeline.value = await adminTimeline({ days: tlDays.value, userId: tlUserId.value })
  } catch (e) {
    error.value = e.message || '时间轴加载失败'
  } finally {
    tlLoading.value = false
  }
}

// 切换范围 / 切换查看对象时只重取时间轴，不动用户列表
watch([tlDays, tlUserId], loadTimeline)

const tlSeries = computed(() => timeline.value?.series || [])
const apiPoints = computed(() => tlSeries.value.map((r) => ({ day: r.day, value: r.api_hits })))
const tokenPoints = computed(() => tlSeries.value.map((r) => ({ day: r.day, value: r.tokens_total })))
const tlTotals = computed(() => timeline.value?.totals || {})
const tlScenes = computed(() => timeline.value?.scenes || [])
// 项目早期用量稀疏时，图上几乎是一条平线，容易被误读成"坏了"。
// 明确告诉用户「30 天里只有 3 天有量」比让他自己猜要友好。
const activeDays = computed(() => tlSeries.value.filter((r) => r.api_hits > 0 || r.tokens_total > 0).length)

const scopeUser = computed(() => users.value.find((u) => u.id === tlUserId.value) || null)

function focusUser(u) {
  tlUserId.value = tlUserId.value === u.id ? null : u.id
  document.querySelector('.adm-trend')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ---------- 概览卡 ----------
const cards = computed(() => {
  const o = overview.value || {}
  return [
    { label: '注册用户', value: o.users ?? 0, sub: `7 日新增 ${o.users_new_7d ?? 0}` },
    { label: '今日 API 访问', value: o.api_hits_today ?? 0, sub: `累计 ${fmt(o.api_hits_total ?? 0)}` },
    { label: '今日大模型调用', value: o.llm_calls_today ?? 0, sub: `累计 ${fmt(o.llm_calls ?? 0)} 次` },
    { label: '今日 Token', value: fmt(o.tokens_today ?? 0), sub: `累计 ${fmt(o.tokens_total ?? 0)}` },
    { label: '拍照答疑', value: o.questions ?? 0, sub: `已完成 ${o.questions_answered ?? 0}` },
    { label: '练习试卷', value: o.test_sessions ?? 0, sub: `错题 ${o.wrong_books ?? 0} 条` },
    { label: '知识点覆盖', value: o.mastery_points ?? 0, sub: `诊断报告 ${o.diagnose_reports ?? 0} 份` },
    { label: '7 日活跃', value: o.users_active_7d ?? 0, sub: `演示账号 ${o.demo_users ?? 0} 个` },
  ]
})

// ---------- 表格：搜索 / 筛选 / 排序 / 分页 ----------
const q = ref('')
const filter = ref('all')           // all | email | admin | demo | active
const sortKey = ref('created_at')
const sortDir = ref('desc')         // asc | desc
const page = ref(1)
const pageSize = ref(20)

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'email', label: '已绑邮箱' },
  { key: 'active', label: '7 日活跃' },
  { key: 'admin', label: '管理员' },
  { key: 'demo', label: '演示账号' },
]

const WEEK = 7 * 24 * 3600 * 1000

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  const now = Date.now()
  return users.value.filter((u) => {
    if (kw) {
      const hay = `${u.nickname || ''} ${u.email || ''} ${u.id}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    if (filter.value === 'email') return !!u.email
    if (filter.value === 'admin') return !!u.is_admin
    if (filter.value === 'demo') return !!u.is_demo
    if (filter.value === 'active') {
      if (!u.last_login_at) return false
      return now - new Date(u.last_login_at).getTime() <= WEEK
    }
    return true
  })
})

const sorted = computed(() => {
  const k = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  const arr = [...filtered.value]
  arr.sort((a, b) => {
    const va = a[k]
    const vb = b[k]
    if (va == null && vb == null) return 0
    if (va == null) return 1            // 空值永远沉底，不随方向翻转
    if (vb == null) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
  return arr
})

const pageCount = computed(() => Math.max(1, Math.ceil(sorted.value.length / pageSize.value)))
const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return sorted.value.slice(start, start + pageSize.value)
})

watch([q, filter, pageSize], () => {
  page.value = 1
})
watch(pageCount, (n) => {
  if (page.value > n) page.value = n
})

function sortBy(k) {
  if (sortKey.value === k) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = k
    // 数值默认从大到小，时间默认最新在前，名字默认升序
    sortDir.value = k === 'nickname' || k === 'email' ? 'asc' : 'desc'
  }
}

function sortMark(k) {
  if (sortKey.value !== k) return ''
  return sortDir.value === 'asc' ? '↑' : '↓'
}

// ---------- 格式化 ----------
function fmt(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function fmtTime(iso, withTime = true) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x) => String(x).padStart(2, '0')
  const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  return withTime ? `${day} ${p(d.getHours())}:${p(d.getMinutes())}` : day
}

function ago(iso) {
  if (!iso) return '从未'
  const ms = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(ms)) return '—'
  const d = Math.floor(ms / 86400000)
  if (d <= 0) return '今天'
  if (d === 1) return '昨天'
  if (d < 30) return `${d} 天前`
  return `${Math.floor(d / 30)} 个月前`
}

onMounted(async () => {
  try {
    const info = await getMe()
    if (info?.is_admin) {
      me.value = info
      currentUser.value = info
      await loadAll()
    } else if (info) {
      denied.value = true
    }
  } catch {
    /* 未登录，展示登录表单 */
  } finally {
    checking.value = false
  }
})
</script>

<template>
  <div class="admin">
    <header class="adm-head">
      <div class="adm-title">
        <span class="adm-logo">∑</span>
        <div>
          <b>管理后台</b>
          <small>智能拍照学习助手 · 运营数据</small>
        </div>
      </div>
      <div class="adm-actions">
        <button v-if="me" class="btn sm" :disabled="loading" @click="loadAll">
          <Icon name="refresh" :size="14" :stroke="2" /> 刷新
        </button>
        <button v-if="me" class="btn sm" @click="enterDemo">
          <Icon name="sparkles" :size="14" :stroke="2" /> 演示账号
        </button>
        <button v-if="me" class="btn sm ghost" @click="doLogout">退出</button>
      </div>
    </header>

    <p v-if="checking" class="adm-hint">正在检查登录状态…</p>

    <!-- 登录 -->
    <section v-else-if="!me" class="adm-login card">
      <h2>管理员登录</h2>
      <p class="adm-hint">
        这里只对管理员开放。使用管理员的邮箱接收验证码登录，普通账号登录后也无法看到数据。
      </p>

      <template v-if="step === 'email'">
        <label class="field-label" for="adm-email">邮箱</label>
        <input
          id="adm-email"
          v-model="email"
          type="email"
          inputmode="email"
          placeholder="admin@example.com"
          @keyup.enter="sendCode"
        />
        <button class="btn primary block" :disabled="!canSend" @click="sendCode">
          {{ cooldown > 0 ? `${cooldown} 秒后可重发` : '发送验证码' }}
        </button>
      </template>

      <template v-else>
        <label class="field-label" for="adm-code">验证码（已发送到 {{ email }}）</label>
        <input
          id="adm-code"
          v-model="code"
          inputmode="numeric"
          maxlength="6"
          placeholder="6 位验证码"
          @keyup.enter="doLogin"
        />
        <div class="adm-row">
          <button class="btn ghost" @click="step = 'email'">换个邮箱</button>
          <button class="btn primary" :disabled="busy" @click="doLogin">
            {{ busy ? '登录中…' : '登录' }}
          </button>
        </div>
      </template>

      <div v-if="error" class="banner err" style="margin-top: 10px">{{ error }}</div>
      <div v-if="denied" class="banner warn" style="margin-top: 10px">
        该账号不是管理员。<a href="#/login">返回普通登录</a>
      </div>
    </section>

    <!-- 数据 -->
    <template v-else>
      <div class="adm-cards">
        <div v-for="c in cards" :key="c.label" class="adm-card">
          <div class="adm-card-label">{{ c.label }}</div>
          <div class="adm-card-value">{{ c.value }}</div>
          <div class="adm-card-sub">{{ c.sub }}</div>
        </div>
      </div>

      <!-- 时间轴：按天的 API 调用量与 Token 用量 -->
      <section class="card adm-trend">
        <div class="adm-table-head">
          <div>
            <h2>用量时间轴</h2>
            <small class="adm-updated">
              {{ timeline?.start }} ~ {{ timeline?.end }} · 按北京时间（UTC+8）自然日统计
            </small>
          </div>
          <div class="adm-range">
            <button
              v-for="d in [7, 14, 30, 90]"
              :key="d"
              class="seg-btn"
              :class="{ on: tlDays === d }"
              @click="tlDays = d"
            >
              {{ d }} 天
            </button>
          </div>
        </div>

        <div v-if="scopeUser" class="adm-scope">
          <Icon name="user" :size="13" :stroke="2" />
          正在查看
          <b>{{ scopeUser.nickname }}</b>
          <span v-if="scopeUser.email" class="adm-scope-mail">{{ scopeUser.email }}</span>
          <button class="adm-scope-x" @click="tlUserId = null">返回全站</button>
        </div>

        <div class="adm-charts" :class="{ dim: tlLoading }">
          <div class="chart-block">
            <div class="chart-head">
              <span class="chart-title">API 调用量</span>
              <span class="chart-total">{{ (tlTotals.api_hits ?? 0).toLocaleString() }} 次</span>
            </div>
            <TrendChart :points="apiPoints" color="#4c6fff" :height="150" unit=" 次" />
            <div class="chart-foot">
              峰值 {{ timeline?.peak?.api_hits?.value ?? 0 }} 次 · {{ timeline?.peak?.api_hits?.day || '—' }}
              <span v-if="activeDays < tlDays" class="chart-note">
                （{{ tlDays }} 天里只有 {{ activeDays }} 天有量）
              </span>
            </div>
          </div>

          <div class="chart-block">
            <div class="chart-head">
              <span class="chart-title">Token 用量</span>
              <span class="chart-total">{{ (tlTotals.tokens_total ?? 0).toLocaleString() }}</span>
            </div>
            <TrendChart :points="tokenPoints" color="#8b5cf6" :height="150" unit=" tokens" />
            <div class="chart-foot">
              输入 {{ fmt(tlTotals.tokens_prompt ?? 0) }} · 输出 {{ fmt(tlTotals.tokens_completion ?? 0) }}
            </div>
          </div>
        </div>

        <!-- 按场景拆分：钱到底花在哪个功能上 -->
        <div v-if="tlScenes.length" class="adm-scenes">
          <div class="scene-title">Token 消耗构成</div>
          <div v-for="s in tlScenes" :key="s.scene" class="scene-row">
            <span class="scene-name">{{ s.label }}</span>
            <span class="scene-bar"><i :style="{ width: Math.max(2, s.share * 100) + '%' }"></i></span>
            <span class="scene-val">
              {{ fmt(s.tokens) }}
              <small>{{ (s.share * 100).toFixed(1) }}% · {{ s.calls }} 次</small>
            </span>
          </div>
        </div>
      </section>

      <!-- 用户明细 -->
      <section class="card adm-table-card">
        <div class="adm-table-head">
          <div>
            <h2>用户明细（{{ filtered.length }}）</h2>
            <small class="adm-updated">点表头排序，点某一行查看该用户的时间轴</small>
          </div>
          <span class="adm-updated">更新于 {{ fmtTime(overview?.generated_at) }}</span>
        </div>

        <div class="adm-toolbar">
          <div class="adm-search">
            <Icon name="search" :size="14" :stroke="2" />
            <input v-model="q" placeholder="搜索邮箱、昵称或用户 ID" />
            <button v-if="q" class="adm-clear" @click="q = ''">×</button>
          </div>
          <div class="adm-filter">
            <button
              v-for="f in FILTERS"
              :key="f.key"
              class="seg-btn"
              :class="{ on: filter === f.key }"
              @click="filter = f.key"
            >
              {{ f.label }}
            </button>
          </div>
          <select v-model.number="pageSize" class="adm-size">
            <option :value="20">每页 20</option>
            <option :value="50">每页 50</option>
            <option :value="100">每页 100</option>
          </select>
        </div>

        <div class="adm-scroll">
          <table class="adm-table">
            <thead>
              <tr>
                <th @click="sortBy('nickname')">用户 {{ sortMark('nickname') }}</th>
                <th @click="sortBy('email')">邮箱 {{ sortMark('email') }}</th>
                <th @click="sortBy('created_at')">注册时间 {{ sortMark('created_at') }}</th>
                <th @click="sortBy('last_login_at')">最近登录 {{ sortMark('last_login_at') }}</th>
                <th class="num" @click="sortBy('questions')">拍题 {{ sortMark('questions') }}</th>
                <th class="num" @click="sortBy('test_answered')">答题 {{ sortMark('test_answered') }}</th>
                <th class="num" @click="sortBy('test_sessions')">练习卷 {{ sortMark('test_sessions') }}</th>
                <th class="num" @click="sortBy('wrong_books')">错题 {{ sortMark('wrong_books') }}</th>
                <th class="num" @click="sortBy('mastery_points')">知识点 {{ sortMark('mastery_points') }}</th>
                <th class="num" @click="sortBy('diagnose_reports')">诊断 {{ sortMark('diagnose_reports') }}</th>
                <th class="num" @click="sortBy('api_hits')">API 访问 {{ sortMark('api_hits') }}</th>
                <th class="num" @click="sortBy('llm_calls')">LLM 调用 {{ sortMark('llm_calls') }}</th>
                <th class="num" @click="sortBy('tokens_total')">Token {{ sortMark('tokens_total') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="u in paged"
                :key="u.id"
                :class="{ demo: u.is_demo, admin: u.is_admin, picked: u.id === tlUserId }"
                @click="focusUser(u)"
              >
                <td class="who">
                  <b>{{ u.anonymous ? '影子账号' : u.nickname }}</b>
                  <span class="tag" v-if="u.is_admin">管理员</span>
                  <span class="tag" v-if="u.is_demo">演示</span>
                  <span class="tag" v-if="u.anonymous">无邮箱</span>
                  <small>ID {{ u.id }}</small>
                </td>
                <td class="mail">{{ u.email || '（未绑定）' }}</td>
                <td class="num">{{ fmtTime(u.created_at, false) }}</td>
                <td class="num" :title="fmtTime(u.last_login_at)">{{ ago(u.last_login_at) }}</td>
                <td class="num">{{ u.questions }}</td>
                <td class="num">{{ u.test_answered }}</td>
                <td class="num">{{ u.test_sessions }}</td>
                <td class="num">{{ u.wrong_books }}</td>
                <td class="num">{{ u.mastery_points }}</td>
                <td class="num">{{ u.diagnose_reports }}</td>
                <td class="num">
                  {{ u.api_hits }}
                  <small v-if="u.api_hits_today">今 {{ u.api_hits_today }}</small>
                </td>
                <td class="num">{{ u.llm_calls }}</td>
                <td class="num" :title="`输入 ${u.tokens_prompt} / 输出 ${u.tokens_completion}`">
                  {{ fmt(u.tokens_total) }}
                  <small>{{ fmt(u.tokens_prompt) }}/{{ fmt(u.tokens_completion) }}</small>
                </td>
              </tr>
              <tr v-if="!paged.length">
                <td colspan="13" class="empty">没有匹配的用户</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="adm-pager">
          <span>共 {{ sorted.length }} 条 · 第 {{ page }} / {{ pageCount }} 页</span>
          <div class="adm-pager-btns">
            <button class="btn sm ghost" :disabled="page <= 1" @click="page -= 1">上一页</button>
            <button class="btn sm ghost" :disabled="page >= pageCount" @click="page += 1">下一页</button>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.admin {
  /* #app 是 flex 容器，不给 width:100% 的话内容会被挤成手机宽度 */
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 18px 14px 40px;
  align-self: flex-start;
}

.adm-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.adm-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.adm-logo {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 18px;
  background: var(--grad);
  flex: 0 0 auto;
}

.adm-title b {
  display: block;
  font-size: 16px;
}

.adm-title small {
  display: block;
  font-size: 11.5px;
  color: var(--ink-3);
}

.adm-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.adm-login {
  max-width: 420px;
  margin: 6vh auto 0;
}

.adm-login h2 {
  font-size: 17px;
  margin: 0 0 8px;
}

.adm-hint {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-3);
  margin: 0 0 12px;
}

.adm-row {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin-top: 10px;
}

.adm-cards {
  display: grid;
  /* 132px 是"8 张卡刚好排成一行"的临界值（1180 容器扣掉 7 个 10px 间距）；
     用 150px 会溢出成 7+1，最后一张孤零零挂在第二行。 */
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.adm-card {
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--card);
  border: 1px solid var(--line);
}

.adm-card-label {
  font-size: 12px;
  color: var(--ink-3);
}

.adm-card-value {
  font-size: 22px;
  font-weight: 720;
  letter-spacing: -0.02em;
  margin: 2px 0;
}

.adm-card-sub {
  font-size: 11.5px;
  color: var(--ink-3);
}

/* ---------- 时间轴 ---------- */
.adm-trend {
  padding: 14px;
  margin-bottom: 14px;
  scroll-margin-top: 12px;
}

.adm-range {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 10px;
  background: var(--card-2);
  border: 1px solid var(--line);
}

.seg-btn {
  border: 0;
  background: transparent;
  padding: 5px 11px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--ink-2);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s var(--ease), color 0.15s var(--ease);
}

.seg-btn:hover {
  color: var(--ink);
}

.seg-btn.on {
  background: var(--card);
  color: var(--brand-ink);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.adm-scope {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 6px 0 10px;
  padding: 8px 11px;
  border-radius: 10px;
  background: var(--brand-weak);
  color: var(--brand-ink);
  font-size: 12px;
}

.adm-scope b {
  font-weight: 650;
}

.adm-scope-mail {
  color: var(--ink-2);
  font-size: 11.5px;
}

.adm-scope-x {
  margin-left: auto;
  border: 1px solid var(--brand-ring);
  background: transparent;
  color: var(--brand-ink);
  border-radius: 8px;
  padding: 3px 9px;
  font-size: 11.5px;
  cursor: pointer;
}

.adm-charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
  transition: opacity 0.2s var(--ease);
}

.adm-charts.dim {
  opacity: 0.45;
}

.chart-block {
  min-width: 0;
}

.chart-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}

.chart-title {
  font-size: 12.5px;
  color: var(--ink-2);
}

.chart-total {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.chart-foot {
  font-size: 11px;
  color: var(--ink-3);
  margin-top: 2px;
}

.chart-note {
  color: var(--warn-ink);
}

/* ---------- 场景拆分 ---------- */
.adm-scenes {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--line);
  display: grid;
  gap: 7px;
}

.scene-title {
  font-size: 12.5px;
  color: var(--ink-2);
  margin-bottom: 2px;
}

.scene-row {
  display: grid;
  grid-template-columns: 78px 1fr 118px;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.scene-name {
  color: var(--ink-2);
  white-space: nowrap;
}

.scene-bar {
  height: 7px;
  border-radius: 99px;
  background: var(--card-2);
  border: 1px solid var(--line);
  overflow: hidden;
}

.scene-bar i {
  display: block;
  height: 100%;
  border-radius: 99px;
  background: var(--grad);
}

.scene-val {
  text-align: right;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.scene-val small {
  display: block;
  font-size: 10.5px;
  color: var(--ink-3);
}

@media (max-width: 640px) {
  .scene-row {
    grid-template-columns: 68px 1fr 96px;
  }
}

/* ---------- 表格 ---------- */
.adm-table-card {
  padding: 14px;
}

.adm-table-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.adm-table-head h2 {
  font-size: 15px;
  margin: 0;
}

.adm-updated {
  font-size: 11.5px;
  color: var(--ink-3);
  display: block;
  margin-top: 2px;
}

.adm-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.adm-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 200px;
  max-width: 340px;
  padding: 7px 10px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--card-2);
  color: var(--ink-3);
}

.adm-search input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  font-size: 12.5px;
  color: var(--ink);
  outline: none;
  padding: 0;
}

.adm-clear {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}

.adm-filter {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 10px;
  background: var(--card-2);
  border: 1px solid var(--line);
}

.adm-size {
  flex: 0 0 auto;
  width: 108px;
  border: 1px solid var(--line);
  background: var(--card-2);
  color: var(--ink-2);
  border-radius: 10px;
  padding: 6px 8px;
  font-size: 12px;
  cursor: pointer;
}

.adm-scroll {
  overflow-x: auto;
}

.adm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  white-space: nowrap;
}

.adm-table th {
  text-align: left;
  padding: 8px 10px;
  font-size: 12px;
  color: var(--ink-3);
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  user-select: none;
}

.adm-table th:hover {
  color: var(--ink);
}

.adm-table th.num,
.adm-table td.num {
  text-align: right;
}

.adm-table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-2);
}

.adm-table td.mail {
  color: var(--ink-2);
  font-size: 12.5px;
}

.adm-table td.who b {
  color: var(--ink);
}

.adm-table td.who small,
.adm-table td.num small {
  display: block;
  font-size: 11px;
  color: var(--ink-3);
}

.adm-table tbody tr {
  cursor: pointer;
}

.adm-table tbody tr:hover {
  background: var(--card-2);
}

.adm-table tr.admin {
  background: var(--brand-weak);
}

.adm-table tr.demo {
  background: var(--card-2);
}

.adm-table tr.picked {
  background: var(--brand-soft);
  box-shadow: inset 2px 0 0 var(--brand);
}

.adm-table .tag {
  margin-left: 5px;
  font-size: 10.5px;
  padding: 1px 6px;
}

.adm-table .empty {
  text-align: center;
  color: var(--ink-3);
  padding: 24px 0;
}

.adm-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--ink-3);
  flex-wrap: wrap;
}

.adm-pager-btns {
  display: flex;
  gap: 6px;
}

@media (max-width: 640px) {
  .adm-trend .adm-table-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .adm-search {
    max-width: none;
    width: 100%;
  }
}
</style>
