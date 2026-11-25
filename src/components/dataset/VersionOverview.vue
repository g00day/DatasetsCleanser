<script setup>
import { ref } from 'vue'
import { request, list, waitForJob } from '../../api/client'
import LoadResource from '../LoadResource.vue'
import RowsTable from './RowsTable.vue'
import DataTable from '../DataTable.vue'
import AuditTable from '../AuditTable.vue'
import HistoryDialog from './HistoryDialog.vue'
import VersionDialog from './VersionDialog.vue'

const props = defineProps({ dataset: Object, id: String })
const emit = defineEmits(['saved'])
const dialog = ref('')
const filters = ref({})
const busy = ref(false)
const error = ref('')
const states = {
  ready: 'Проверка завершена', failed: 'Ошибка проверки', not_checked: 'Не проверен',
  queued: 'В очереди', running: 'Идёт проверка',
}
async function load() {
  const id = props.id
  const [version, quality, configuration, audit] = await Promise.all([
    request('version', { id }), request('quality', { id }), request('configuration', { id }),
    request('audit', { id: props.dataset.id, query: { pageSize: 5 } }),
  ])
  const checkRunId = quality.lastSuccessfulCheckRunId
  const [rows, issues] = await Promise.all([
    request('rows', { id, query: { checkRunId, pageSize: 10 } }),
    checkRunId ? list('issues', { id: checkRunId }) : [],
  ])
  return { version, quality, configuration, audit, rows, issues }
}
function showRows(filter = {}) {
  filters.value = filter
  dialog.value = 'rows'
}
async function check(revision) {
  busy.value = true
  error.value = ''
  try {
    const result = await request('checks', {
      id: props.id, method: 'POST', body: { configurationRevision: revision },
    })
    await waitForJob(result.jobId)
    emit('saved', false)
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <LoadResource :load="load" v-slot="{ data }">
    <div class="actions">
      <button class="primary" @click="dialog = 'clean'">Очистить данные</button>
      <button @click="dialog = 'download'">Скачать</button>
      <button v-if="data.version.canRename" @click="dialog = 'rename'">Переименовать версию</button>
    </div>
    <RowsTable :result="data.rows" :version-id="id" />
    <div class="actions">
      <span>Показано {{ data.rows.items.length }} из {{ data.version.rowCount }} строк</span>
      <button @click="showRows({ checkRunId: data.quality.lastSuccessfulCheckRunId })">Открыть таблицу</button>
    </div>
    <h2>Качество данных</h2>
    <p>{{ states[data.quality.status] }} <span v-if="data.quality.isStale">· Результат устарел</span></p>
    <div class="metrics">
      <div>Проверено строк<strong>{{ data.quality.result?.checkedRowCount ?? '—' }}</strong></div>
      <div>Столбцы для проверки<strong>{{ data.quality.selectedColumnCount }} из {{ data.version.columnCount }}</strong></div>
      <div>Проблем<strong>{{ data.quality.result?.issueCount ?? '—' }}</strong></div>
      <div>Оценка качества<strong>{{ data.quality.result?.qualityScore ?? '—' }}</strong></div>
    </div>
    <div class="actions">
      <button @click="dialog = 'score'">Как считается оценка?</button>
      <button @click="dialog = 'columns'">Столбцы для проверки</button>
      <button :disabled="busy" @click="check(data.configuration.revision)">{{ busy ? 'Проверяем…' : 'Проверить' }}</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <h2>Ошибки по столбцам</h2>
    <DataTable :rows="data.issues" :columns="[
      { key: 'columnName', label: 'Столбец' }, { key: 'label', label: 'Правило' },
      { key: 'issueCount', label: 'Ошибок' },
    ]">
      <template #issueCount="{ row }">
        <button @click="showRows({ checkRunId: data.quality.lastSuccessfulCheckRunId, onlyProblemRows: true, columnId: row.columnId, ruleCode: row.ruleCode })">
          {{ row.issueCount }}
        </button>
      </template>
    </DataTable>
    <header class="section-head">
      <h2>Аудит изменений</h2>
      <button @click="dialog = 'audit'">Весь журнал</button>
    </header>
    <AuditTable :rows="data.audit.items" />
    <HistoryDialog v-if="['audit', 'rows'].includes(dialog)" :mode="dialog"
      :id="dialog === 'audit' ? dataset.id : id" :filters="dialog === 'rows' ? filters : {}"
      @close="dialog = ''" />
    <VersionDialog v-else-if="dialog" :mode="dialog" :dataset="dataset"
      :version="data.version" :configuration="data.configuration" :rows="data.rows" @close="dialog = ''"
      @saved="latest => emit('saved', latest)" />
  </LoadResource>
</template>
