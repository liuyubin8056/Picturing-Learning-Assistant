<script setup>
import { computed, ref, onMounted } from 'vue'
import {
  getWrongbook,
  markMastered,
  getProfile,
  listQuestions,
  listTests,
  setNickname,
  logout as apiLogout,
  exportMyData,
  mediaUrl,
} from '../api'
import { userId, setUserId, currentUser, clearLogin } from '../store/user'
import { useRouter } from 'vue-router'
import { mode, setMode } from '../store/theme'
import MarkdownView from '../components/MarkdownView.vue'
import Icon from '../components/Icon.vue'

const tab = ref('wrong')        // wrong | profile
const wrong = ref({ stats: {}, items: [] })
const filter = ref('')          // '' | pending | mastered
const profileMd = ref('')
const overview = ref({ questions: 0, tests: 0, signals: 0, weak: 0 })
const loading = ref(true)
const router = useRouter()

// 昵称内联编辑
const editing = ref(false)
const nameInput = ref('')

const displayName = computed(
  () => currentUser.value?.nickname || currentUser.value?.email_masked || `用户 ${userId.value}`
)

const DEMO_USER = 1001  // 汇报演示用户（scripts/seed_demo_user.py 生成）

const THEMES = [
  { value: 'light', label: '浅色', icon: 'sun' },
  { value: 'dark', label: '深色', icon: 'moon' },
  { value: 'system', label: '跟随系统', icon: 'monitor' },
]

const FILTERS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待攻克' },
  { value: 'mastered', label: '已掌握' },
]

onMounted(load)

