<script setup>
import { onMounted, ref } from 'vue'
import { api, fmtTokens } from '../api.js'

const info = ref(null)
const defaults = ref({ default_total_tokens: 0, default_valid_days: 90, default_effective_from: '' })
const tiersList = ref([])
const service = ref({ base_url: '', api_key: '', app_host: '', app_port: 8000, low_percent: 20, sync_hour: 3 })
const msg = ref('')
const msgKind = ref('success')
const savingDefaults = ref(false)
const savingTiers = ref(false)
const savingService = ref(false)
const checking = ref(false)
const checkResult = ref(null)

function flash(text, kind = 'success') {
  msg.value = text
  msgKind.value = kind
  setTimeout(() => (msg.value = ''), 6000)
}

async function load() {
  try {
    const s = await api.settings()
    info.value = s
    defaults.value = {
      default_total_tokens: s.defaults.default_total_tokens,
      default_valid_days: s.defaults.default_valid_days,
      default_effective_from: s.defaults.default_effective_from || '',
    }
    service.value = {
      base_url: s.gateway.base_url,
      api_key: '',
      app_host: s.gateway.host,
      app_port: s.gateway.port,
      low_percent: Math.round(s.low_percent * 100),
      sync_hour: s.sync_hour,
    }
    tiersList.value = s.tiers.map((t) => ({
      name: t.name,
      display_name: t.display_name,
      modelsText: t.models.join('\n'),
    }))
  } catch (e) {
    flash(`加载失败：${e.message}`, 'error')
  }
}

async function saveService() {
  savingService.value = true
  try {
    const body = {
      base_url: service.value.base_url,
      app_host: service.value.app_host,
      app_port: Number(service.value.app_port),
      low_percent: Number(service.value.low_percent) / 100,
      sync_hour: Number(service.value.sync_hour),
    }
    if (service.value.api_key.trim()) body.api_key = service.value.api_key.trim()
    const r = await api.updateService(body)
    if (r.error) throw new Error(r.error.message)
    service.value.api_key = ''
    await load()
    flash(
      r.restart_required.length
        ? `已保存。${r.restart_required.join('、')}将在重启服务后生效，其余已即时生效。`
        : '已保存并即时生效'
    )
  } catch (e) {
    flash(`保存失败：${e.message}`, 'error')
  } finally {
    savingService.value = false
  }
}

async function saveDefaults() {
  savingDefaults.value = true
  try {
    await api.updateDefaults({ ...defaults.value })
    flash('全局默认已保存（仅影响之后新建的额度规则）')
  } catch (e) {
    flash(`保存失败：${e.message}`, 'error')
  } finally {
    savingDefaults.value = false
  }
}

async function saveTiers() {
  const tiers = tiersList.value.map((t) => ({
    name: t.name.trim(),
    display_name: t.display_name.trim() || t.name.trim(),
    models: t.modelsText.split('\n').map((x) => x.trim()).filter(Boolean),
  }))
  savingTiers.value = true
  try {
    const r = await api.updateTiers(tiers)
    if (r.error) throw new Error(r.error.message)
    tiersList.value = r.tiers.map((t) => ({
      name: t.name,
      display_name: t.display_name,
      modelsText: t.models.join('\n'),
    }))
    flash('档位配置已保存并立即生效')
  } catch (e) {
    flash(`保存失败：${e.message}`, 'error')
  } finally {
    savingTiers.value = false
  }
}

function addTier() {
  let i = tiersList.value.length + 1
  while (tiersList.value.some((t) => t.name === `tier${i}`)) i += 1
  tiersList.value.push({ name: `tier${i}`, display_name: '', modelsText: '' })
}

function removeTier(idx) {
  tiersList.value.splice(idx, 1)
}

