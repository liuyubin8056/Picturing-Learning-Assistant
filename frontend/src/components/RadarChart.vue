<script setup>
import { computed } from 'vue'

// 掌握度雷达图：后端出 JSON，前端手绘 SVG。
// 支持任意边数（全书 12 章 → 正十二边形；单章知识点 → 正 N 边形）。
// 布局要点：viewBox 留足标签空间 + 标签分行（章号/名称/数值），
// 避免长章节名被画布边界裁掉（此前的显示问题即由此而来）。
const props = defineProps({
  axes: { type: Array, default: () => [] },
  interactive: { type: Boolean, default: false },
  maxWidth: { type: Number, default: 380 },
})
const emit = defineEmits(['select'])

// 画布：宽高分别留出标签区（左右约 150px、上下约 60px）
const W = 440
const H = 400
const CX = W / 2
const CY = H / 2 - 5
const R = 100            // 数据区半径
const LR = R + 46        // 标签位置半径
const LEVELS = 4

const n = computed(() => Math.max(props.axes.length, 3))

function angle(i, count) {
  return (Math.PI * 2 * i) / count - Math.PI / 2
}

function point(i, value, count) {
  const a = angle(i, count)
  const r = R * Math.max(0.02, Math.min(1, value))
  return [CX + r * Math.cos(a), CY + r * Math.sin(a)]
}

const gridPolys = computed(() => {
  const arr = []
  for (let lv = 1; lv <= LEVELS; lv++) {
    const r = (R * lv) / LEVELS
    const pts = []
    for (let i = 0; i < n.value; i++) {
      const a = angle(i, n.value)
      pts.push(`${CX + r * Math.cos(a)},${CY + r * Math.sin(a)}`)
    }
    arr.push(pts.join(' '))
  }
  return arr
})

const spokes = computed(() =>
  Array.from({ length: n.value }, (_, i) => {
    const a = angle(i, n.value)
    return { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) }
  })
)

const dataPoly = computed(() => {
  if (!props.axes.length) return ''
  return props.axes
    .map((ax, i) => {
      const [x, y] = point(i, ax.value, props.axes.length)
      return `${x},${y}`
    })
    .join(' ')
})

const dots = computed(() =>
  props.axes.map((ax, i) => {
    const [x, y] = point(i, ax.value, props.axes.length)
    return { x, y, v: ax.value, practiced: ax.practiced !== false }
  })
)

// 「第十二章  常微分方程」→ 章号 + 名称，便于分行显示
function splitLabel(name) {
  const s = String(name || '').replace(/\s+/g, '')
  const m = s.match(/^(第[一二三四五六七八九十百]+章)(.*)$/)
  if (m) return { head: m[1], body: m[2] }
  return { head: '', body: s }
}

function clip(s, len) {
  // 截断后追加省略号，总长仍受 len 约束（否则会超出宽度限制）
  return s.length > len ? s.slice(0, len - 1) + '…' : s
}

// 标签限制：轴多时更短，避免相邻标签相撞
const bodyLimit = computed(() => {
  const n = props.axes.length
  if (n > 8) return 5
  if (n <= 3) return 6
  return 7
})

const labels = computed(() =>
  props.axes.map((ax, i) => {
    const a = angle(i, props.axes.length)
    const x = CX + LR * Math.cos(a)
    const y = CY + LR * Math.sin(a)
    const cos = Math.cos(a)
    const side = cos > 0.2 ? 1 : cos < -0.2 ? -1 : 0
    const { head, body } = splitLabel(ax.axis)
    const practiced = ax.practiced !== false
    // 三行排布：章号 → 名称 → 数值；无章号时省略第一行
    const rows = head
      ? [head, clip(body, bodyLimit.value), ax.value.toFixed(2)]
      : [clip(body, bodyLimit.value), ax.value.toFixed(2)]
    return {
      x: x + side * 8,
      y,
      rows,
      practiced,
      anchor: side === 1 ? 'start' : side === -1 ? 'end' : 'middle',
      idx: i,
    }
  })
)
</script>

<template>
  <div class="radar-wrap">
    <svg
      :viewBox="`0 0 ${W} ${H}`"
      class="radar-svg"
      :style="{ maxWidth: maxWidth + 'px' }"
      role="img"
      aria-label="掌握度雷达图"
    >
      <!-- 网格 -->
      <polygon
        v-for="(p, i) in gridPolys"
        :key="'g' + i"
        :points="p"
        fill="none"
        stroke="#e5e9f2"
        stroke-width="1"
      />
      <!-- 轴线 -->
      <line
        v-for="(s, i) in spokes"
        :key="'s' + i"
        :x1="CX"
        :y1="CY"
        :x2="s.x"
        :y2="s.y"
        stroke="#e5e9f2"
        stroke-width="1"
      />
      <!-- 数据面 -->
      <polygon
        v-if="dataPoly"
        :points="dataPoly"
        fill="rgba(47,107,255,0.18)"
        stroke="#2f6bff"
        stroke-width="2"
        stroke-linejoin="round"
      />
      <circle
        v-for="(d, i) in dots"
        :key="'d' + i"
        :cx="d.x"
        :cy="d.y"
        r="3.5"
        :fill="d.practiced ? '#2f6bff' : '#c3cbd9'"
      />

      <!-- 轴标签（interactive 时可点击下钻） -->
      <g
        v-for="(l, i) in labels"
        :key="'l' + i"
        :class="{ clickable: interactive }"
        @click="interactive && emit('select', l.idx)"
      >
        <text
          v-for="(row, ri) in l.rows"
          :key="ri"
          :x="l.x"
          :y="l.y - (l.rows.length - 1) * 6 + ri * 13"
          :text-anchor="l.anchor"
          :font-size="ri === l.rows.length - 1 ? 10 : 11.5"
          :fill="!l.practiced ? '#b6c0d0' : ri === 0 && l.rows.length === 3 ? '#8b97ad' : interactive ? '#2f6bff' : '#5a6b8c'"
          dominant-baseline="middle"
        >{{ row }}</text>
        <!-- 透明热区：覆盖整个标签块 -->
        <rect
          v-if="interactive"
          :x="l.anchor === 'start' ? l.x - 6 : l.anchor === 'end' ? l.x - 74 : l.x - 40"
          :y="l.y - (l.rows.length - 1) * 6 - 8"
          width="80"
          :height="l.rows.length * 13 + 8"
          fill="transparent"
        />
      </g>
    </svg>
  </div>
</template>

<style scoped>
.radar-svg { width: 100%; height: auto; }
.clickable { cursor: pointer; }
.clickable:hover text { text-decoration: underline; }
</style>
