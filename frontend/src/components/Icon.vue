<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  stroke: { type: [Number, String], default: 1.8 },
})

const ICONS = {
  camera: {
    paths: [
      'M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z',
    ],
    circles: [[12, 13, 3.2]],
  },
  pencil: {
    paths: ['M12 20h9', 'M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z'],
  },
  chart: {
    paths: ['M3 3v18h18', 'M7 16v-4', 'M12 16V8', 'M17 16v-7'],
  },
  user: {
    paths: ['M4.5 20.5a7.5 7.5 0 0 1 15 0'],
    circles: [[12, 8, 3.7]],
  },
  sparkles: {
    paths: [
      'M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9Z',
      'M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7Z',
    ],
  },
  upload: {
    paths: ['M12 15.5V4', 'm7 9 5-5 5 5', 'M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3'],
  },
  // 与 upload 相反：用于「导入数据」
  download: {
    paths: ['M12 4v11.5', 'm7 10.5 5 5 5-5', 'M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3'],
  },
  check: { paths: ['M20 6 9 17l-5-5'] },
  'chevron-right': { paths: ['m9 18 6-6-6-6'] },
  'chevron-down': { paths: ['m6 9 6 6 6-6'] },
  'chevron-up': { paths: ['m18 15-6-6-6 6'] },
  refresh: {
    paths: ['M21 12a9 9 0 1 1-2.6-6.4L21 8', 'M21 3v5h-5'],
  },
  lock: {
    paths: ['M7 11V7a5 5 0 0 1 10 0v4', 'M5.5 11h13A1.5 1.5 0 0 1 20 12.5v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19.5v-7A1.5 1.5 0 0 1 5.5 11Z'],
  },
  bulb: {
    paths: ['M9 18h6', 'M10 21.5h4', 'M12 2.5a6.5 6.5 0 0 0-3.8 11.8c.6.4.8 1 .8 1.7v.5h6v-.5c0-.7.2-1.3.8-1.7A6.5 6.5 0 0 0 12 2.5Z'],
  },
  history: {
    paths: ['M3 12a9 9 0 1 0 2.6-6.4L3 8', 'M3 3v5h5', 'M12 7.5V12l3 1.8'],
  },
  image: {
    paths: ['M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z', 'm21 15-4.2-4.2L7 20.5'],
    circles: [[9.2, 9.2, 1.8]],
  },
  sun: {
    paths: ['M12 2.5v2', 'M12 19.5v2', 'M2.5 12h2', 'M19.5 12h2', 'M5.2 5.2l1.4 1.4', 'M17.4 17.4l1.4 1.4', 'M5.2 18.8l1.4-1.4', 'M17.4 6.6l1.4-1.4'],
    circles: [[12, 12, 4]],
  },
  moon: { paths: ['M20.9 13.2A8.6 8.6 0 1 1 10.8 3.1a6.9 6.9 0 0 0 10.1 10.1Z'] },
  monitor: {
    paths: [
      'M4 3.5h16A1.5 1.5 0 0 1 21.5 5v9A1.5 1.5 0 0 1 20 15.5H4A1.5 1.5 0 0 1 2.5 14V5A1.5 1.5 0 0 1 4 3.5Z',
      'M8.5 20h7',
      'M12 15.5V20',
    ],
  },
  'arrow-right': { paths: ['M4.5 12h15', 'm13.5 6 6 6-6 6'] },
  clock: { paths: ['M12 7.5V12l3 1.8'], circles: [[12, 12, 8.5]] },
  award: { paths: ['m8.6 13.4-1.6 7.1 5-3 5 3-1.6-7.1'], circles: [[12, 8.5, 5.5]] },
  book: {
    paths: ['M12 7v14', 'M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z'],
  },
  alert: {
    paths: ['M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z', 'M12 9v4', 'M12 17h.01'],
  },
  info: {
    paths: ['M12 11v5', 'M12 7.8h.01'],
    circles: [[12, 12, 9]],
  },
  scan: {
    paths: ['M3 7V5.5A2.5 2.5 0 0 1 5.5 3H7', 'M17 3h1.5A2.5 2.5 0 0 1 21 5.5V7', 'M21 17v1.5a2.5 2.5 0 0 1-2.5 2.5H17', 'M7 21H5.5A2.5 2.5 0 0 1 3 18.5V17', 'M7 12h10'],
  },
  send: { paths: ['m21.5 2.5-7.3 20-4-8.7-8.7-4Z', 'M21.5 2.5 10.2 13.8'] },
  target: {
    paths: [],
    circles: [[12, 12, 9], [12, 12, 5], [12, 12, 1.2, 'currentColor']],
  },
  flame: {
    paths: ['M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1.1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.1.4-2.3 1-3a2.5 2.5 0 0 0 2.5 2.5Z'],
  },
  grid: { paths: ['M3 3h7v7H3z', 'M14 3h7v7h-7z', 'M14 14h7v7h-7z', 'M3 14h7v7H3z'] },
  list: { paths: ['M8.5 6h12', 'M8.5 12h12', 'M8.5 18h12', 'M3.6 6h.01', 'M3.6 12h.01', 'M3.6 18h.01'] },
  play: { paths: ['m8 4.8 11 7.2-11 7.2z'] },
  plus: { paths: ['M12 5v14', 'M5 12h14'] },
  x: { paths: ['M18 6 6 18', 'M6 6l12 12'] },
}

const icon = computed(() => ICONS[props.name] || ICONS.sparkles)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="stroke"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
    class="ic-svg"
  >
    <path v-for="(d, i) in icon.paths" :key="`p${i}`" :d="d" />
    <circle
      v-for="(c, i) in icon.circles || []"
      :key="`c${i}`"
      :cx="c[0]"
      :cy="c[1]"
      :r="c[2]"
      :fill="c[3] || 'none'"
    />
  </svg>
</template>

<style scoped>
.ic-svg {
  display: block;
  flex: 0 0 auto;
}
</style>
