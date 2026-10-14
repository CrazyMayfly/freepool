<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { api, fmtTokens, STATUS_META } from '../api.js'
import UsageChart from '../components/UsageChart.vue'

const overview = ref(null)
const tiers = ref([])
const series = ref([])
const requests = ref([])
const errorMsg = ref('')
const loading = ref(false)

async function refresh() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [ov, tr, se, rq] = await Promise.all([
      api.overview(),
      api.tiers(),
      api.series(30),
      api.requests(30),
    ])
    overview.value = ov
    tiers.value = tr.tiers
    series.value = se.series
    requests.value = rq.items
  } catch (e) {
    errorMsg.value = `加载失败：${e.message}（后端是否已启动？）`
  } finally {
    loading.value = false
  }
}

let timer = null
function startAutoRefresh() {
  if (!timer) timer = setInterval(refresh, 30_000)
}
function stopAutoRefresh() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

let everActivated = false
onMounted(() => {
  refresh()
  startAutoRefresh()
})
// KeepAlive 下切走暂停轮询，切回立即刷新并恢复（首次 activated 与 mounted 重复，跳过）
onActivated(() => {
  if (!everActivated) {
    everActivated = true
    return
  }
  refresh()
  startAutoRefresh()
})
onDeactivated(stopAutoRefresh)
onBeforeUnmount(stopAutoRefresh)

const totals = computed(() => overview.value?.totals ?? {})
const models = computed(() => overview.value?.models ?? [])

function usedPercent(m) {
  return Math.min(100, Math.round(m.percent * 100))
}

function progressColor(status) {
  return { normal: 'progress-success', low: 'progress-warning', exhausted: 'progress-error', expired: 'progress-neutral', offline: 'progress-error' }[status] || 'progress-primary'
}

function statusMeta(status) {
  return STATUS_META[status] || STATUS_META.unknown
}
</script>

