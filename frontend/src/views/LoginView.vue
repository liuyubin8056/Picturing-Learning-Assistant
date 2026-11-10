<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { sendEmailCode, loginByCode, setNickname, demoLogin } from '../api'
import { applyLogin } from '../store/user'
import Icon from '../components/Icon.vue'

// 组件名：App.vue 的 keep-alive 用它把登录页排除在缓存外
defineOptions({ name: 'LoginView' })

const router = useRouter()
const route = useRoute()

const email = ref('')
const code = ref('')
const nickname = ref('')
const step = ref('code0')      // code0=填邮箱 → code=填验证码 → nickname=填昵称
const busy = ref(false)
const error = ref('')
const hint = ref('')
const cooldown = ref(0)
// 隐私政策同意：不勾选不允许发送验证码
const agreed = ref(false)
let timer = null

const canSend = computed(
  () => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim()) && cooldown.value === 0 && agreed.value
)
const canLogin = computed(() => /^\d{6}$/.test(code.value.trim()))

const STEPS = [
  { key: 'code0', no: 1, label: '邮箱' },
  { key: 'code', no: 2, label: '验证码' },
  { key: 'nickname', no: 3, label: '昵称' },
]
const stepIndex = computed(() => STEPS.findIndex((s) => s.key === step.value))

function startCooldown(sec) {
  cooldown.value = sec
  clearInterval(timer)
  timer = setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) clearInterval(timer)
  }, 1000)
}

onUnmounted(() => clearInterval(timer))

async function send() {
  if (!canSend.value || busy.value) return
  busy.value = true
  error.value = ''
  hint.value = ''
  try {
    const r = await sendEmailCode(email.value.trim())
    step.value = 'code'
    startCooldown(r.cooldown || 60)
    hint.value = r.hint || '验证码已发出'
    // 本地开发（MAIL_PROVIDER=console）时后端会回显验证码，省得去翻日志
    if (r.debug_code) {
      code.value = r.debug_code
      hint.value = '本地开发模式：验证码已自动填入'
    }
  } catch (e) {
    error.value = e.message || '发送失败'
  } finally {
    busy.value = false
  }
}

async function doLogin() {
  if (!canLogin.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await loginByCode(email.value.trim(), code.value.trim(), agreed.value)
    applyLogin(r)
    if (r.is_new || !r.user?.nickname) {
      step.value = 'nickname'
    } else {
      finish()
    }
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    busy.value = false
  }
}

async function saveName() {
  const name = nickname.value.trim()
  if (!name) {
    finish()   // 允许跳过，昵称以后在「我的」里改
    return
  }
  busy.value = true
  try {
    await setNickname(name)
    window.__toast?.('昵称已保存')
  } catch (e) {
    error.value = e.message || '保存失败'
  } finally {
    busy.value = false
    finish()
  }
}

function finish() {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/camera'
  router.replace(target)
}

