<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const items = ref([])
const keyword = ref('')
const syncing = ref(false)
const syncMsg = ref('')
const page = ref(1)
const PAGE_SIZE = 50

// 额度规则编辑弹窗
const editing = ref(null)
const form = ref({ total_tokens: 0, effective_from: '', valid_days: 90, used_offset: 0, exhausted: false })
const saving = ref(false)

async function load() {
  const data = await api.catalog()
  items.value = data.items
}

async function sync() {
  syncing.value = true
  syncMsg.value = ''
  try {
    const r = await api.syncCatalog()
    syncMsg.value = `已同步 ${r.models} 个模型、${r.limits} 条限流`
    await load()
  } catch (e) {
    syncMsg.value = `同步失败：${e.message}`
  } finally {
    syncing.value = false
  }
}

async function openEdit(model) {
  // 用看板数据预填当前规则
  const ov = await api.overview()
  const m = ov.models.find((x) => x.model === model)
  editing.value = model
  form.value = {
    total_tokens: m?.total_tokens ?? 1_000_000,
    effective_from: m?.effective_from ?? new Date().toISOString().slice(0, 10),
    valid_days: m?.valid_days ?? 90,
    used_offset: m?.used_offset ?? 0,
    exhausted: m?.status === 'exhausted',
  }
}

async function save() {
  saving.value = true
  try {
    await api.updateQuota(editing.value, { ...form.value })
    editing.value = null
    await load() // 刷新"额度规则"列的 编辑/设置 标记
  } finally {
    saving.value = false
  }
}

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return items.value
  return items.value.filter(
    (i) => i.model.toLowerCase().includes(k) || (i.provider || '').toLowerCase().includes(k)
  )
})

const paged = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filtered.value.slice(start, start + PAGE_SIZE)
})

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))

watch([keyword, () => items.value.length], () => {
  page.value = 1
})

function gotoPage(p) {
  page.value = Math.min(Math.max(1, p), totalPages.value)
}

function onKeydown(e) {
  if (e.key === 'Escape' && editing.value) editing.value = null
}

let everActivated = false
onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
})
onActivated(() => {
  // KeepAlive 下首次 activated 紧跟 mounted，跳过避免重复拉取；之后切回时静默刷新
  if (!everActivated) {
    everActivated = true
    return
  }
  load()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <input
        v-model="keyword"
        type="text"
        placeholder="按模型 / 厂商筛选…"
        class="input input-sm input-bordered w-72"
      />
      <button class="btn btn-sm btn-primary" :disabled="syncing" @click="sync">
        <span v-if="syncing" class="loading loading-spinner loading-xs"></span>
        同步官方目录
      </button>
      <span class="text-xs opacity-70">{{ syncMsg || `共 ${filtered.length} 个模型（来自百炼 ListModels）` }}</span>
    </div>

    <div class="card card-border bg-base-100">
      <div class="card-body py-4">
        <div class="overflow-x-auto max-h-[70vh] overflow-y-auto">
          <table class="table table-sm table-pin-rows">
            <thead>
              <tr>
                <th>模型</th>
                <th>名称</th>
                <th>厂商</th>
                <th>能力</th>
                <th class="text-right">上下文</th>
                <th>发布时间</th>
                <th class="text-right">限流</th>
                <th>额度规则</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="i in paged" :key="i.model">
                <td class="font-mono text-xs">{{ i.model }}</td>
                <td class="text-xs opacity-70 max-w-40 truncate">{{ i.name }}</td>
                <td>
                  <span class="badge badge-ghost badge-xs">{{ i.provider }}</span>
                </td>
                <td>
                  <span v-for="c in (i.capabilities || []).slice(0, 3)" :key="c" class="badge badge-soft badge-xs me-0.5">
                    {{ c }}
                  </span>
                </td>
                <td class="text-right text-xs tabular-nums">
                  {{ i.context_window ? (i.context_window / 1000).toFixed(0) + 'K' : '-' }}
                </td>
                <td class="text-xs opacity-70">{{ (i.published_time || '').slice(0, 10) || '-' }}</td>
                <td class="text-right text-xs opacity-70">
                  <template v-if="i.rate_limit?.request_limit">
                    {{ i.rate_limit.request_limit }}次/{{ i.rate_limit.request_limit_period }}s
                  </template>
                  <template v-else>-</template>
                </td>
                <td>
                  <button class="btn btn-xs btn-ghost" @click="openEdit(i.model)">
                    {{ i.has_quota_rule ? '编辑' : '设置' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex justify-center mt-3" v-if="totalPages > 1">
          <div class="join">
            <button class="join-item btn btn-sm" :disabled="page === 1" @click="gotoPage(page - 1)">«</button>
            <button
              v-for="p in totalPages"
              :key="p"
              class="join-item btn btn-sm"
              :class="{ 'btn-active': p === page }"
              @click="gotoPage(p)"
            >
              {{ p }}
            </button>
            <button class="join-item btn btn-sm" :disabled="page === totalPages" @click="gotoPage(page + 1)">»</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 额度规则编辑 -->
    <dialog class="modal" :class="{ 'modal-open': !!editing }" @close="editing = null">
      <div class="modal-box" v-if="editing">
        <h3 class="font-bold text-lg">额度规则 · <span class="font-mono text-sm">{{ editing }}</span></h3>
        <div class="py-4 space-y-3">
          <label class="input input-sm flex items-center gap-2">
            <span class="label text-xs">免费总量 (tokens)</span>
            <input v-model.number="form.total_tokens" type="number" class="grow tabular-nums" />
          </label>
          <label class="input input-sm flex items-center gap-2">
            <span class="label text-xs">起算日</span>
            <input v-model="form.effective_from" type="date" class="grow" />
          </label>
          <label class="input input-sm flex items-center gap-2">
            <span class="label text-xs">有效天数</span>
            <input v-model.number="form.valid_days" type="number" class="grow tabular-nums" />
          </label>
          <label class="input input-sm flex items-center gap-2">
            <span class="label text-xs">接入前已用 (offset)</span>
            <input v-model.number="form.used_offset" type="number" class="grow tabular-nums" />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="form.exhausted" type="checkbox" class="toggle toggle-error toggle-sm" />
            标记为已耗尽（触发档位切换，重置额度后取消勾选）
          </label>
        </div>
        <div class="modal-action">
          <button class="btn btn-sm" @click="editing = null">取消</button>
          <button class="btn btn-sm btn-primary" :disabled="saving" @click="save">
            <span v-if="saving" class="loading loading-spinner loading-xs"></span>
            保存
          </button>
        </div>
      </div>
      <form method="dialog" class="modal-backdrop" @submit="editing = null"><button>close</button></form>
    </dialog>
  </div>
</template>