async function load() {
  loading.value = true
  try {
    wrong.value = await getWrongbook(userId.value, filter.value || undefined)
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
    profileMd.value = prof?.markdown || ''
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
  window.__toast?.('已切换用户 ' + userId.value)
  load()
}

function startEdit() {
  nameInput.value = currentUser.value?.nickname || ''
  editing.value = true
}

async function saveName() {
  const name = nameInput.value.trim()
  if (!name) {
    window.__toast?.('昵称不能为空')
    return
  }
  try {
    currentUser.value = await setNickname(name)
    editing.value = false
    window.__toast?.('昵称已更新')
  } catch (e) {
    window.__toast?.(e.message || '更新失败')
  }
}

async function doExport() {
  try {
    await exportMyData()
    window.__toast?.('数据已开始下载')
  } catch (e) {
    window.__toast?.(e.message || '导出失败')
  }
}

async function doLogout() {
  try {
    await apiLogout()
  } catch {
    /* 令牌可能已失效，忽略 */
  }
  clearLogin()
  router.replace('/login')
}

function filterCount(value) {
  if (value === 'pending') return wrong.value.stats.pending || 0
  if (value === 'mastered') return wrong.value.stats.mastered || 0
  return wrong.value.stats.total || 0
}

function emptyText() {
  if (filter.value === 'pending') return '没有待攻克的错题'
  if (filter.value === 'mastered') return '还没有标记为掌握的错题'
  return '错题本还是空的'
}
</script>

<template>
  <div class="screen">
    <!-- 当前档案 -->
    <section class="card user-card">
      <div class="user-top">
        <div class="user-avatar"><Icon name="user" :size="24" :stroke="1.7" /></div>
        <div class="user-info">
          <div class="eyebrow">当前档案</div>
          <template v-if="editing">
            <div class="uid-field" style="margin-top: 6px">
              <input
                v-model="nameInput"
                maxlength="20"
                placeholder="输入昵称（最多 20 字）"
                aria-label="昵称"
                @keyup.enter="saveName"
              />
              <button class="btn primary" @click="saveName">保存</button>
            </div>
          </template>
          <template v-else>
            <h2>
              {{ displayName }}
              <span v-if="currentUser?.is_demo" class="chip on" style="margin-left: 6px; vertical-align: 2px">演示</span>
            </h2>
            <p>{{ currentUser?.email_masked || '演示账号（无需邮箱）' }}</p>
          </template>
        </div>
      </div>

      <div class="quick-users">
        <button v-if="!editing" class="chip" @click="startEdit">
          <Icon name="pencil" :size="13" :stroke="1.9" /> 修改昵称
        </button>
        <button v-else class="chip" @click="editing = false">取消</button>
        <button
          v-if="currentUser?.is_demo"
          class="chip"
          :class="{ on: userId === DEMO_USER }"
          @click="applyUser(DEMO_USER)"
        >
          演示数据 · {{ DEMO_USER }}
        </button>
        <button class="chip" @click="doExport">导出数据</button>
        <button class="chip danger" @click="doLogout">退出登录</button>
      </div>
      <p class="hint user-hint">
        <template v-if="currentUser?.is_demo">
          演示账号可切换到其它用户查看数据；正式账号只能访问自己的数据。
        </template>
        <template v-else>
          数据保存在后端数据库，换设备后用邮箱验证码登录即可继续。
        </template>
      </p>
    </section>

    <!-- 数据总览 -->
    <section class="card">
      <div class="card-head">
        <span class="card-ico"><Icon name="grid" :size="20" /></span>
        <div class="card-head-text">
          <div class="card-title">数据总览</div>
          <div class="card-sub">这个账号里已经发生的学习</div>
        </div>
      </div>
      <div class="ov-grid">
        <div class="ov-item">
          <span class="ov-ico"><Icon name="camera" :size="16" /></span>
          <b class="num">{{ overview.questions }}</b>
          <span>答疑记录</span>
        </div>
        <div class="ov-item">
          <span class="ov-ico teal"><Icon name="book" :size="16" /></span>
          <b class="num">{{ overview.tests }}</b>
          <span>完成练习</span>
        </div>
        <div class="ov-item">
          <span class="ov-ico amber"><Icon name="alert" :size="16" /></span>
          <b class="num">{{ wrong.stats.total || 0 }}</b>
          <span>错题</span>
        </div>
        <div class="ov-item">
          <span class="ov-ico rose"><Icon name="sparkles" :size="16" /></span>
          <b class="num">{{ overview.signals }}</b>
          <span>画像信号</span>
        </div>
      </div>
    </section>

    <!-- 页签 -->
    <div class="seg tabs">
      <button :class="{ on: tab === 'wrong' }" @click="tab = 'wrong'">
        <Icon name="book" :size="15" />
        错题本
        <em v-if="wrong.stats.total" class="seg-count">{{ wrong.stats.total }}</em>
      </button>
      <button :class="{ on: tab === 'profile' }" @click="tab = 'profile'">
        <Icon name="user" :size="15" />
        我的画像
      </button>
    </div>

    <!-- 加载骨架 -->
    <section v-if="loading" class="card">
      <div class="sk" style="width: 42%; height: 15px"></div>
      <div class="sk" style="width: 66%; height: 10px; margin-top: 10px"></div>
      <div class="sk" style="height: 120px; border-radius: 14px; margin-top: 16px"></div>
    </section>

    <!-- 错题本 -->
    <template v-else-if="tab === 'wrong'">
      <section class="card filter-card">
        <div class="wb-head">
          <b>共 {{ wrong.stats.total || 0 }} 道错题</b>
          <span class="wb-sub">待攻克 {{ wrong.stats.pending || 0 }} · 已掌握 {{ wrong.stats.mastered || 0 }}</span>
        </div>
        <div class="seg filt">
          <button
            v-for="f in FILTERS"
            :key="f.value"
            :class="{ on: filter === f.value }"
            @click="setFilter(f.value)"
          >
            {{ f.label }}
            <span class="seg-count">{{ filterCount(f.value) }}</span>
          </button>
        </div>
      </section>

      <section v-if="!wrong.items?.length" class="card empty-state">
        <div class="empty-ico" :class="{ ok: filter === 'pending' }">
          <Icon :name="filter === 'pending' ? 'award' : 'book'" :size="28" />
        </div>
        <b>{{ emptyText() }}</b>
        <p v-if="filter === 'pending'">没有待攻克的错题，继续保持。也可以去「练习」里做一组新的题。</p>
        <p v-else-if="filter === 'mastered'">把错题真正弄懂后，可以在这里标记为「已掌握」。</p>
        <p v-else>做错的题目会自动收集到这里，方便集中复盘。</p>
        <router-link v-if="filter === ''" to="/practice" class="btn ghost empty-btn">
          去做一组练习
        </router-link>
      </section>

      <article v-for="w in wrong.items" :key="w.id" class="card wrong-card">
        <div class="wc-tags">
          <span class="status-pill" :class="w.status === 'mastered' ? 'ok' : 'warn'">
            <i></i>{{ w.status === 'mastered' ? '已掌握' : '待攻克' }}
          </span>
          <span class="tag ghost">{{ w.source === 'test' ? '自测错题' : '答疑未解决' }}</span>
          <span v-if="w.wrong_count > 1" class="tag">{{ '错过 ' + w.wrong_count + ' 次' }}</span>
          <span v-for="t in (w.error_tags || [])" :key="t" class="tag err">{{ t }}</span>
        </div>

        <div v-if="w.image_path && w.source === 'test'" class="img-card wc-img">
          <img :src="mediaUrl(w.image_path)" alt="错题原图" loading="lazy" />
        </div>
        <div class="stem-box">
          <MarkdownView v-if="w.stem" :text="w.stem" />
          <span v-else class="muted">（答疑图片题，见拍照记录）</span>
        </div>

        <div v-if="w.answer" class="ans-line">
          <span class="ans-label">正确答案</span>
          <div class="ans-body"><MarkdownView :text="w.answer" /></div>
        </div>

        <details v-if="w.solution" class="sol">
          <summary>
            <span>查看库内解析</span>
            <Icon class="sol-chev" name="chevron-down" :size="15" />
          </summary>
          <div class="answer sol-body">
            <MarkdownView :text="w.solution" />
          </div>
        </details>

        <button
          class="btn block wc-btn"
          :class="w.status === 'mastered' ? 'ghost' : 'ok'"
          @click="toggleMastered(w)"
        >
          <Icon :name="w.status === 'mastered' ? 'refresh' : 'check'" :size="15" :stroke="2.4" />
          {{ w.status === 'mastered' ? '重新加入错题' : '我已掌握（掌握度 +0.2）' }}
        </button>
      </article>
    </template>

    <!-- 我的画像 -->
    <template v-else>
      <section v-if="profileMd" class="card">
        <div class="card-head">
          <span class="card-ico violet"><Icon name="user" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">学习画像</div>
            <div class="card-sub">由你的答疑反馈与练习记录自动生成</div>
          </div>
        </div>
        <div class="answer profile-md">
          <MarkdownView :text="profileMd" />
        </div>
      </section>

      <section v-else class="card empty-state">
        <div class="empty-ico"><Icon name="user" :size="28" /></div>
        <b>还没有生成画像</b>
        <p>去「拍照」问一道题并提交卡点，或做一次「练习」后，这里会出现你的专属画像。</p>
        <div class="btn-row empty-actions">
          <router-link to="/camera" class="btn primary">去拍照</router-link>
          <router-link to="/practice" class="btn ghost">去做练习</router-link>
        </div>
      </section>

      <!-- 外观设置 -->
      <section class="card">
        <div class="card-head">
          <span class="card-ico neutral"><Icon name="sun" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">外观</div>
            <div class="card-sub">选择界面亮度，设置保存在本机</div>
          </div>
        </div>

        <div class="theme-grid">
          <button
            v-for="t in THEMES"
            :key="t.value"
            class="theme-opt"
            :class="[t.value, { on: mode === t.value }]"
            @click="setMode(t.value)"
          >
            <span class="tp-ico"><Icon :name="t.icon" :size="22" :stroke="1.8" /></span>
            <span class="tp-label">{{ t.label }}</span>
            <span v-if="mode === t.value" class="tp-check"><Icon name="check" :size="11" :stroke="3" /></span>
          </button>
        </div>
        <p class="hint theme-note">深色模式在夜间刷题更护眼；选择「跟随系统」时会随手机或电脑自动切换。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* ---------- 用户卡 ---------- */
.user-card {
  padding-top: 16px;
}

.user-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  color: #fff;
  background: var(--grad);
  box-shadow: 0 8px 18px -8px rgba(76, 111, 255, 0.7);
}

