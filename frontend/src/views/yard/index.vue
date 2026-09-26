<template>
  <section class="page" data-module="yard">
    <header class="page-head">
      <div>
        <h2>箱区台账</h2>
        <p class="page-desc">围绕箱区编号、堆放层数、可用/已用箱位做筛选与状态流转；列表与导出共用同一取数口径。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记箱区</button>
        <button class="btn" type="button" :disabled="exporting" @click="exportRows">
          {{ exporting ? '正在导出…' : '导出箱区台账清单' }}
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
        <input v-model="filters.keyword" placeholder="按箱区编号检索" />
      </label>
      <label class="filter-item">
        <span>箱区状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="option in statuses" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label class="filter-check">
        <input v-model="filters.includeClosed" type="checkbox" />
        <span>包含已封闭箱区</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="exportError" class="export-error" role="alert">
      <span>{{ exportError }}</span>
      <button class="link" type="button" @click="exportRows">按当前条件重试</button>
    </p>

    <div v-if="anomalies.length" class="anomaly-panel">
      <h3>箱位与堆放层数对不上的记录（{{ anomalies.length }} 条）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>异常说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in anomalies" :key="`anomaly-${String(row.id)}`" class="anomaly-row">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="error-text">{{ row['异常说明'] }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>箱位核对</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row['箱位异常']" class="badge danger" :title="String(row['异常说明'] ?? '')">异常</span>
            <span v-else class="badge ok">正常</span>
          </td>
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
          <td :colspan="columns.length + 2" class="empty-state">当前条件下没有箱区记录，可调整筛选或登记箱区</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条箱区记录（含已封闭：{{ filters.includeClosed ? '是' : '否' }}）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

type Filters = {
  keyword: string
  status: string
  includeClosed: boolean
}

type ListPayload = {
  items: Row[]
  total: number
  anomalies: Row[]
  summary: Partial<Record<string, number>>
}

type ExportPayload = ListPayload & {
  module: string
  filters: Record<string, string | boolean>
}

const ENDPOINT = '/api/yard'
const FILTER_STORAGE_KEY = 'yard-ledger-filters'
const columns = ['箱区编号', '箱区名称', '堆放层数', '可用箱位', '已用箱位', '所属堆场', '责任人', '箱区状态']
const actions = ['启用箱区', '封闭箱区', '腾空箱区']
const statuses = ['待启用', '正常堆放', '接近满载', '已封闭']
const summaryCards = [
  { label: '在用箱区', key: '在用箱区' },
  { label: '接近满载箱区', key: '接近满载箱区' },
  { label: '可用箱位总数', key: '可用箱位总数' },
  { label: '箱位异常数', key: '箱位异常数' },
]

const rows = ref<Row[]>([])
const anomalies = ref<Row[]>([])
const total = ref(0)
const summary = ref<Partial<Record<string, number>>>({})
const errorMessage = ref('')
const exporting = ref(false)
const exportError = ref('')
const filters = ref<Filters>(loadFilters())

const stats = ref(summaryCards.map((card) => ({ label: card.label, value: 0 })))

function loadFilters(): Filters {
  const fallback: Filters = { keyword: '', status: '', includeClosed: false }
  try {
    const saved = window.localStorage.getItem(FILTER_STORAGE_KEY)
    if (!saved) {
      return fallback
    }
    const parsed = JSON.parse(saved) as Partial<Filters>
    return {
      keyword: typeof parsed.keyword === 'string' ? parsed.keyword : '',
      status: typeof parsed.status === 'string' && statuses.includes(parsed.status) ? parsed.status : '',
      includeClosed: parsed.includeClosed === true,
    }
  } catch {
    return fallback
  }
}

function persistFilters() {
  try {
    window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters.value))
  } catch {
    // 本地存储不可用时不影响查询，只是刷新后条件不保留。
  }
}

function buildQuery() {
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) {
    params.set('keyword', filters.value.keyword.trim())
  }
  if (filters.value.status) {
    params.set('status', filters.value.status)
  }
  if (filters.value.includeClosed) {
    params.set('include_closed', 'true')
  }
  return params.toString()
}

function resetFilters() {
  filters.value = { keyword: '', status: '', includeClosed: false }
  persistFilters()
  void reload()
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
      throw new Error('箱区动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '箱区操作失败'
  }
}

function applyPayload(payload: Partial<ListPayload>) {
  rows.value = payload.items ?? []
  anomalies.value = payload.anomalies ?? []
  total.value = payload.total ?? rows.value.length
  summary.value = payload.summary ?? {}
  stats.value = summaryCards.map((card) => ({
    label: card.label,
    value: summary.value[card.key] ?? 0,
  }))
}

async function reload() {
  errorMessage.value = ''
  persistFilters()
  const query = buildQuery()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('箱区列表读取失败')
    }
    applyPayload((await response.json()) as ListPayload)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '箱区台账列表读取失败'
  }
}

function csvCell(value: Row[string]) {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function toCsv(data: Row[]): string {
  const header = [...columns, '异常说明']
  const lines = [header.map(csvCell).join(',')]
  for (const row of data) {
    lines.push(header.map((column) => csvCell(row[column])).join(','))
  }
  // 加 BOM，避免 Excel 打开中文乱码。
  return `﻿${lines.join('\n')}`
}

function downloadCsv(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  window.URL.revokeObjectURL(url)
}

async function exportRows() {
  // 导出前先固化条件：即使下载失败，已选条件也原样保留，可直接重试。
  persistFilters()
  exportError.value = ''
  exporting.value = true
  try {
    const response = await request(`${ENDPOINT}/export?${buildQuery()}`)
    if (!response.ok) {
      throw new Error(`导出请求返回 ${response.status}`)
    }
    const payload = (await response.json()) as ExportPayload
    const stamp = new Date().toISOString().slice(0, 10)
    // 正常清单与异常清单分两段写入同一个文件，异常记录被单独挑出。
    const content = [
      '# 箱区台账清单（按当前筛选条件取数）',
      toCsv(payload.items ?? []),
      '',
      `# 箱位与堆放层数对不上的记录（${(payload.anomalies ?? []).length} 条）`,
      toCsv(payload.anomalies ?? []),
    ].join('\n')
    downloadCsv(`箱区台账清单-${stamp}.csv`, content)
  } catch (error) {
    const detail = error instanceof Error ? error.message : '网络异常'
    exportError.value = `清单下载失败（${detail}），已保留当前筛选条件，可重试。`
  } finally {
    exporting.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.filter-check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  align-self: flex-end;
  padding-bottom: 7px;
}

.filter-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.badge.ok {
  background: #ecfdf3;
  color: #027a48;
  border: 1px solid #abefc6;
}

.badge.danger {
  background: #fef3f2;
  color: #b42318;
  border: 1px solid #fda29b;
}

.anomaly-panel {
  margin: 12px 0;
  border: 1px solid #fda29b;
  border-radius: 8px;
  overflow: hidden;
}

.anomaly-panel h3 {
  margin: 0;
  padding: 8px 10px;
  font-size: 13px;
  background: #fef3f2;
  color: #b42318;
}

.anomaly-row {
  background: #fffafa;
}

.export-error {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
  padding: 6px 10px;
  font-size: 13px;
  color: #b42318;
  background: #fef3f2;
  border: 1px solid #fda29b;
  border-radius: 6px;
}
</style>
