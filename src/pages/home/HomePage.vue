<script setup>
import DataTable from '../../components/DataTable.vue'
import LoadResource from '../../components/LoadResource.vue'
import { request, list } from '../../api/client'

const load = () => Promise.all([request('dashboard'), list('uploads')])
const columns = [
  { key: 'datasetName', label: 'Датасет' },
  { key: 'projectName', label: 'Проект' },
  { key: 'uploadedAt', label: 'Дата загрузки' },
]
</script>

<template>
  <small>Главная</small>
  <h1>Главная</h1>
  <LoadResource :load="load" v-slot="{ data }">
    <div class="metrics">
      <div>Проектов<strong>{{ data[0].projectCount }}</strong></div>
      <div>Датасетов<strong>{{ data[0].datasetCount }}</strong></div>
    </div>
    <h2>История загрузки датасетов</h2>
    <DataTable :columns="columns" :rows="data[1]" empty="Вы ещё не загружали датасеты.">
      <template #datasetName="{ row }">
        <RouterLink :to="'/datasets/' + row.datasetId">{{ row.datasetName }}</RouterLink>
      </template>
      <template #projectName="{ row }">
        <RouterLink :to="'/projects/' + row.projectId">{{ row.projectName }}</RouterLink>
      </template>
      <template #uploadedAt="{ row }">{{ new Date(row.uploadedAt).toLocaleString('ru-RU') }}</template>
    </DataTable>
  </LoadResource>
</template>