.user-info {
  min-width: 0;
}

.user-info h2 {
  margin: 1px 0 2px;
  font-size: 18px;
  font-weight: 760;
  letter-spacing: -0.02em;
}

.user-info h2 .num {
  color: var(--brand-ink);
}

.user-info p {
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--ink-3);
}

.uid-field {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.uid-field input {
  flex: 1;
  min-width: 0;
}

.uid-field .btn {
  flex: 0 0 auto;
  padding: 0 20px;
}

.quick-users {
  display: flex;
  gap: 7px;
  margin-top: 9px;
}

.quick-users .chip {
  flex: 1;
  min-width: 0;
}

.user-hint {
  margin-top: 10px;
  margin-bottom: 0;
  font-size: 11px;
  line-height: 1.55;
}

/* ---------- 总览 ---------- */
.ov-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ov-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 10px 9px;
  border-radius: 13px;
  background: var(--card-2);
  text-align: center;
}

.ov-ico {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  margin: 0 auto 4px;
  border-radius: 9px;
  color: var(--brand);
  background: var(--brand-weak);
}

.ov-ico.teal {
  color: var(--ok-ink);
  background: var(--ok-weak);
}

.ov-ico.amber {
  color: var(--warn-ink);
  background: var(--warn-weak);
}

.ov-ico.rose {
  color: var(--err-ink);
  background: var(--err-weak);
}

.ov-item b {
  font-size: 19px;
  font-weight: 780;
  line-height: 1.2;
  color: var(--ink);
}

.ov-item > span:last-child {
  font-size: 10.5px;
  color: var(--ink-3);
  white-space: nowrap;
}

/* ---------- 页签 ---------- */
.tabs {
  margin-bottom: 12px;
}

.tabs button {
  gap: 6px;
}

