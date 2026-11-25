<script setup>
import { inject } from 'vue'
import { list, request } from '../../api/client'
import LoadResource from '../../components/LoadResource.vue'
import DataTable from '../../components/DataTable.vue'
import AuditTable from '../../components/AuditTable.vue'

const props = defineProps({ id: String })
const openDialog = inject('openProjectDialog')
const load = () => Promise.all([
  request('project', { id: props.id }),
  list('datasets', { id: props.id, query: { includeSchema: true } }),
  request('projectAudit', { id: props.id, query: { pageSize: 5 } }),
])
const columns = [
  { key: 'name', label: 'Датасет' },
  { key: 'rowCount', label: 'Строк' },
  { key: 'columnCount', label: 'Столбцов' },
]
</script>

<template>
  <LoadResource :load="load" v-slot="{ data }">
    <small><RouterLink to="/home">Главная</RouterLink> / {{ data[0].name }}</small>
    <header class="section-head">
      <h1>{{ data[0].name }}</h1>
      <button @click="openDialog('edit', data[0])">Настройки проекта</button>
    </header>
    <p>{{ data[0].description }}</p>
    <header class="section-head">
      <h2>Датасеты</h2>
      <button class="primary" @click="openDialog('upload', data[0])">+ Добавить датасет</button>
    </header>
    <DataTable :rows="data[1]" :columns="columns" empty="В проекте пока нет датасетов.">
      <template #name="{ row }"><RouterLink :to="'/datasets/' + row.id">{{ row.name }}</RouterLink></template>
    </DataTable>
    <section v-for="dataset in data[1]" :key="dataset.id">
      <template v-if="Array.isArray(dataset.schema)">
        <h2>Структура · {{ dataset.name }}</h2>
        <DataTable :rows="dataset.schema" :columns="[
          { key: 'name', label: 'Столбец' },
          { key: 'dataType', label: 'Тип данных' },
        ]" />
      </template>
    </section>
    <h2>Аудит изменений</h2>
    <AuditTable :rows="data[2].items" />
  </LoadResource>
</template>