<template>
  <div class="space-y-6">
    <div v-if="errorMsg" role="alert" class="alert alert-error">{{ errorMsg }}</div>

    <!-- 汇总卡片 -->
    <div class="stats stats-vertical sm:stats-horizontal shadow w-full bg-base-100">
      <div class="stat">
        <div class="stat-title">免费额度总剩余</div>
        <div class="stat-value text-primary">{{ fmtTokens(totals.total_remaining) }}</div>
        <div class="stat-desc">总量 {{ fmtTokens(totals.total_free) }} · 已用 {{ fmtTokens(totals.total_used) }}</div>
      </div>
      <div class="stat">
        <div class="stat-title">今日消耗</div>
        <div class="stat-value">{{ fmtTokens(totals.today_tokens) }}</div>
        <div class="stat-desc">{{ totals.today_requests ?? 0 }} 次调用</div>
      </div>
      <div class="stat">
        <div class="stat-title">即将到期（7 天内）</div>
        <div class="stat-value" :class="totals.expiring_soon ? 'text-warning' : ''">
          {{ totals.expiring_soon ?? 0 }}
        </div>
        <div class="stat-desc">免费窗口 90 天，到期即失效</div>
      </div>
    </div>

    <!-- 档位健康度 -->
    <section class="space-y-3">
      <h2 class="text-lg font-semibold">档位路由（model 传档位名即可自动切换）</h2>
      <div class="grid gap-4 md:grid-cols-3">
        <div v-for="t in tiers" :key="t.name" class="card card-border bg-base-100">
          <div class="card-body gap-2 py-4">
            <div class="flex items-center justify-between">
              <h3 class="card-title text-base">{{ t.display_name }}</h3>
              <span class="font-mono text-xs badge badge-soft">
                model: "{{ t.name }}"
              </span>
            </div>
            <div class="text-sm">
              当前生效：
              <span v-if="t.active_model" class="badge badge-sm badge-success">{{ t.active_model }}</span>
              <span v-else class="badge badge-sm badge-error">全部不可用</span>
            </div>
            <div class="space-y-1.5">
              <div v-for="m in t.models" :key="m.model" class="text-xs">
                <div class="flex justify-between mb-0.5">
                  <span class="font-mono" :class="{ 'opacity-40': !['normal', 'low', 'unknown'].includes(m.status) }">
                    {{ m.model }}
                  </span>
                  <span class="opacity-70">{{ fmtTokens(m.remaining_tokens) }}</span>
                </div>
                <progress
                  class="progress h-1.5"
                  :class="progressColor(m.status)"
                  :value="usedPercent(m)"
                  max="100"
                ></progress>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 用量趋势 -->
    <section class="card card-border bg-base-100">
      <div class="card-body py-4">
        <h2 class="card-title text-base">近 30 天用量</h2>
        <UsageChart :series="series" />
      </div>
    </section>

    <!-- 模型额度表 -->
    <section class="card card-border bg-base-100">
      <div class="card-body py-4">
        <h2 class="card-title text-base">模型额度账本</h2>
        <div class="overflow-x-auto">
          <table class="table table-sm">
            <thead>
              <tr>
                <th>模型</th>
                <th>状态</th>
                <th class="w-56">已用进度</th>
                <th class="text-right">已用 / 总量</th>
                <th class="text-right">剩余</th>
                <th class="text-right">剩余天数</th>
                <th>到期日</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in models" :key="m.model">
                <td class="font-mono text-xs">{{ m.model }}</td>
                <td>
                  <span class="badge badge-sm" :class="statusMeta(m.status).badge">
                    {{ statusMeta(m.status).label }}
                  </span>
                </td>
                <td>
                  <div class="flex items-center gap-2">
                    <progress class="progress h-2" :class="progressColor(m.status)" :value="usedPercent(m)" max="100"></progress>
                    <span class="text-xs tabular-nums w-10">{{ usedPercent(m) }}%</span>
                  </div>
                </td>
                <td class="text-right text-xs tabular-nums">{{ fmtTokens(m.used_tokens) }} / {{ fmtTokens(m.total_tokens) }}</td>
                <td class="text-right text-xs tabular-nums">{{ fmtTokens(m.remaining_tokens) }}</td>
                <td class="text-right text-xs tabular-nums" :class="m.days_left <= 7 ? 'text-warning' : ''">
                  {{ m.days_left }}
                </td>
                <td class="text-xs opacity-70">{{ m.expires_at }}</td>
              </tr>
              <tr v-if="!models.length">
                <td colspan="7" class="text-center opacity-50 py-6">
                  {{ loading ? '加载中…' : '暂无数据，通过代理发起一次调用试试' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- 最近调用 -->
    <section class="card card-border bg-base-100">
      <div class="card-body py-4">
        <h2 class="card-title text-base">最近调用</h2>
        <div class="overflow-x-auto">
          <table class="table table-sm">
            <thead>
              <tr>
                <th>时间</th>
                <th>请求模型</th>
                <th>实际模型</th>
                <th>切换</th>
                <th class="text-right">tokens</th>
                <th class="text-right">耗时</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in requests" :key="r.id">
                <td class="text-xs opacity-70">{{ r.ts.slice(5, 19) }}</td>
                <td class="font-mono text-xs">{{ r.requested_model }}</td>
                <td class="font-mono text-xs">
                  {{ r.actual_model }}
                  <span v-if="r.stream" class="badge badge-ghost badge-xs">流</span>
                </td>
                <td>
                  <span v-if="r.switched" class="badge badge-xs badge-warning" :title="r.switch_reason">切换</span>
                  <span v-else class="opacity-30">-</span>
                </td>
                <td class="text-right text-xs tabular-nums">{{ r.total_tokens }}</td>
                <td class="text-right text-xs tabular-nums opacity-70">{{ r.duration_ms }}ms</td>
                <td>
                  <span class="badge badge-xs" :class="r.status_code === 200 ? 'badge-success' : 'badge-error'">
                    {{ r.error_code || r.status_code }}
                  </span>
                </td>
              </tr>
              <tr v-if="!requests.length">
                <td colspan="7" class="text-center opacity-50 py-6">暂无调用记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>
