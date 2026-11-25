<script setup>
import { ref, computed } from 'vue'
import { request } from '../../api/client'
import BaseDialog from '../BaseDialog.vue'
import LoadResource from '../LoadResource.vue'
import AuditTable from '../AuditTable.vue'
import RowsTable from './RowsTable.vue'

const props = defineProps({ mode: String, id: String, filters: Object })
defineEmits(['close'])
const page = ref(1)
const load = computed(() => {
  const query = { ...props.filters, page: page.value, pageSize: 10 }
  return () => request(props.mode, { id: props.id, query })
})
</script>

<template>
  <BaseDialog :title="mode === 'rows' ? 'Таблица данных' : 'Аудит изменений'" @close="$emit('close')">
    <LoadResource :load="load" v-slot="{ data }">
      <RowsTable v-if="mode === 'rows'" :result="data" :version-id="id" />
      <AuditTable v-else :rows="data.items" />
      <footer class="actions">
        <button :disabled="page <= 1" @click="page--">Назад</button>
        <span>{{ page }} / {{ Math.max(1, data.pagination.totalPages) }}</span>
        <button :disabled="page >= data.pagination.totalPages" @click="page++">Далее</button>
      </footer>
    </LoadResource>
  </BaseDialog>
</template>
