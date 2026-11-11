<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  sendEmailCode,
  loginByCode,
  getMe,
  adminUsers,
  adminOverview,
  demoLogin,
  logout as apiLogout,
} from '../api'
import { applyLogin, currentUser, clearLogin } from '../store/user'
import Icon from '../components/Icon.vue'

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
const sortKey = ref('questions')
const sortDesc = ref(true)

async function loadAll() {
  loading.value = true
  try {
    const [ov, list] = await Promise.all([adminOverview(), adminUsers()])
    overview.value = ov
    users.value = list.users || []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const sorted = computed(() => {
  const k = sortKey.value
  const arr = [...users.value]
  arr.sort((a, b) => {
    const va = a[k] ?? 0
    const vb = b[k] ?? 0
    const na = typeof va === 'number'
    const nb = typeof vb === 'number'
    const r = na && nb ? va - vb : String(va).localeCompare(String(vb))
    return sortDesc.value ? -r : r
  })
  return arr
})

function sortBy(k) {
  if (sortKey.value === k) sortDesc.value = !sortDesc.value
  else {
    sortKey.value = k
    sortDesc.value = true
  }
}

const cards = computed(() => {
  const o = overview.value || {}
  return [
    { label: '注册用户', value: o.users ?? 0, sub: `7 日活跃 ${o.users_active_7d ?? 0}` },
    { label: '拍照答疑', value: o.questions ?? 0, sub: `已完成 ${o.questions_answered ?? 0}` },
    { label: '练习试卷', value: o.test_sessions ?? 0, sub: `错题 ${o.wrong_books ?? 0} 条` },
    { label: '接口访问', value: o.api_hits_total ?? 0, sub: '累计（登录用户）' },
    { label: '大模型调用', value: o.llm_calls ?? 0, sub: `Token ${fmt(o.tokens_total ?? 0)}` },
    { label: '知识点覆盖', value: o.mastery_points ?? 0, sub: `诊断报告 ${o.diagnose_reports ?? 0} 份` },
  ]
})

function fmt(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
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

      <section class="card adm-table-card">
        <div class="adm-table-head">
          <h2>用户明细（{{ users.length }}）</h2>
          <span class="adm-updated">更新于 {{ fmtTime(overview?.generated_at) }}</span>
        </div>

        <div class="adm-scroll">
          <table class="adm-table">
            <thead>
              <tr>
                <th>用户</th>
                <th class="num" @click="sortBy('created_at')">注册时间</th>
                <th class="num" @click="sortBy('questions')">拍题</th>
                <th class="num" @click="sortBy('test_answered')">答题</th>
                <th class="num" @click="sortBy('api_hits')">API 访问</th>
                <th class="num" @click="sortBy('tokens_total')">Token</th>
                <th class="num" @click="sortBy('wrong_books')">错题</th>
                <th class="num" @click="sortBy('last_login_at')">最近登录</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in sorted" :key="u.id" :class="{ demo: u.is_demo, admin: u.is_admin }">
                <td class="who">
                  <b>{{ u.nickname }}</b>
                  <span class="tag" v-if="u.is_admin">管理员</span>
                  <span class="tag" v-if="u.is_demo">演示</span>
                  <small>{{ u.email || '（未绑定邮箱）' }}</small>
                </td>
                <td class="num">{{ fmtTime(u.created_at) }}</td>
                <td class="num">{{ u.questions }}</td>
                <td class="num">{{ u.test_answered }}</td>
                <td class="num">
                  {{ u.api_hits }}
                  <small v-if="u.api_hits_today">今 {{ u.api_hits_today }}</small>
                </td>
                <td class="num">
                  {{ fmt(u.tokens_total) }}
                  <small>{{ u.llm_calls }} 次</small>
                </td>
                <td class="num">{{ u.wrong_books }}</td>
                <td class="num">{{ fmtTime(u.last_login_at) }}</td>
              </tr>
              <tr v-if="!users.length">
                <td colspan="8" class="empty">暂无数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.admin {
  /* #app 是 flex 容器，不给 width:100% 的话内容会被挤成手机宽度 */
  width: 100%;
  max-width: 1120px;
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
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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

.adm-table-card {
  padding: 14px;
}

.adm-table-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.adm-table-head h2 {
  font-size: 15px;
  margin: 0;
}

.adm-updated {
  font-size: 11.5px;
  color: var(--ink-3);
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

.adm-table th.num,
.adm-table td.num {
  text-align: right;
}

.adm-table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-2);
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

.adm-table tr.admin {
  background: var(--brand-weak);
}

.adm-table tr.demo {
  background: var(--card-2);
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
</style>
