<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '../../api/client'
import LoadResource from '../LoadResource.vue'

const router = useRouter()
const error = ref('')
const load = () => request('me')
async function logout() {
  try {
    await request('logout', { method: 'POST' })
    await router.replace('/login')
  } catch (cause) {
    error.value = cause.message
  }
}
</script>

<template>
  <LoadResource :load="load" v-slot="{ data }">
    <details class="user-menu">
      <summary><b class="avatar">{{ data.username?.[0] }}</b> {{ data.username }}</summary>
      <button @click="logout">Выйти</button>
      <p v-if="error" role="alert">{{ error }}</p>
    </details>
  </LoadResource>
</template>
