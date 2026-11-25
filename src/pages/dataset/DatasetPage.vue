<script setup>
import { ref } from 'vue'
import { request, list } from '../../api/client'
import LoadResource from '../../components/LoadResource.vue'
import VersionOverview from '../../components/dataset/VersionOverview.vue'

const props = defineProps({ id: String })
const selected = ref('')
const revision = ref(0)
const cleaning = ref(null)
async function load() {
  const [dataset, versions] = await Promise.all([
    request('dataset', { id: props.id }),
    list('versions', { id: props.id, query: { sort: 'number:desc' } }),
  ])
  if (!versions.some(v => v.id === selected.value)) selected.value = dataset.latestVersionId
  return { dataset, versions }
}
function refresh(result) {
  if (result?.resultVersionId) {
    selected.value = result.resultVersionId
    cleaning.value = result
  }
  revision.value++
}
</script>

<template>
  <LoadResource :key="revision" :load="load" v-slot="{ data }">
    <small>
      <RouterLink to="/home">Главная</RouterLink> /
      <RouterLink :to="'/projects/' + data.dataset.project.id">{{ data.dataset.project.name }}</RouterLink> /
      {{ data.dataset.name }}
    </small>
    <h1>{{ data.dataset.name }}</h1>
    <template v-if="selected">
      <label>Версия
        <select v-model="selected">
          <option v-for="version in data.versions" :key="version.id" :value="version.id">
            {{ version.number }} · {{ version.name }}
          </option>
        </select>
      </label>
      <p v-if="cleaning?.resultVersionId === selected" role="status">
        Очистка завершена. Удалено строк: {{ cleaning.removedRowCount }}.
        Изменено значений: {{ cleaning.changedCellCount }}.
      </p>
      <VersionOverview :key="selected" :id="selected" :dataset="data.dataset" @saved="refresh" />
    </template>
    <p v-else>{{ data.dataset.status === 'import_failed' ? 'Ошибка загрузки' : 'Идёт обработка файла…' }}
      <button @click="refresh(false)">Обновить</button>
    </p>
  </LoadResource>
</template>
