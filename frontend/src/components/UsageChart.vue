<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  series: { type: Array, default: () => [] },
})

const el = ref(null)
let chart = null

function render() {
  if (!chart) return
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['输入 tokens', '输出 tokens'], textStyle: { color: '#a6adbb' } },
    grid: { left: 70, right: 20, top: 36, bottom: 28 },
    xAxis: {
      type: 'category',
      data: props.series.map((d) => d.date.slice(5)),
      axisLabel: { color: '#a6adbb' },
    },
    yAxis: {
      type: 'log',
      logBase: 10,
      min: 1,
      axisLabel: { color: '#a6adbb', formatter: (v) => (v >= 10000 ? v / 10000 + '万' : v) },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
    },
    series: [
      {
        name: '输入 tokens',
        type: 'bar',
        stack: 'total',
        data: props.series.map((d) => (d.input_tokens > 0 ? d.input_tokens : null)),
        itemStyle: { color: '#4f9cf9' },
      },
      {
        name: '输出 tokens',
        type: 'bar',
        stack: 'total',
        data: props.series.map((d) => (d.output_tokens > 0 ? d.output_tokens : null)),
        itemStyle: { color: '#22c55e' },
      },
    ],
  })
}

function resize() {
  chart && chart.resize()
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart && chart.dispose()
})

watch(() => props.series, render, { deep: true })
</script>

<template>
  <div ref="el" class="w-full h-72"></div>
</template>
