<script setup>
import { inject } from 'vue'
import LoadResource from '../LoadResource.vue'
import { list } from '../../api/client'

const load = () => list('projects')
const openDialog = inject('openProjectDialog')
</script>

<template>
  <LoadResource :load="load" v-slot="{ data: projects }">
    <details v-for="project in projects" :key="project.id" open>
      <summary><RouterLink :to="'/projects/' + project.id">{{ project.name }}</RouterLink></summary>
      <LoadResource :load="() => list('datasets', { id: project.id })" v-slot="{ data }">
        <RouterLink v-for="dataset in data" :key="dataset.id" :to="'/datasets/' + dataset.id">
          {{ dataset.name }}
        </RouterLink>
      </LoadResource>
      <button class="primary" @click="openDialog('upload', project)">+ Добавить датасет</button>
    </details>
  </LoadResource>
</template>
