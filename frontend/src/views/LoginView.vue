<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { sendEmailCode, loginByCode, setNickname, demoLogin } from '../api'
import { applyLogin } from '../store/user'

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
let timer = null

const canSend = computed(() => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim()) && cooldown.value === 0)
const canLogin = computed(() => /^\d{6}$/.test(code.value.trim()))

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
    const r = await loginByCode(email.value.trim(), code.value.trim())
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
    <div class="brand">
      <div class="logo">∑</div>
      <h1>智能拍照学习助手</h1>
      <p class="sub">拍一道不会的题，先弄懂它，再弄懂你自己</p>
    </div>

    <!-- 步骤一：邮箱 -->
    <div class="card">
      <template v-if="step === 'code0'">
        <h2>邮箱登录</h2>
        <p class="hint" style="margin-top: 0">输入邮箱，我们会发送 6 位验证码。首次登录自动创建账号。</p>
        <input
          v-model="email"
          type="email"
          inputmode="email"
          autocomplete="username"
          placeholder="you@qq.com"
          @keyup.enter="send"
        />
        <button class="btn primary block" style="margin-top: 10px" :disabled="!canSend || busy" @click="send">
          {{ busy ? '发送中…' : '发送验证码' }}
        </button>
      </template>

      <!-- 步骤二：验证码 -->
      <template v-else-if="step === 'code'">
        <h2>输入验证码</h2>
        <p class="hint" style="margin-top: 0">
          已发送至 <b>{{ email }}</b>
          <a href="javascript:void(0)" style="color: var(--brand)" @click="step = 'code0'">改邮箱</a>
        </p>
        <input
          v-model="code"
          inputmode="numeric"
          maxlength="6"
          placeholder="6 位数字"
          autocomplete="one-time-code"
          style="letter-spacing: 6px; text-align: center; font-size: 20px"
          @keyup.enter="doLogin"
        />
        <p v-if="hint" class="muted" style="font-size: 12px; margin: 8px 0 0">{{ hint }}</p>
        <p class="muted" style="font-size: 12px; margin: 4px 0 0">
          没收到？先看看垃圾邮件；{{ cooldown > 0 ? `${cooldown} 秒后可重发` : '可以重新发送' }}
        </p>

        <div class="btn-row" style="margin-top: 12px">
          <button class="btn ghost" :disabled="cooldown > 0 || busy" @click="send">
            {{ cooldown > 0 ? `${cooldown}s` : '重新发送' }}
          </button>
          <button class="btn primary" :disabled="!canLogin || busy" @click="doLogin">
            {{ busy ? '登录中…' : '登录' }}
          </button>
        </div>
      </template>

      <!-- 步骤三：昵称 -->
      <template v-else>
        <h2>给自己起个名字</h2>
        <p class="hint" style="margin-top: 0">昵称会显示在页面上，之后可以在「我的」里修改。</p>
        <input
          v-model="nickname"
          maxlength="20"
          placeholder="例如：小刘"
          @keyup.enter="saveName"
        />
        <div class="btn-row" style="margin-top: 12px">
          <button class="btn ghost" :disabled="busy" @click="finish">以后再说</button>
          <button class="btn primary" :disabled="busy" @click="saveName">保存并进入</button>
        </div>
      </template>

      <div v-if="error" class="banner err" style="margin-top: 12px">{{ error }}</div>
    </div>

    <div class="card">
      <h2>没有邮箱？</h2>
      <p class="hint" style="margin-top: 0">
        可以直接进入演示账号（含一周学习数据），或先看看题库和练习功能。
      </p>
      <button class="btn block" :disabled="busy" @click="enterDemo">进入演示账号</button>
    </div>

    <p class="muted foot">登录即表示同意仅将邮箱用于账号识别与登录，不用于其他用途。</p>
  </div>
</template>

<style scoped>
.login-screen { padding-top: 24px; }
.brand { text-align: center; margin-bottom: 18px; }
.brand .logo {
  width: 54px; height: 54px; line-height: 54px; margin: 0 auto 10px;
  border-radius: 16px; background: var(--brand); color: #fff;
  font-size: 26px; font-weight: 600;
}
.brand h1 { font-size: 19px; margin: 0 0 6px; }
.brand .sub { font-size: 12.5px; color: var(--ink-3); margin: 0; }
.foot { text-align: center; font-size: 11.5px; color: var(--ink-3); padding: 0 12px 20px; }
</style>
