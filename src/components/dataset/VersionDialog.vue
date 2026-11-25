<script setup>
import { ref } from 'vue'
import BaseDialog from '../BaseDialog.vue'
import RowsTable from './RowsTable.vue'
import { request, waitForJob } from '../../api/client'

const props = defineProps({ mode: String, dataset: Object, version: Object, configuration: Object, rows: Object })
const emit = defineEmits(['close', 'saved'])
const titles = {
  clean: 'Очистка данных', rename: 'Переименование версии', download: 'Скачивание версии',
  columns: 'Столбцы для проверки', score: 'Оценка качества',
}
const name = ref(props.mode === 'rename' ? props.version.name : '')
const selected = ref([...props.configuration.columnIds])
const missing = ref(false)
const duplicates = ref(false)
const actions = ref({})
const format = ref('csv')
const busy = ref(false)
const error = ref('')

function cleaningPlan() {
  const datasetActions = []
  if (missing.value) datasetActions.push({ code: 'drop_rows_with_missing', parameters: { columnScope: 'all', match: 'any' } })
  if (duplicates.value) datasetActions.push({ code: 'drop_duplicate_rows', parameters: { keep: 'first' } })
  const columnActions = []
  for (const column of props.version.columns) {
    const code = actions.value[column.id]
    if (code) {
      const parameters = code === 'pseudonymize'
        ? { strategy: column.dataType === 'email' ? 'email_token' : 'text_token' }
        : {}
      columnActions.push({ columnId: column.id, code, parameters })
    }
  }
  if (!datasetActions.length && !columnActions.length) throw new Error('Выберите действие очистки.')
  return {
    sourceVersionId: props.version.id,
    expectedLatestVersionId: props.dataset.latestVersionId,
    versionName: name.value, datasetActions, columnActions,
  }
}

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const id = props.version.id
    if (props.mode === 'rename') {
      await request('version', { id, method: 'PATCH', body: { name: name.value } })
    } else if (props.mode === 'download') {
      const blob = await request('download', { id, query: { format: format.value } })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = format.value === 'original' ? props.dataset.originalFile.name : props.version.name + '.csv'
      link.click()
      setTimeout(() => URL.revokeObjectURL(link.href), 1000)
      emit('close')
      return
    } else if (props.mode === 'columns') {
      const config = await request('configuration', {
        id, method: 'PUT', body: { columnIds: selected.value, expectedRevision: props.configuration.revision },
      })
      const check = await request('checks', { id, method: 'POST', body: { configurationRevision: config.revision } })
      await waitForJob(check.jobId)
    } else {
      const run = await request('cleaning', { id: props.dataset.id, method: 'POST', body: cleaningPlan() })
      await waitForJob(run.jobId)
      const result = await request('cleaningResult', { id: run.cleaningRunId })
      emit('saved', result)
      return
    }
    emit('saved', props.mode === 'clean')
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
  }
}

for (const col of props.version.columns) actions.value[col.id] = ''
</script>

<template>
  <BaseDialog :title="titles[mode]" :busy="busy" @close="emit('close')">
    <p v-if="mode === 'score'">Оценка относится к последней успешной проверке выбранных столбцов. Прочерк означает, что оценка ещё не рассчитана.</p>
    <form v-else class="dialog-form" @submit.prevent="submit">
      <label v-if="['clean', 'rename'].includes(mode)">Название версии
        <input v-model.trim="name" required maxlength="80" />
      </label>
      <template v-if="mode === 'clean'">
        <label><input type="checkbox" v-model="missing" /> Удалить строки с пропусками</label>
        <label><input type="checkbox" v-model="duplicates" /> Удалить дубликаты строк</label>
        <fieldset v-for="col in version.columns.filter(c => ['email', 'string'].includes(c.dataType))" :key="col.id">
          <legend>{{ col.name }}</legend>
          <label>Действие
            <select v-model="actions[col.id]">
              <option value="">Без изменений</option>
              <option value="trim">Убрать крайние пробелы</option>
              <option value="lowercase">Нижний регистр</option>
              <option value="pseudonymize">Обезличить</option>
            </select>
          </label>
        </fieldset>
        <h3>Первые пять строк</h3>
        <RowsTable :result="{ ...rows, items: rows.items.slice(0, 5) }" :version-id="version.id" />
      </template>
      <template v-if="mode === 'columns'">
        <label v-for="col in version.columns" :key="col.id">
          <input type="checkbox" v-model="selected" :value="col.id" /> {{ col.name }}
        </label>
      </template>
      <label v-if="mode === 'download'">Формат
        <select v-model="format">
          <option value="csv">CSV</option>
          <option v-if="version.id === dataset.originalVersionId" value="original">Исходный файл</option>
        </select>
      </label>
      <p role="alert" v-if="error">{{ error }}</p>
      <button type="button" :disabled="busy" @click="emit('close')">Отмена</button>
      <button class="primary" :disabled="busy || (mode === 'columns' && !selected.length)">
        {{ busy ? 'Обработка…' : { clean: 'Применить очистку', columns: 'Проверить выбранные', download: 'Скачать', rename: 'Сохранить' }[mode] }}
      </button>
    </form>
  </BaseDialog>
</template>
