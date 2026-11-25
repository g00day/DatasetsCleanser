<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import BaseDialog from '../BaseDialog.vue'
import { request, waitForJob } from '../../api/client'

const props = defineProps({ mode: String, project: Object })
const emit = defineEmits(['saved', 'close'])
const router = useRouter()
const titles = { create: 'Добавление проекта', edit: 'Настройки проекта', upload: 'Добавление датасета' }
const name = ref(props.mode === 'edit' ? props.project.name : '')
const description = ref(props.project?.description || '')
const file = ref(null)
const delimiter = ref('')
const busy = ref(false)
const error = ref('')
const picker = ref(null)

function useExample() {
  picker.value.value = ''
  file.value = new File(['id,name,email\n1,Анна,anna@example.org\n2,Иван,\n'], 'clients.csv', { type: 'text/csv' })
  if (!name.value) name.value = 'Клиенты'
}

async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (props.mode === 'upload') {
      const body = new FormData()
      body.set('name', name.value)
      body.set('file', file.value)
      if (delimiter.value) body.set('delimiter', delimiter.value)
      const result = await request('datasets', { id: props.project.id, method: 'POST', body })
      await waitForJob(result.jobId)
      await router.push('/datasets/' + result.datasetId)
    } else {
      const edit = props.mode === 'edit'
      const project = await request(edit ? 'project' : 'projects', {
        id: props.project?.id,
        method: edit ? 'PATCH' : 'POST',
        body: { name: name.value, description: description.value },
      })
      await router.push('/projects/' + project.id)
    }
    emit('saved')
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <BaseDialog :title="titles[mode]" :busy="busy" @close="emit('close')">
    <form class="dialog-form" @submit.prevent="save">
      <label>Название<input v-model.trim="name" required /></label>
      <template v-if="mode === 'upload'">
        <p>Проект: {{ project.name }}</p>
        <label>Файл CSV<input ref="picker" type="file" accept=".csv,text/csv" :required="!file" @change="file = $event.target.files[0]" /></label>
        <button type="button" @click="useExample">Использовать пример CSV</button>
        <small>{{ file?.name || 'Файл не выбран' }}</small>
        <label>Разделитель
          <select v-model="delimiter">
            <option value="">Автоматически</option>
            <option value=",">Запятая</option>
            <option value=";">Точка с запятой</option>
          </select>
        </label>
      </template>
      <label v-else>Описание<textarea v-model="description" rows="3" /></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <button class="primary" :disabled="busy">{{ busy ? 'Обработка…' : mode === 'upload' ? 'Загрузить и проверить' : 'Сохранить' }}</button>
    </form>
  </BaseDialog>
</template>
