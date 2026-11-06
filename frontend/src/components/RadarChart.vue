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

// 画布：宽高分别留出标签区（左右约 160px、上下约 60px）
const W = 480
const H = 420
const CX = W / 2
const CY = H / 2
const R = 106 // 数据区半径
const LR = R + 48 // 标签位置半径
const LEVELS = 4

// 每个实例独立的渐变 id，避免同页两个雷达图互相串色
const uid = Math.random().toString(36).slice(2, 7)
const fillId = `radar-fill-${uid}`
const glowId = `radar-glow-${uid}`

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

// 未练且为 0 的轴不画点：否则所有点会重叠在圆心，显得脏
const dots = computed(() =>
  props.axes
    .map((ax, i) => {
      const [x, y] = point(i, ax.value, props.axes.length)
      return { x, y, v: ax.value, practiced: ax.practiced !== false }
    })
    .filter((d) => d.practiced || d.v > 0.02)
)

// 「第十二章  常微分方程」→ 章号 + 名称，便于分行显示
function splitLabel(name) {
  const s = String(name || '').replace(/\s+/g, '')
  const m = s.match(/^(第[一二三四五六七八九十百]+章)(.*)$/)
  if (m) return { head: m[1], body: m[2] }
  return { head: '', body: s }
}

function clip(s, len) {
  return s.length > len ? s.slice(0, len - 1) + '…' : s
}

// 标签限制：轴多时更短，避免相邻标签相撞
const bodyLimit = computed(() => {
  const n = props.axes.length
  if (n > 8) return 6
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
      x: x + side * 9,
      y,
      rows,
      practiced,
      anchor: side === 1 ? 'start' : side === -1 ? 'end' : 'middle',
      idx: i,
    }
  })
)

const ariaLabel = computed(() => {
  if (!props.axes.length) return '暂无掌握度数据'
  const avg = props.axes.reduce((a, b) => a + b.value, 0) / props.axes.length
  return `掌握度雷达图，共 ${props.axes.length} 个章节，平均掌握度 ${avg.toFixed(2)}`
})

function rowFill(l, ri) {
  if (!l.practiced) return 'var(--ink-3)'
  const isValue = ri === l.rows.length - 1
  if (isValue) return props.interactive ? 'var(--brand)' : 'var(--ink-2)'
  return ri === 0 && l.rows.length === 3 ? 'var(--ink-3)' : 'var(--ink-2)'
}
</script>

<template>
  <div class="radar-wrap">
    <svg
      :viewBox="`0 0 ${W} ${H}`"
      class="radar-svg"
      :style="{ maxWidth: maxWidth + 'px' }"
      role="img"
      :aria-label="ariaLabel"
    >
      <defs>
        <linearGradient :id="fillId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--brand)" stop-opacity="0.34" />
          <stop offset="100%" stop-color="var(--brand-2)" stop-opacity="0.05" />
        </linearGradient>
        <radialGradient :id="glowId">
          <stop offset="0%" stop-color="var(--brand)" stop-opacity="0.1" />
          <stop offset="100%" stop-color="var(--brand)" stop-opacity="0" />
        </radialGradient>
      </defs>

      <!-- 圆心柔光，让数据区有层次 -->
      <circle :cx="CX" :cy="CY" :r="R * 0.98" :fill="`url(#${glowId})`" />

      <!-- 网格 -->
      <polygon
        v-for="(p, i) in gridPolys"
        :key="'g' + i"
        :points="p"
        fill="none"
        stroke="var(--line)"
        stroke-width="1"
        :stroke-opacity="i === gridPolys.length - 1 ? 1 : 0.7"
        vector-effect="non-scaling-stroke"
      />
      <!-- 轴线 -->
      <line
        v-for="(s, i) in spokes"
        :key="'s' + i"
        :x1="CX"
        :y1="CY"
        :x2="s.x"
        :y2="s.y"
        stroke="var(--line)"
        stroke-width="1"
        stroke-opacity="0.75"
        vector-effect="non-scaling-stroke"
      />

      <!-- 数据面 -->
      <polygon
        v-if="dataPoly"
        :points="dataPoly"
        :fill="`url(#${fillId})`"
        stroke="var(--brand)"
        stroke-width="2"
        stroke-linejoin="round"
        vector-effect="non-scaling-stroke"
      />

      <!-- 数据点：白色描边让小圆点更干净 -->
      <circle
        v-for="(d, i) in dots"
        :key="'d' + i"
        :cx="d.x"
        :cy="d.y"
        r="4"
        :fill="d.practiced ? 'var(--brand)' : 'var(--ink-3)'"
        stroke="var(--card)"
        stroke-width="1.8"
      />

      <!-- 轴标签（interactive 时可点击下钻） -->
      <g
        v-for="(l, i) in labels"
        :key="'l' + i"
        class="lbl-group"
        :class="{ clickable: interactive, off: !l.practiced }"
        @click="interactive && emit('select', l.idx)"
      >
        <text
          v-for="(row, ri) in l.rows"
          :key="ri"
          :x="l.x"
          :y="l.y - (l.rows.length - 1) * 6 + ri * 13"
          :text-anchor="l.anchor"
          :font-size="ri === l.rows.length - 1 ? 10.5 : 11.5"
          :font-weight="ri === l.rows.length - 1 ? 650 : 500"
          :fill="rowFill(l, ri)"
          dominant-baseline="middle"
          class="lbl-text"
          :class="{ value: ri === l.rows.length - 1 }"
        >{{ row }}</text>
        <!-- 透明热区：覆盖整个标签块 -->
        <rect
          v-if="interactive"
          :x="l.anchor === 'start' ? l.x - 6 : l.anchor === 'end' ? l.x - 80 : l.x - 44"
          :y="l.y - (l.rows.length - 1) * 6 - 9"
          width="88"
          :height="l.rows.length * 13 + 9"
          fill="transparent"
        />
      </g>
    </svg>
  </div>
</template>

<style scoped>
.radar-wrap {
  display: flex;
  justify-content: center;
}

.radar-svg {
  width: 100%;
  height: auto;
  overflow: visible;
}

.lbl-text {
  font-family: inherit;
  letter-spacing: -0.01em;
  transition: fill 0.16s var(--ease);
}

.lbl-text.value {
  font-variant-numeric: tabular-nums;
}

.lbl-group.clickable {
  cursor: pointer;
}

.lbl-group.clickable:hover .lbl-text {
  fill: var(--brand);
}

.lbl-group.clickable:hover .lbl-text.value {
  text-decoration: underline;
}

.lbl-group.off .lbl-text {
  fill: var(--ink-3);
  opacity: 0.85;
}
</style>
