<script setup>
import { inject } from 'vue'
import ProjectList from './ProjectList.vue'
const openDialog = inject('openProjectDialog')
</script>

<template>
  <aside class="sidebar">
    <RouterLink to="/home">Главная</RouterLink>
    <details open>
      <summary>Проекты</summary>
      <ProjectList />
    </details>
    <button class="primary add-project" @click="openDialog('create')">+ Добавить проект</button>
  </aside>
</template>
