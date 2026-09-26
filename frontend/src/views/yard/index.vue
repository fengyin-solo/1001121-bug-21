<template>
  <section class="page" data-module="yard">
    <header class="page-head">
      <div>
        <h2>堆场管理管理</h2>
        <p class="page-desc">维护箱区，围绕箱区编号、箱区名称、堆放层数、可用箱位做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记箱区</button>
        <button class="btn" type="button" :disabled="exporting" @click="exportRows">
          {{ exporting ? '正在导出…' : '导出堆场管理清单' }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>箱区编号</span>
        <input v-model="keyword" placeholder="按箱区编号检索" />
      </label>
      <label class="filter-item">
        <span>箱区状态</span>
        <select v-model="status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无堆场管理数据，可先登记箱区</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条堆场管理记录</span>
      <span v-if="exportNotice" class="notice-text">{{ exportNotice }}</span>
      <span v-if="exportError" class="error-text">
        {{ exportError }}
        <button class="link" type="button" @click="exportRows">重试导出</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/yard'
const columns = ["箱区编号", "箱区名称", "堆放层数", "可用箱位", "已用箱位", "所属堆场", "责任人", "箱区状态"]
const actions = ["启用箱区", "封闭箱区", "腾空箱区"]
const statuses = ["待启用", "正常堆放", "接近满载", "已封闭"]
const stats = [{"label": "在用箱区", "value": 0}, {"label": "接近满载箱区", "value": 0}, {"label": "可用箱位总数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const exporting = ref(false)
const exportError = ref('')
const exportNotice = ref('')

function buildQuery(): string {
  const params = new URLSearchParams()
  if (keyword.value.trim()) {
    params.set('keyword', keyword.value.trim())
  }
  if (status.value) {
    params.set('status', status.value)
  }
  return params.toString()
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

async function exportRows() {
  // 导出按当前筛选条件取数；失败时条件保留在原处，点“重试导出”即可再来一次
  exporting.value = true
  exportError.value = ''
  exportNotice.value = ''
  try {
    const query = buildQuery()
    const response = await request(`${ENDPOINT}/export${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error(`导出接口返回 ${response.status}，清单未生成`)
    }
    const payload = await response.json()
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `箱区台账-${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    const mismatched = (payload.mismatched ?? []) as Row[]
    exportNotice.value = mismatched.length
      ? `已导出 ${payload.total ?? 0} 条；其中 ${mismatched.length} 条箱位与堆放层数对不上：${mismatched.map((row) => row['箱区编号']).join('、')}`
      : `已导出 ${payload.total ?? 0} 条箱区记录，箱位与堆放层数全部对得上`
  } catch (error) {
    exportError.value = error instanceof Error ? `导出失败：${error.message}` : '导出失败，请重试'
  } finally {
    exporting.value = false
  }
}

function openCreate() {
  errorMessage.value = '箱区登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('堆场管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆场管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error('箱区列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆场管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.notice-text { color: #b54708; }
.page-foot { gap: 12px; align-items: center; }
</style>
