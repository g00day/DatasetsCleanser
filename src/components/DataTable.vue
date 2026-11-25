<script setup>
defineProps({ columns: Array, rows: Array, empty: { type: String, default: 'Записей пока нет.' } })
</script>

<template>
  <div v-if="rows.length" class="table-wrap">
    <table>
      <thead><tr><th v-for="column in columns" :key="column.key">{{ column.label }}</th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row.id ?? index">
          <td v-for="column in columns" :key="column.key">
            <slot :name="column.key" :row="row">{{ row[column.key] ?? '—' }}</slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else>{{ empty }}</p>
</template>
