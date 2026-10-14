<script setup>
import { ref } from 'vue'
import Dashboard from './views/Dashboard.vue'
import Models from './views/Models.vue'
import Config from './views/Config.vue'

const tab = ref('dashboard')
</script>

<template>
  <div class="min-h-screen bg-base-200">
    <div class="navbar bg-base-100 shadow-sm">
      <div class="navbar-start">
        <span class="text-lg font-bold px-2">freepool</span>
        <span class="badge badge-soft badge-secondary ms-1">免费额度聚合网关</span>
      </div>
      <div class="navbar-end">
        <div role="tablist" class="tabs tabs-box">
          <button
            role="tab"
            class="tab"
            :class="{ 'tab-active': tab === 'dashboard' }"
            @click="tab = 'dashboard'"
          >
            额度看板
          </button>
          <button
            role="tab"
            class="tab"
            :class="{ 'tab-active': tab === 'models' }"
            @click="tab = 'models'"
          >
            模型目录
          </button>
          <button
            role="tab"
            class="tab"
            :class="{ 'tab-active': tab === 'config' }"
            @click="tab = 'config'"
          >
            配置
          </button>
        </div>
      </div>
    </div>

    <main class="p-4 max-w-7xl mx-auto">
      <Dashboard v-if="tab === 'dashboard'" />
      <Models v-else-if="tab === 'models'" />
      <Config v-else />
    </main>
  </div>
</template>
