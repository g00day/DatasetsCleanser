<script setup>
import { ref } from 'vue'
import { request } from '../../api/client'

const props = defineProps({ result: Object, versionId: String })
const fullValue = ref(null)
async function readCell(row, cell) {
  try {
    const result = await request('cell', {
      id: props.versionId,
      params: { row: row.rowIndex, column: cell.columnId },
    })
    fullValue.value = result.value
  } catch (error) {
    fullValue.value = error.message
  }
}
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead><tr><th>№</th><th v-for="col in result.columns" :key="col.id">{{ col.name }}</th></tr></thead>
      <tbody>
        <tr v-for="row in result.items" :key="row.rowIndex">
          <th>{{ row.rowNumber }}</th>
          <td v-for="cell in row.cells" :key="cell.columnId" :class="{ issue: cell.issues?.length }"
            :title="cell.issues?.map(issue => issue.message).join(', ')">
            <button v-if="cell.isTruncated" @click="readCell(row, cell)">{{ cell.displayValue }}…</button>
            <template v-else>{{ cell.displayValue ?? cell.value ?? '—' }}</template>
            <small v-for="issue in cell.issues" :key="issue.ruleCode" class="issue-message">
              {{ issue.message }}
            </small>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-if="!result.items.length">Подходящих строк нет.</p>
  <p v-if="fullValue !== null" role="status">{{ fullValue }}</p>
</template>