.seg-count {
  display: inline-grid;
  place-items: center;
  min-width: 17px;
  height: 17px;
  padding: 0 5px;
  border-radius: 99px;
  background: rgba(16, 24, 40, 0.06);
  color: var(--ink-3);
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.seg button.on .seg-count {
  background: var(--brand-weak);
  color: var(--brand-ink);
}

/* ---------- 错题筛选 ---------- */
.filter-card {
  padding: 14px 16px;
}

.wb-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.wb-head b {
  font-size: 14px;
  font-weight: 700;
}

.wb-sub {
  font-size: 11.5px;
  color: var(--ink-3);
}

.filt {
  margin-top: 11px;
}

/* ---------- 空状态 ---------- */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 28px 22px 24px;
}

.empty-ico {
  display: grid;
  place-items: center;
  width: 62px;
  height: 62px;
  margin-bottom: 12px;
  border-radius: 21px;
  color: var(--brand);
  background: var(--brand-weak);
}

.empty-ico.ok {
  color: var(--ok-ink);
  background: var(--ok-weak);
}

.empty-state b {
  font-size: 15px;
  font-weight: 700;
}

.empty-state p {
  max-width: 280px;
  margin-top: 5px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-3);
}

.empty-btn,
.empty-actions {
  margin-top: 14px;
}

.empty-btn {
  text-decoration: none;
}

.empty-actions {
  display: flex;
  gap: 8px;
}

.empty-actions .btn {
  text-decoration: none;
}

/* ---------- 错题卡 ---------- */
.wrong-card {
  padding: 15px 16px 16px;
}

.wc-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 650;
}

.status-pill i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.status-pill.warn {
  color: var(--warn-ink);
  background: var(--warn-weak);
}

.status-pill.ok {
  color: var(--ok-ink);
  background: var(--ok-weak);
}

.wc-img {
  margin-bottom: 9px;
}

.wc-img img {
  display: block;
  width: 100%;
  max-height: 240px;
  object-fit: contain;
  background: var(--card-2);
}

.ans-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 10px;
  padding: 9px 11px;
  border-radius: 11px;
  background: var(--ok-weak);
  border: 1px solid rgba(16, 185, 129, 0.16);
}

.ans-label {
  flex: 0 0 auto;
  padding-top: 1px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--ok-ink);
}

.ans-body {
  min-width: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ok-ink);
}

.sol {
  margin-top: 10px;
  border-top: 1px dashed var(--line);
  padding-top: 9px;
}

.sol summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
  list-style: none;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-ink);
  user-select: none;
}

.sol summary::-webkit-details-marker {
  display: none;
}

.sol-chev {
  color: var(--ink-3);
  transition: transform 0.2s var(--ease);
}

.sol[open] .sol-chev {
  transform: rotate(180deg);
}

.sol-body {
  margin-top: 6px;
  max-height: 320px;
  overflow: auto;
}

.wc-btn {
  margin-top: 12px;
  gap: 6px;
  font-size: 13px;
}

/* ---------- 画像 ---------- */
.profile-md {
  max-height: none;
}

/* ---------- 外观 ---------- */
.theme-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}

.theme-opt {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 13px 8px 11px;
  border: 1.5px solid var(--line);
  border-radius: 14px;
  background: var(--card);
  cursor: pointer;
  transition: border-color 0.18s var(--ease), box-shadow 0.18s var(--ease);
}

.theme-opt:hover {
  border-color: var(--brand-ring);
}

.theme-opt.on {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}

.tp-ico {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 13px;
  background: var(--card-2);
  border: 1px solid var(--line-2);
  color: var(--ink-2);
}

.theme-opt.light .tp-ico {
  color: #b45309;
  background: #fef4e2;
  border-color: transparent;
}

.theme-opt.dark .tp-ico {
  color: #aebfff;
  background: #1a2444;
  border-color: transparent;
}

.theme-opt.system .tp-ico {
  color: var(--ink-2);
  background: var(--line-2);
  border-color: transparent;
}

.tp-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-2);
}

.theme-opt.on .tp-label {
  color: var(--brand-ink);
}

.tp-check {
  position: absolute;
  top: 6px;
  right: 6px;
  display: grid;
  place-items: center;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  color: #fff;
  background: var(--brand);
}

.theme-note {
  margin-top: 10px;
  margin-bottom: 0;
  font-size: 11px;
  line-height: 1.6;
}

.card-ico.violet {
  color: #7b61ff;
  background: #f2efff;
}

html[data-theme='dark'] .card-ico.violet {
  background: rgba(123, 97, 255, 0.16);
}

.chip.danger {
  color: var(--err);
  border-color: color-mix(in srgb, var(--err) 34%, transparent);
}
.chip.danger:hover {
  background: var(--err-weak);
}
</style>
