<script setup>
import DataTable from './DataTable.vue'
defineProps({ rows: Array })
const columns = [
  { key: 'createdAt', label: 'Дата' },
  { key: 'actor', label: 'Пользователь' },
  { key: 'summary', label: 'Изменение' },
]
</script>

<template>
  <DataTable :columns="columns" :rows="rows" empty="Журнал изменений пока пуст.">
    <template #createdAt="{ row }">{{ new Date(row.createdAt).toLocaleString('ru-RU') }}</template>
    <template #actor="{ row }">{{ row.actor?.username }}</template>
  </DataTable>
</template>
