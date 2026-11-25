<script setup>
import { ref, shallowRef, watch } from 'vue'

const props = defineProps({ load: { type: Function, required: true } })
const data = shallowRef()
const error = ref('')
const status = ref(0)
const revision = ref(0)

watch([() => props.load, revision], async (_, __, cleanup) => {
  let active = true
  cleanup(() => { active = false })
  data.value = undefined
  error.value = ''
  try {
    const result = await props.load()
    if (active) data.value = result
  } catch (cause) {
    if (active) {
      status.value = cause.status
      error.value = cause.message
    }
  }
}, { immediate: true })
</script>

<template>
  <div v-if="error" role="alert">
    <p>{{ status === 403 ? 'Нет доступа' : status === 404 ? 'Страница не найдена' : error }}</p>
    <RouterLink v-if="status === 401" to="/login">Войти</RouterLink>
    <button v-else @click="revision++">Повторить</button>
  </div>
  <p v-else-if="data === undefined" role="status">Загрузка…</p>
  <slot v-else :data="data" />
</template>
