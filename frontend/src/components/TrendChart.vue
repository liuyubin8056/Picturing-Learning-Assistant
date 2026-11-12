<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

// 面积折线图：管理后台的「按天用量」时间轴。
// 不引第三方图表库（项目里只有手写 SVG 的 RadarChart），
// 用 ResizeObserver 拿真实像素宽度再算坐标——固定 viewBox 缩放在宽屏上会把文字一起放大变糊。
const props = defineProps({
  points: { type: Array, default: () => [] },   // [{ day: 'YYYY-MM-DD', value: n, ... }]
  valueKey: { type: String, default: 'value' },
  color: { type: String, default: '#4c6fff' },
  height: { type: Number, default: 148 },
  unit: { type: String, default: '' },
})

const wrap = ref(null)
const width = ref(680)
const hover = ref(-1)
let ro = null

const PAD = { l: 46, r: 14, t: 14, b: 22 }

onMounted(() => {
  if (!wrap.value) return
  width.value = wrap.value.clientWidth || 680
  ro = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect?.width || 0
    if (w > 0) width.value = w
  })
  ro.observe(wrap.value)
})
onBeforeUnmount(() => ro?.disconnect())

const vals = computed(() => props.points.map((p) => Number(p[props.valueKey] ?? 0)))

// Y 轴顶端取"好看的整数"：直接 max*1.18 会得到 304 / 203 / 101 这种刻度，
// 读数时要在脑子里换算，很别扭。这里把刻度步长吸到 1/2/5×10^n，再乘 3 段。
const maxV = computed(() => {
  const m = Math.max(0, ...vals.value)
  if (m <= 0) return 1
  const rough = (m * 1.05) / 3
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const norm = rough / mag
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag
  return step * 3
})
const innerW = computed(() => Math.max(40, width.value - PAD.l - PAD.r))
const innerH = computed(() => Math.max(30, props.height - PAD.t - PAD.b))

function xAt(i) {
  const n = vals.value.length
  if (n <= 1) return PAD.l + innerW.value / 2
  return PAD.l + (innerW.value * i) / (n - 1)
}
function yAt(v) {
  return PAD.t + innerH.value * (1 - v / maxV.value)
}

const linePath = computed(() =>
  vals.value.map((v, i) => `${i ? 'L' : 'M'}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(' ')
)
const areaPath = computed(() => {
  const n = vals.value.length
  if (!n) return ''
  const base = (PAD.t + innerH.value).toFixed(1)
  return `${linePath.value} L${xAt(n - 1).toFixed(1)},${base} L${xAt(0).toFixed(1)},${base} Z`
})

const yTicks = computed(() =>
  Array.from({ length: 4 }, (_, i) => {
    const v = (maxV.value * i) / 3
    return { v, y: yAt(v) }
  })
)

const xTicks = computed(() => {
  const n = props.points.length
  if (!n) return []
  const idxs =
    n <= 4
      ? [...Array(n).keys()]
      : [0, Math.round((n - 1) * 0.25), Math.round((n - 1) * 0.5), Math.round((n - 1) * 0.75), n - 1]
  return [...new Set(idxs)].map((i) => ({ i, x: xAt(i), day: props.points[i].day }))
})

function fmt(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k'
  return String(Math.round(n))
}

const md = (day) => (day || '').slice(5)   // 2026-11-12 → 11-12

const hoverPoint = computed(() => {
  if (hover.value < 0 || !props.points[hover.value]) return null
  const i = hover.value
  return { x: xAt(i), y: yAt(vals.value[i]), day: props.points[i].day, value: vals.value[i] }
})

function onMove(e) {
  const n = vals.value.length
  if (!n || !wrap.value) return
  const rect = wrap.value.getBoundingClientRect()
  const ratio = (e.clientX - rect.left - PAD.l) / innerW.value
  hover.value = Math.min(n - 1, Math.max(0, Math.round(ratio * (n - 1))))
}

const gradId = `trend-grad-${Math.random().toString(36).slice(2, 8)}`
</script>

<template>
  <div ref="wrap" class="trend" :style="{ height: height + 'px' }" @mousemove="onMove" @mouseleave="hover = -1">
    <svg v-if="points.length" :width="width" :height="height" class="trend-svg">
      <defs>
        <linearGradient :id="gradId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity="0.26" />
          <stop offset="100%" :stop-color="color" stop-opacity="0.02" />
        </linearGradient>
      </defs>

      <!-- 网格与 Y 轴刻度 -->
      <g>
        <line
          v-for="(t, i) in yTicks"
          :key="'g' + i"
          :x1="PAD.l"
          :x2="width - PAD.r"
          :y1="t.y"
          :y2="t.y"
          class="grid"
        />
        <text v-for="(t, i) in yTicks" :key="'y' + i" :x="PAD.l - 8" :y="t.y + 4" class="axis" text-anchor="end">
          {{ fmt(t.v) }}
        </text>
      </g>

      <!-- X 轴日期 -->
      <text
        v-for="t in xTicks"
        :key="'x' + t.i"
        :x="t.x"
        :y="height - 6"
        class="axis"
        :text-anchor="t.i === 0 ? 'start' : t.i === points.length - 1 ? 'end' : 'middle'"
      >
        {{ md(t.day) }}
      </text>

      <path :d="areaPath" :fill="`url(#${gradId})`" />
      <path :d="linePath" fill="none" :stroke="color" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />

      <!-- 悬浮：竖线 + 圆点 -->
      <g v-if="hoverPoint">
        <line :x1="hoverPoint.x" :x2="hoverPoint.x" :y1="PAD.t" :y2="PAD.t + innerH" class="cursor" />
        <circle :cx="hoverPoint.x" :cy="hoverPoint.y" r="4.5" :fill="color" stroke="#fff" stroke-width="2" />
      </g>
    </svg>

    <div v-else class="trend-empty">暂无数据</div>

    <div
      v-if="hoverPoint"
      class="tip"
      :style="{ left: Math.min(Math.max(hoverPoint.x, 62), width - 62) + 'px', top: Math.max(hoverPoint.y - 46, 0) + 'px' }"
    >
      <b>{{ hoverPoint.day }}</b>
      <span>{{ hoverPoint.value.toLocaleString() }}{{ unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.trend {
  position: relative;
  width: 100%;
  overflow: hidden;
}
.trend-svg {
  display: block;
}
.grid {
  stroke: var(--line);
  stroke-width: 1;
  stroke-dasharray: 3 4;
}
.axis {
  fill: var(--ink-3);
  font-size: 10.5px;
}
.cursor {
  stroke: var(--ink-3);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.trend-empty {
  height: 100%;
  display: grid;
  place-items: center;
  font-size: 12px;
  color: var(--ink-3);
}
.tip {
  position: absolute;
  transform: translateX(-50%);
  padding: 6px 9px;
  border-radius: 9px;
  background: var(--ink);
  color: var(--card);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
  pointer-events: none;
  box-shadow: 0 6px 16px -8px rgba(0, 0, 0, 0.45);
}
.tip b {
  display: block;
  font-weight: 600;
  opacity: 0.75;
  font-size: 10.5px;
}
.tip span {
  font-weight: 700;
  font-size: 12.5px;
}
</style>