async function enterDemo() {
  busy.value = true
  error.value = ''
  try {
    const r = await demoLogin()
    applyLogin(r)
    window.__toast?.('已进入演示账号')
    finish()
  } catch (e) {
    error.value = e.message || '演示登录不可用（可能未开启或演示账号不存在）'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="screen login-screen">
    <!-- 首屏引导 -->
    <section class="hero">
      <span class="hero-eq one">∫</span>
      <span class="hero-eq two">∑</span>
      <span class="hero-eq three">lim</span>
      <p class="hero-eyebrow">
        <Icon name="sparkles" :size="13" :stroke="2" />
        学习档案
      </p>
      <h2 class="hero-title">先登录，<br />再看今天的题</h2>
      <p class="hero-sub">邮箱验证码登录，不用记密码；进度跟着账号走，换设备也能接着练。</p>
      <div class="hero-chips">
        <span>免密码</span>
        <span>跨设备同步</span>
        <span>仅用于识别</span>
      </div>
    </section>

    <!-- 步骤条 -->
    <div class="steps">
      <template v-for="(s, i) in STEPS" :key="s.key">
        <span class="step" :class="{ on: i === stepIndex, done: i < stepIndex }">
          <b>{{ i < stepIndex ? '✓' : s.no }}</b>{{ s.label }}
        </span>
        <i v-if="i < STEPS.length - 1" class="step-line" :class="{ done: i < stepIndex }"></i>
      </template>
    </div>

    <section class="card">
      <!-- 步骤一：邮箱 -->
      <template v-if="step === 'code0'">
        <div class="card-head">
          <span class="card-ico"><Icon name="user" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">邮箱登录</div>
            <div class="card-sub">输入邮箱，我们会发送 6 位验证码；首次登录自动创建账号</div>
          </div>
        </div>
        <input
          v-model="email"
          type="email"
          inputmode="email"
          autocomplete="username"
          placeholder="you@qq.com"
          aria-label="邮箱"
          @keyup.enter="send"
        />
        <button class="btn primary block" style="margin-top: 12px" :disabled="!canSend || busy" @click="send">
          <Icon name="send" :size="16" :stroke="1.9" />
          {{ busy ? '发送中…' : '发送验证码' }}
        </button>
      </template>

      <!-- 步骤二：验证码 -->
      <template v-else-if="step === 'code'">
        <div class="card-head">
          <span class="card-ico"><Icon name="lock" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">输入验证码</div>
            <div class="card-sub">
              已发送至 <b>{{ email }}</b> ·
              <a class="link" href="javascript:void(0)" @click="step = 'code0'">改邮箱</a>
            </div>
          </div>
        </div>
        <input
          v-model="code"
          class="code-input"
          inputmode="numeric"
          maxlength="6"
          placeholder="6 位数字"
          autocomplete="one-time-code"
          aria-label="验证码"
          @keyup.enter="doLogin"
        />
        <p v-if="hint" class="hint" style="margin-top: 8px">{{ hint }}</p>
        <p class="muted" style="font-size: 12px; margin: 6px 0 0">
          <Icon name="info" :size="12" :stroke="1.9" />
          没收到？先看看垃圾邮件；{{ cooldown > 0 ? `${cooldown} 秒后可重发` : '可以重新发送' }}
        </p>

        <div class="btn-row" style="margin-top: 14px">
          <button class="btn ghost" :disabled="cooldown > 0 || busy" @click="send">
            {{ cooldown > 0 ? `${cooldown}s 后重发` : '重新发送' }}
          </button>
          <button class="btn primary" :disabled="!canLogin || busy" @click="doLogin">
            {{ busy ? '登录中…' : '登录' }}
          </button>
        </div>
      </template>

      <!-- 步骤三：昵称 -->
      <template v-else>
        <div class="card-head">
          <span class="card-ico"><Icon name="award" :size="20" /></span>
          <div class="card-head-text">
            <div class="card-title">给自己起个名字</div>
            <div class="card-sub">昵称会显示在页面上，之后可以在「我的」里修改</div>
          </div>
        </div>
        <input
          v-model="nickname"
          maxlength="20"
          placeholder="例如：小刘"
          aria-label="昵称"
          @keyup.enter="saveName"
        />
        <div class="btn-row" style="margin-top: 14px">
          <button class="btn ghost" :disabled="busy" @click="finish">以后再说</button>
          <button class="btn primary" :disabled="busy" @click="saveName">保存并进入</button>
        </div>
      </template>

      <label class="consent-row">
        <input v-model="agreed" type="checkbox" />
        <span>
          我已阅读并同意
          <a href="#/privacy" target="_blank" rel="noopener">《隐私政策与用户协议》</a>
        </span>
      </label>

      <div v-if="error" class="banner err" style="margin-top: 12px">
        <Icon name="alert" :size="15" :stroke="2" />
        <span>{{ error }}</span>
      </div>
    </section>

    <section class="card demo-card">
      <div class="card-head">
        <span class="card-ico neutral"><Icon name="play" :size="20" /></span>
        <div class="card-head-text">
          <div class="card-title">先看看效果</div>
          <div class="card-sub">演示账号自带一周学习数据，可以随便点</div>
        </div>
      </div>
      <button class="btn block" :disabled="busy" @click="enterDemo">
        进入演示账号
      </button>
    </section>

    <p class="foot">
      <Icon name="lock" :size="11" :stroke="2" />
      邮箱仅用于账号识别与登录，不用于其他用途
    </p>
  </div>
</template>

<style scoped>
.login-screen {
  padding-top: 14px;
}

/* ---------- Hero ---------- */
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
.hero-eq {
  position: absolute;
  font-family: Georgia, 'Times New Roman', serif;
  font-style: italic;
  color: #fff;
  opacity: 0.14;
  pointer-events: none;
  line-height: 1;
}
.hero-eq.one { right: 22px; top: 26px; font-size: 56px; }
.hero-eq.two { right: 58px; bottom: 30px; font-size: 34px; opacity: 0.11; }
.hero-eq.three { right: 92px; top: 86px; font-size: 18px; opacity: 0.1; }

.hero-eyebrow {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  background: rgba(255, 255, 255, 0.16);
  font-size: 11.5px;
  font-weight: 600;
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

/* ---------- 步骤条 ---------- */
.steps {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 2px 12px;
}
.step {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-3);
  white-space: nowrap;
}
.step b {
  display: grid;
  place-items: center;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  border: 1.5px solid var(--line);
  background: var(--card);
  font-size: 10px;
  font-weight: 700;
  color: var(--ink-3);
}
.step.on {
  color: var(--brand);
  font-weight: 600;
}
.step.on b {
  border-color: var(--brand);
  background: var(--brand);
  color: #fff;
}
.step.done {
  color: var(--ink-2);
}
.step.done b {
  border-color: var(--brand-ring);
  background: var(--brand-weak);
  color: var(--brand);
}
.step-line {
  flex: 1;
  height: 1.5px;
  border-radius: 2px;
  background: var(--line);
}
.step-line.done {
  background: var(--brand-ring);
}

/* ---------- 验证码输入 ---------- */
.code-input {
  letter-spacing: 8px;
  text-align: center;
  font-size: 20px;
  font-weight: 700;
}

.demo-card {
  margin-top: 12px;
}

.consent-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 14px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-2);
  cursor: pointer;
}
.consent-row input {
  width: 16px;
  height: 16px;
  margin: 1px 0 0;
  flex: 0 0 auto;
  accent-color: var(--brand);
}
.consent-row a {
  color: var(--brand);
  text-decoration: none;
}
.consent-row a:hover { text-decoration: underline; }

.foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 14px 12px 22px;
  font-size: 11.5px;
  color: var(--ink-3);
}
</style>
