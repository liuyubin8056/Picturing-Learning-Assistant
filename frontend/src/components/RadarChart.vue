<script setup>
import { computed } from 'vue'

// 掌握度雷达图：后端出 JSON（/api/v1/profile/users/{id}/radar），前端手绘 SVG。
// axes: [{axis:"第一章 极限与连续", value:0.42, kp_count:3}, ...]
const props = defineProps({
  axes: { type: Array, default: () => [] },
})

const SIZE = 320
const CX = SIZE / 2
const CY = SIZE / 2 + 6
const R = 108
const LEVELS = 4

const n = computed(() => Math.max(props.axes.length, 3))

// 轴角度（从正上方开始顺时针）
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
    return { x, y, v: ax.value }
  })
)

// 轴标签：过长章节名截断成两行
function shortName(name) {
  const s = String(name || '').replace(/\s+/g, '')
  return s.length > 7 ? s.slice(0, 7) + '…' : s
}

const labels = computed(() =>
  props.axes.map((ax, i) => {
    const a = angle(i, props.axes.length)
    const lr = R + 30
    return {
      x: CX + lr * Math.cos(a),
      y: CY + lr * Math.sin(a),
      text: shortName(ax.axis),
      anchor: Math.abs(Math.cos(a)) < 0.3 ? 'middle' : Math.cos(a) > 0 ? 'start' : 'end',
    }
  })
)
</script>

<template>
  <div class="radar-wrap">
    <svg :viewBox="`0 0 ${SIZE} ${SIZE}`" class="radar-svg" role="img" aria-label="掌握度雷达图">
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
      <circle v-for="(d, i) in dots" :key="'d' + i" :cx="d.x" :cy="d.y" r="3.5" fill="#2f6bff" />
      <!-- 标签 -->
      <text
        v-for="(l, i) in labels"
        :key="'l' + i"
        :x="l.x"
        :y="l.y"
        :text-anchor="l.anchor"
        font-size="11"
        fill="#5a6b8c"
        dominant-baseline="middle"
      >{{ l.text }}</text>
    </svg>
  </div>
</template>