async function checkUpstream() {
  checking.value = true
  checkResult.value = null
  try {
    checkResult.value = await api.upstreamCheck()
  } finally {
    checking.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <div v-if="msg" role="alert" class="alert" :class="msgKind === 'error' ? 'alert-error' : 'alert-success'">
      {{ msg }}
    </div>

    <template v-if="info">
    <!-- 服务信息 -->
    <section class="card card-border bg-base-100">
      <div class="card-body gap-3 py-4">
        <div class="flex items-center justify-between">
          <h2 class="card-title text-base">服务信息</h2>
          <button class="btn btn-sm" :disabled="checking" @click="checkUpstream">
            <span v-if="checking" class="loading loading-spinner loading-xs"></span>
            测试上游连通性
          </button>
        </div>
        <div v-if="checkResult" class="alert py-2 text-sm" :class="checkResult.ok ? 'alert-success' : 'alert-error'">
          <template v-if="checkResult.ok">
            上游正常 · HTTP {{ checkResult.status_code }} · {{ checkResult.latency_ms }}ms · 目录
            {{ checkResult.model_count ?? '?' }} 个模型
          </template>
          <template v-else>上游异常：{{ checkResult.error || `HTTP ${checkResult.status_code}` }}</template>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="fieldset sm:col-span-2">
            <span class="label text-xs">百炼端点（OpenAI 兼容 base_url）</span>
            <input v-model="service.base_url" type="text" spellcheck="false" class="input input-sm input-bordered font-mono text-xs" />
          </label>
          <label class="fieldset sm:col-span-2">
            <span class="label text-xs">
              API Key — 留空保持不变（当前 {{ info.gateway.api_key_masked }}）
            </span>
            <input v-model="service.api_key" type="password" autocomplete="new-password" placeholder="不修改请留空" class="input input-sm input-bordered font-mono text-xs" />
          </label>
          <label class="fieldset">
            <span class="label text-xs">监听地址 <span class="badge badge-warning badge-xs">需重启</span></span>
            <input v-model="service.app_host" type="text" class="input input-sm input-bordered font-mono text-xs" />
          </label>
          <label class="fieldset">
            <span class="label text-xs">监听端口 <span class="badge badge-warning badge-xs">需重启</span></span>
            <input v-model.number="service.app_port" type="number" min="1" max="65535" class="input input-sm input-bordered font-mono text-xs tabular-nums" />
          </label>
          <label class="fieldset">
            <span class="label text-xs">偏低阈值（剩余百分比，%）</span>
            <input v-model.number="service.low_percent" type="number" min="1" max="99" class="input input-sm input-bordered tabular-nums" />
          </label>
          <label class="fieldset">
            <span class="label text-xs">每日目录同步（时，0-23）<span class="badge badge-ghost badge-xs">重启后改调度</span></span>
            <input v-model.number="service.sync_hour" type="number" min="0" max="23" class="input input-sm input-bordered tabular-nums" />
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <button class="btn btn-sm btn-primary" :disabled="savingService" @click="saveService">
            <span v-if="savingService" class="loading loading-spinner loading-xs"></span>
            保存服务信息
          </button>
          <span class="text-xs opacity-50">
            保存写入 .env；端点 / Key / 阈值即时生效，监听地址与端口需重启
            <code class="font-mono">sudo systemctl restart tokentool</code>。转发地址
            <span class="font-mono">{{ info.gateway.chat_url }}</span>
          </span>
        </div>
      </div>
    </section>

    <!-- 全局默认 -->
    <section class="card card-border bg-base-100">
      <div class="card-body gap-3 py-4">
        <h2 class="card-title text-base">免费额度全局默认</h2>
        <div class="grid gap-3 sm:grid-cols-3">
          <label class="fieldset">
            <span class="label text-xs">默认总量 (tokens)</span>
            <input v-model.number="defaults.default_total_tokens" type="number" class="input input-sm input-bordered tabular-nums" />
          </label>
          <label class="fieldset">
            <span class="label text-xs">默认有效天数</span>
            <input v-model.number="defaults.default_valid_days" type="number" class="input input-sm input-bordered tabular-nums" />
          </label>
          <label class="fieldset">
            <span class="label text-xs">全局起算日（留空=按模型发布日）</span>
            <input v-model="defaults.default_effective_from" type="date" class="input input-sm input-bordered" />
          </label>
        </div>
        <div class="flex items-center gap-3">
          <button class="btn btn-sm btn-primary" :disabled="savingDefaults" @click="saveDefaults">
            <span v-if="savingDefaults" class="loading loading-spinner loading-xs"></span>
            保存默认
          </button>
          <span class="text-xs opacity-50">
            仅影响之后新建的额度规则；已有模型请到「模型目录」单独编辑。当前默认总量
            {{ fmtTokens(defaults.default_total_tokens) }}。
          </span>
        </div>
      </div>
    </section>

    <!-- 档位配置 -->
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold">档位路由</h2>
        <div class="flex gap-2">
          <button class="btn btn-sm btn-ghost" @click="addTier">+ 添加档位</button>
          <button class="btn btn-sm btn-primary" :disabled="savingTiers" @click="saveTiers">
            <span v-if="savingTiers" class="loading loading-spinner loading-xs"></span>
            保存档位
          </button>
        </div>
      </div>
      <p class="text-xs opacity-50">
        每行一个模型，<b>越靠上优先级越高</b>；链上模型耗尽/过期时自动切换到下一个。model 传档位名即按此链路由。
        保存立即生效，无需重启。
      </p>
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div v-for="(t, idx) in tiersList" :key="idx" class="card card-border bg-base-100">
          <div class="card-body gap-2 py-4">
            <div class="flex items-center gap-2">
              <label class="input input-sm flex items-center gap-1 flex-1">
                <span class="label text-xs">档位名</span>
                <input v-model="t.name" class="grow font-mono text-xs" placeholder="fast" />
              </label>
              <button class="btn btn-xs btn-ghost btn-square text-error" title="删除档位" @click="removeTier(idx)">✕</button>
            </div>
            <label class="input input-sm flex items-center gap-1">
              <span class="label text-xs">显示名</span>
              <input v-model="t.display_name" class="grow text-xs" placeholder="快速档（flash 系）" />
            </label>
            <textarea
              v-model="t.modelsText"
              class="textarea textarea-bordered font-mono text-xs leading-5"
              rows="6"
              placeholder="每行一个模型 ID"
            ></textarea>
            <div class="text-xs opacity-50">{{ t.modelsText.split('\n').filter((x) => x.trim()).length }} 个模型在链</div>
          </div>
        </div>
      </div>
    </section>
    </template>
    <div v-else class="flex justify-center py-20"><span class="loading loading-spinner loading-lg"></span></div>
  </div>
</template>
